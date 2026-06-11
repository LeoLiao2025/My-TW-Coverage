"""
detect_changes.py — Flag tickers whose financial signals suggest a business change.

Part of the /quarterly-review workflow. Run AFTER a data refresh
(update_valuation.py / update_financials.py) and BEFORE committing it,
so the working tree holds this quarter's data and git HEAD holds last quarter's.

Signals (any one triggers a flag):
  1. Market cap change vs git HEAD          (default ±30%)
  2. Latest-quarter revenue QoQ swing       (default ±40%)
  3. Gross/Operating margin QoQ swing       (default ±10 percentage points)

Flagged tickers are candidates for enrichment review — a big financial swing
often means a business change (new product cycle, M&A, lost customer) that
the 業務簡介/供應鏈 sections may not reflect yet.

Usage:
  python scripts/detect_changes.py                          # ALL tickers
  python scripts/detect_changes.py 2330 2317                # specific tickers
  python scripts/detect_changes.py --sector Semiconductors  # by sector
  python scripts/detect_changes.py --batch 101              # by batch

Options:
  --base HEAD        Git ref to compare market cap against (default HEAD;
                     use e.g. HEAD~1 if the refresh was already committed)
  --mcap-pct 30      Market cap change threshold (%)
  --rev-pct 40       Revenue QoQ change threshold (%)
  --margin-pp 10     Margin QoQ change threshold (percentage points)
  --json out.json    Also write results as JSON
"""

import json
import os
import re
import subprocess
import sys

from utils import (
    PROJECT_ROOT,
    find_ticker_files,
    get_ticker_from_filename,
    parse_scope_args,
    setup_stdout,
)


def parse_number(s):
    s = s.strip().replace(",", "")
    if not s or s in {"-", "N/A"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def get_market_cap(content):
    m = re.search(r"\*\*市值:\*\* ([\d,]+) 百萬台幣", content)
    return parse_number(m.group(1)) if m else None


def quarterly_row(content, label):
    """Return the quarterly-table row values for a metric, latest quarter first."""
    parts = content.split("### 季度關鍵財務數據", 1)
    if len(parts) < 2:
        return []
    for line in parts[1].splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0] == label:
            return [parse_number(c) for c in cells[1:]]
    return []


def get_base_content(filepath, base):
    """Read the file as it was at the base git ref. Returns None if absent."""
    rel = os.path.relpath(filepath, PROJECT_ROOT).replace(os.sep, "/")
    result = subprocess.run(
        ["git", "show", f"{base}:{rel}"],
        cwd=PROJECT_ROOT,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace")


def detect(filepath, mcap_pct, rev_pct, margin_pp, base):
    """Return a list of signal strings for one report file."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    signals = []

    # Signal 1: market cap vs base ref
    new_mcap = get_market_cap(content)
    if new_mcap:
        old = get_base_content(filepath, base)
        old_mcap = get_market_cap(old) if old else None
        if old_mcap:
            pct = (new_mcap - old_mcap) / old_mcap * 100
            if abs(pct) >= mcap_pct:
                signals.append(
                    f"市值 {pct:+.1f}% ({old_mcap:,.0f} → {new_mcap:,.0f} 百萬台幣)"
                )

    # Signal 2: latest-quarter revenue QoQ
    rev = quarterly_row(content, "Revenue")
    if len(rev) >= 2 and rev[0] and rev[1]:
        pct = (rev[0] - rev[1]) / abs(rev[1]) * 100
        if abs(pct) >= rev_pct:
            signals.append(f"最新季營收 QoQ {pct:+.1f}% ({rev[1]:,.0f} → {rev[0]:,.0f})")

    # Signal 3: margin swings QoQ
    for label, zh in [("Gross Margin (%)", "毛利率"), ("Operating Margin (%)", "營益率")]:
        vals = quarterly_row(content, label)
        if len(vals) >= 2 and vals[0] is not None and vals[1] is not None:
            diff = vals[0] - vals[1]
            if abs(diff) >= margin_pp:
                signals.append(f"{zh} QoQ {diff:+.1f}pp ({vals[1]:.1f}% → {vals[0]:.1f}%)")

    return signals


def main():
    setup_stdout()
    args = list(sys.argv[1:])

    def pop_opt(name, default, cast=float):
        if name in args:
            i = args.index(name)
            if i + 1 >= len(args):
                print(f"Error: {name} requires a value")
                sys.exit(1)
            val = cast(args[i + 1])
            del args[i : i + 2]
            return val
        return default

    mcap_pct = pop_opt("--mcap-pct", 30.0)
    rev_pct = pop_opt("--rev-pct", 40.0)
    margin_pp = pop_opt("--margin-pp", 10.0)
    json_out = pop_opt("--json", None, str)
    base = pop_opt("--base", "HEAD", str)

    tickers, sector, desc = parse_scope_args(args)
    files = find_ticker_files(tickers, sector)

    print(f"Detecting change signals for {desc}...")
    print(f"Base: {base} | Thresholds: 市值 ±{mcap_pct:g}% | 營收 QoQ ±{rev_pct:g}% | Margin ±{margin_pp:g}pp")
    print(f"Found {len(files)} files.\n")

    flagged = {}
    for ticker in sorted(files):
        fp = files[ticker]
        try:
            signals = detect(fp, mcap_pct, rev_pct, margin_pp, base)
        except Exception as e:
            print(f"  {ticker}: ERROR ({e})")
            continue
        if signals:
            _, name = get_ticker_from_filename(fp)
            sec = os.path.basename(os.path.dirname(fp))
            flagged[ticker] = {"name": name, "sector": sec, "signals": signals}
            print(f"FLAGGED: {ticker} {name} ({sec})")
            for s in signals:
                print(f"  - {s}")

    print(f"\nDone. Scanned: {len(files)} | Flagged: {len(flagged)}")

    if json_out:
        payload = {
            "thresholds": {"mcap_pct": mcap_pct, "rev_pct": rev_pct, "margin_pp": margin_pp},
            "flagged": flagged,
        }
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"JSON written to {json_out}")


if __name__ == "__main__":
    main()
