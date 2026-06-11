---
name: quarterly-review
description: Quarterly maintenance workflow — refresh data, detect business changes, selectively update enrichment for changed companies only
user_invocable: true
---

# Quarterly Review

季度巡檢流程：全量刷新財務數據（免費）→ 用便宜的訊號找出「業務可能有變」的公司 → 只對確認有變動的公司做 AI 研究更新。避免全量重做 enrichment 的 token 浪費。

## Usage

- `/quarterly-review` — full workflow, all sectors
- `/quarterly-review --sector Semiconductors` — limit to one sector
- `/quarterly-review --focus 液冷散熱 CPO` — additionally check specific themes/buzzwords

## Instructions

### Step 0: Data Refresh (free, ~30-90 min, run in background)

Ask the user which refresh to run (default: valuation; use financials if a new earnings season has passed since last review):

```bash
python scripts/update_valuation.py     # prices + multiples + market cap (~30 min)
python scripts/update_financials.py    # + full annual/quarterly tables (~60-90 min)
```

**Do NOT commit yet** — Step 1 needs the uncommitted diff. Report any Failed tickers and retry them once.

### Step 1: Financial Anomaly Screen (free, Python)

```bash
python scripts/detect_changes.py --json detect_results.json
```

Compares working tree vs git HEAD (market cap) and latest quarterly swings (revenue QoQ, margin pp). Flagged tickers = candidates whose business may have changed. Thresholds adjustable: `--mcap-pct 30 --rev-pct 40 --margin-pp 10`.

After this step, commit + push the data refresh (`chore: 季度數據更新 YYYY-QN`). Delete detect_results.json after the review (do not commit it).

### Step 2: Market-Level News Scan (low token)

Do NOT search per-ticker. Run ~15-25 market-level web searches:

1. `台股 本季 購併 合併 收購` / `台股 重大轉型 分割 更名`
2. `公開資訊觀測站 重大訊息` highlights for the quarter
3. Sector dynamics for major sectors: `半導體 供應鏈 變化 [year]Q[n]`, `AI 伺服器 台廠`, etc.
4. Each `--focus` buzzword: run `python scripts/discover.py "<buzzword>"` first; if results are thin, web-search `"<buzzword>" 台股 概念股 供應鏈`
5. For each flagged ticker from Step 1 with an extreme signal (>2x threshold), one targeted search: `[ticker] [company] 新聞`

Map every finding to tickers in Pilot_Reports/ (verify filename = company, Golden Rule #2).

### Step 3: Present Candidates (user decides)

Merge Step 1 + Step 2 into one table and present to the user:

```
| 代號 | 公司 | 訊號來源 | 變動內容 | 建議 |
|---|---|---|---|---|
| XXXX | 公司名 | 財務異常/新聞 | 一句話描述 | 更新/觀察/略過 |
```

Ask the user to confirm which tickers to update. Do not proceed without confirmation.

### Step 4: Selective Enrichment Update (medium token, confirmed tickers only)

For each confirmed ticker, follow the `/update-enrichment` skill workflow:
research → verify identity → write enrichment JSON → apply → audit.

Then rebuild indexes:

```bash
python scripts/audit_batch.py --all -v
python scripts/build_wikilink_index.py
python scripts/build_themes.py
python scripts/build_network.py
```

### Step 5: Log + Commit

1. Append one entry to `maintenance_log.md`: review date, refresh type, tickers updated and why, tickers flagged-but-skipped (so next quarter can re-check them).
2. Commit + push: `chore: 季度巡檢 YYYY-QN — 更新 N 檔 enrichment`.
3. Remind the user of anything left unresolved (failed tickers, deferred candidates).

## Quality Rules

- All Golden Rules in CLAUDE.md apply, especially #2 (filename is ground truth) and #5 (財務概況 tables are sacred — enrichment edits never touch them).
- Generic buzzwords are not wikilinks — only specific proper nouns.
- The candidate list is a triage tool, not a verdict: a financial swing alone does not justify rewriting enrichment. Only update when research confirms an actual business change.
