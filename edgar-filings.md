---
description: Download SEC EDGAR 10-K and 10-Q filings into the repo research tree using the local edgar-filings CLI.
---

Download SEC EDGAR filings into the repo using the local `edgar-filings` CLI.

## Environment

The CLI reads `SEC_EDGAR_EMAIL` and `SEC_EDGAR_COMPANY_NAME` from the shell environment or from a `.env` file at the repo root — it loads the file automatically. Do not pre-check or echo these variables. Do not invent values. Just run the CLI; if either variable is missing it will fail with a clear error message — surface that error to the user as-is.

## CLI reference — exact options only

Do not invent options. The CLI accepts only the following:

```text
--ticker TEXT            Required. Ticker symbol, e.g. AAPL
--filing TEXT            Form type to download. Repeatable. Default: 10-K
                         Accepted: 10-K, 10-Q, 20-F, 40-F, 6-K, 8-K
--range-start YYYY-MM-DD Lower bound on filing date. If set, downloads all
                         matching filings in range.
--range-end YYYY-MM-DD   Upper bound on filing date. Defaults to today.
--output-format TEXT     txt (default) | html | raw
--verify                 Audit on-disk filings against EDGAR metadata without
                         downloading. Reports present / missing / unrecognized.
```

There is no `--output-dir`. Output path is always `research/data/<TICKER>/filings/` — derived automatically.

## Output behaviour

- `txt` output converts every readable document in the SEC full submission
  (cover page plus furnished exhibits), separated by `=== TYPE (DESCRIPTION) ===`
  headers. For 6-K and 8-K filers the primary document is only a cover page —
  the results content lives in exhibits such as EX-99.1. Never rely on the
  cover page alone; check the file contains the exhibit before analysing.
- Machine-readable XBRL taxonomy documents (EX-100 to EX-109) are skipped.
- Filings sharing a fiscal quarter label (common for 6-K filers) get the
  filing date appended: `2027_Q2_6-K_2026-10-15.txt`. Same-day filings get an
  accession suffix. Unique quarterly labels keep the short name: `2027_Q1_6-K.txt`.
- `raw` output is the untouched SEC full submission. `html` output is the
  primary document only — prefer `txt` or `raw` for 6-K and 8-K research.
- Each output line reports the filing date and period:
  `6-K 2026-10-15 (period 2026-09-30) -> research/data/WSE/filings/2027_Q2_6-K_2026-10-15.txt`

## Corpus audit

After any multi-filing fetch, or before relying on an existing corpus, run:

```bash
.venv/bin/edgar-filings --ticker WSE --filing 6-K --verify
```

`UNRECOGNIZED` text files are candidates for deletion after confirming the
replacement files are present and named correctly.

## Invocation

```bash
.venv/bin/edgar-filings --ticker AAPL
.venv/bin/edgar-filings --ticker AAPL --filing 10-K --filing 10-Q
.venv/bin/edgar-filings --ticker AAPL --filing 10-K --range-start 2021-01-01 --range-end 2026-03-31
.venv/bin/edgar-filings --ticker AAPL --output-format html
.venv/bin/edgar-filings --ticker WSE --filing 6-K --verify
```

When the user does not specify a filing type, default to `10-K`.
When the user does not specify a date range, omit both flags — the CLI fetches the latest filing.
Always use `--output-format txt` unless the user explicitly requests otherwise.

## After a successful fetch

Report the files written under `research/data/<TICKER>/filings/`. Then prepend an entry to `research/results/<TICKER>/CHANGELOG.md` following the format and self-reporting rules in `CLAUDE.md`. Set Workflow to `edgar-filings`, list the files written under "Memos written", and set Primary source to "SEC EDGAR".
