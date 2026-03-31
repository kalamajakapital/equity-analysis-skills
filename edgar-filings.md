---
description: Download SEC EDGAR 10-K and 10-Q filings into the repo research tree using the local edgar-filings CLI.
---

Download SEC EDGAR filings into the repo using the local `edgar-filings` CLI.

## Before running — environment check

**Stop immediately** if either variable is missing from the environment. Do not invent or guess values. Raise it as a blocking issue and ask the user to set them.

```bash
echo $SEC_EDGAR_EMAIL        # must be non-empty
echo $SEC_EDGAR_COMPANY_NAME # must be non-empty
```

If either is missing, respond with:

> **Blocked:** `SEC_EDGAR_EMAIL` / `SEC_EDGAR_COMPANY_NAME` is not set. Add it to your shell environment or to a `.env` file at the repo root before running this skill.

Only proceed once both are confirmed present.

## CLI reference — exact options only

Do not invent options. The CLI accepts only the following:

```
--ticker TEXT            Required. Ticker symbol, e.g. AAPL
--filing TEXT            Form type to download. Repeatable. Default: 10-K
                         Accepted: 10-K, 10-Q, 20-F, 40-F, 6-K, 8-K
--range-start YYYY-MM-DD Lower bound on filing date. If set, downloads all
                         matching filings in range.
--range-end YYYY-MM-DD   Upper bound on filing date. Defaults to today.
--output-format TEXT     txt (default) | html | raw
```

There is no `--output-dir`. Output path is always `research/data/<TICKER>/filings/` — derived automatically.

## Invocation

```bash
.venv/bin/edgar-filings --ticker AAPL
.venv/bin/edgar-filings --ticker AAPL --filing 10-K --filing 10-Q
.venv/bin/edgar-filings --ticker AAPL --filing 10-K --range-start 2021-01-01 --range-end 2026-03-31
.venv/bin/edgar-filings --ticker AAPL --output-format html
```

When the user does not specify a filing type, default to `10-K`.
When the user does not specify a date range, omit both flags — the CLI fetches the latest filing.
Always use `--output-format txt` unless the user explicitly requests otherwise.

## After a successful fetch

Report the files written under `research/data/<TICKER>/filings/`. Then prepend an entry to `research/results/<TICKER>/CHANGELOG.md` following the format and self-reporting rules in `CLAUDE.md`. Set Workflow to `edgar-filings`, list the files written under "Memos written", and set Primary source to "SEC EDGAR".
