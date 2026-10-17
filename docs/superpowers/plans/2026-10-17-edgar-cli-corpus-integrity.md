# EDGAR CLI Corpus Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `edgar-filings` CLI so periodic filers of any form type (6-K, 8-K, 10-Q) get complete, correctly-named, non-overwriting downloads with exhibit content included, add a corpus `--verify` audit mode, and ship the change through this repo's contribution process.

**Architecture:** Four coordinated changes: three fixes in `scripts/edgar/edgar_filings/cli.py` — (1) fiscal quarter/year labels derived from each filing's `reportDate` plus the fiscal-year-end month inferred from annual-filing metadata, replacing a sequential counter that mislabels 6-K quarters and collapses 8-K filings into one filename; (2) collision-free output filenames when multiple filings share a fiscal quarter; (3) `txt` output converted from the full submission text file (all documents incl. exhibits) instead of the primary document only, which for 6-K and 8-K filers is just a cover page — plus a new `--verify` flag that compares the on-disk corpus against EDGAR metadata without downloading, surfacing silently lost or mislabelled files. A working prototype of all code changes exists, uncommitted, in the financial-models submodule checkout with 22 passing pytest tests — Task 1 ports it, including the `dev` extra in `scripts/edgar/pyproject.toml`.

**Tech Stack:** Python 3.11+, click, sec-edgar-downloader (vendored fork pin), pytest 9 (`dev` extra; no other new deps).

**Background — the bugs, observed on WSE (Wise Group plc) on 2026-10-17:**
- A range fetch of 18 six-K filings (2026-07-21..2026-10-15) wrote every one to the same filename (`2026_Q4_6-K.txt`); only the last survived. Root cause: the sequential quarter counter in `assign_fiscal_labels()` advanced on *every* 6-K (Wise furnishes ~9 per fiscal quarter), so by the earnings filing the counter was exhausted and every filing received the same fallback `Q4` label and the filing year.
- `txt` output converted only `primary-document`, so the Q2 FY27 earnings exhibit (Exhibit 99.1 — the actual results) was silently dropped from the readable output. Raw format was the only workaround.
- 8-K filers are hit harder still: `8-K` is in neither `QUARTERLY_FORMS` nor `ANNUAL_FORMS`, so the old code labelled every 8-K in a calendar year `{year}_Q4_8-K`.
- 10-Q range fetches starting mid-fiscal-year shifted every quarter label, because the sequential counter assumed the set began at fiscal-year start.
- The fiscal-year label for March-FYE annuals was computed as `report_date.year - 1` when `month <= 3`, mislabelling FY2026 (year ended 2026-03-31) as FY2025.
- There was no way to detect any of this after the fact — no audit of what EDGAR knows about vs what is on disk.

---

### Task 1: Port the CLI fixes and tests into this repo

**Files:**
- Modify: `scripts/edgar/edgar_filings/cli.py`
- Create: `scripts/edgar/tests/test_cli.py`
- Modify: `scripts/edgar/pyproject.toml`
- Modify: `Makefile`

The prototype lives in the parent research repo's submodule checkout:
`/opt/github/kalamajakapital/financial-models/.claude/commands/` (uncommitted working tree on `dev-20261017` at commit `442dcbe` + uncommitted changes).

- [ ] **Step 1: Create the feature branch**

The repo's `main` branch exists but `dev-20261017` (local-only) carries an unpushed README cleanup commit (`4383559`). Cut the feature branch from `dev-20261017`; Task 4 flags the PR-base consequence.

```bash
cd /opt/github/kalamajakapital/equity-analysis-skills
git checkout dev-20261017
git checkout -b fix/edgar-cli-corpus-integrity
```

- [ ] **Step 2: Port the changed and new files from the prototype**

```bash
PROTO=/opt/github/kalamajakapital/financial-models/.claude/commands
cp $PROTO/scripts/edgar/edgar_filings/cli.py scripts/edgar/edgar_filings/cli.py
mkdir -p scripts/edgar/tests
cp $PROTO/scripts/edgar/tests/test_cli.py scripts/edgar/tests/test_cli.py
git diff --stat
```

Expected: `cli.py` modified; `tests/test_cli.py` new. The prototype `cli.py` contains, versus the old version:
- `infer_fy_end_month(rows)` — FY-end month from the first annual filing's period date
- `fiscal_label_from_report_date(report_date, fy_end_month)` — returns `(fiscal_year, quarter)` where `quarter = 4 if (month - fy_end) % 12 == 0 else ((month - fy_end) % 12 - 1) // 3 + 1` and `fiscal_year = report_date.year + (1 if report_date.month > fy_end_month else 0)`
- `assign_fiscal_labels()` rewritten: periodic filings take labels from `report_date` when available; the old sequential counter survives only as a fallback for filings without a period date
- `parse_submission_documents()`, `submission_to_text()`, `SKIP_DOCUMENT_TYPES` — full-submission conversion
- `output_names_for_targets(targets)` — base name `{fy}_Q{q}_{form}`; on collision within a fetch, appends the filing date (`_YYYY-MM-DD`), and same-day collisions additionally get the last 6 characters of the dash-stripped accession number
- `verify_corpus()` — metadata-only audit (present / missing / unrecognized text artifacts)
- `download_selected_filings()` rewritten: `txt` reads the full submission and converts every non-XBRL document with `=== TYPE (DESCRIPTION) ===` separators; `download_details` only for `html`
- `main()` gains the `--verify` flag; echo lines include `(period YYYY-MM-DD)`

The prototype `tests/test_cli.py` contains 22 pytest tests: March-FYE and December-FYE quarter math (parametrized), 6-K non-burn, no-period fallback, collision naming, 8-K labelling + same-quarter collision, 8-K exhibit inclusion, 10-Q mid-year range, submission parsing, exhibit inclusion, XBRL skip, no-`<DOCUMENT>`-markers fallback. The tests deliberately cover the three non-6-K damage classes: 8-K label collapse, 8-K exhibit loss, and mid-year 10-Q range fetches.

- [ ] **Step 3: Add the pytest `dev` extra**

In `scripts/edgar/pyproject.toml`, after the `[project.scripts]` section:

```toml
[project.optional-dependencies]
dev = ["pytest>=9.0"]
```

- [ ] **Step 4: Add a `make test` target**

In `Makefile`, extend `.PHONY`:

```make
.PHONY: help install install-claude install-codex hooks develop test
```

Add the target (mirrors `develop`'s venv bootstrap so it works from a fresh clone):

```make
test:
	@uv venv .venv --allow-existing
	@uv pip install --python .venv/bin/python --cache-dir .uv-cache -e 'scripts/edgar[dev]'
	@.venv/bin/python -m pytest scripts/edgar/tests/ -v
```

- [ ] **Step 5: Run the tests**

```bash
cd /opt/github/kalamajakapital/equity-analysis-skills && make test
```

Expected: `22 passed`.

- [ ] **Step 6: Smoke-test the real CLI against EDGAR**

```bash
.venv/bin/edgar-filings --ticker WSE --filing 6-K --verify --range-start 2026-07-01
```

Expected: metadata report printed, no downloads. Exit code 0 even when files are missing — this is deliberate: the report is the deliverable, and the missing/UNRECOGNIZED sections enumerate what the old bug destroyed.

- [ ] **Step 7: Commit**

```bash
git add scripts/edgar/edgar_filings/cli.py scripts/edgar/tests/test_cli.py scripts/edgar/pyproject.toml Makefile
git commit -m "edgar-filings: fix fiscal labels, filename collisions, exhibit loss; add --verify"
```

---

### Task 2: Sync the `edgar-filings` skill doc with the new behavior

**Files:**
- Modify: `edgar-filings.md`

Three edits, in file order. (Fence nesting: the inner blocks below are shown with four-backtick outer fences so they render correctly.)

- [ ] **Step 1: Update the CLI reference block**

Replace the existing `## CLI reference — exact options only` section with:

````markdown
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
- Machine-readable XBRL taxonomy documents (EX-100 to EX-107) are skipped.
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
````

- [ ] **Step 2: Update the Invocation examples**

Replace the existing `## Invocation` section with:

````markdown
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
````

- [ ] **Step 3: Commit**

```bash
git add edgar-filings.md
git commit -m "edgar-filings: document multi-document txt output, collision naming, --verify audit"
```

---

### Task 3: Author benchmark + SKILLS_CHANGELOG entry

**Files:**
- Create: `_benchmarks/_contributions/2026-10-17-edgar-filings/author.md`
- Modify: `SKILLS_CHANGELOG.md`

The repo rule (`SKILLS_CHANGELOG.md` header): skill-file changes require an author benchmark and an independent reviewer benchmark before merge. The benchmark run doubles as the start of the real WSE Q2 FY27 earnings update.

**Ordering constraint:** the benchmark must run the *fixed* CLI inside the financial-models research repo, but the fix is not merged yet. Resolve it by pointing the financial-models submodule at the local fix branch for the duration of the benchmark (a local pointer change, no merge required). Task 4 Step 3 then finalises the pointer after the merge decision.

- [ ] **Step 1: Point the financial-models submodule at the fix branch**

```bash
cd /opt/github/kalamajakapital/financial-models
git submodule set-branch --branch fix/edgar-cli-corpus-integrity .claude/commands
git submodule update --remote .claude/commands
.venv/bin/edgar-filings --version 2>/dev/null || .venv/bin/pip install -e .claude/commands/scripts/edgar
```

(Re-install if the editable install does not pick up the updated checkout automatically.)

- [ ] **Step 2: Run the benchmark workflow**

In the financial-models repo:

1. Delete the damaged artifacts `research/data/WSE/filings/2026_Q4_6-K.txt` and `2026_Q4_6-K.raw.txt` (both flagged UNRECOGNIZED by `--verify`; created by the pre-fix CLI in the session of 2026-10-17).
2. Refetch: `.venv/bin/edgar-filings --ticker WSE --filing 6-K --range-start 2026-07-17 --range-end 2026-10-17 --output-format txt`.
3. Confirm `2027_Q2_6-K_2026-10-15.txt` contains `=== EX-99.1 ===` with the KPI tables.
4. Run the `earnings-update` workflow for Q2 FY27 (memo prepended to `research/results/WSE/memos/earnings-updates.md`, changelog entry prepended).
5. Run `--verify` for WSE to show the repaired corpus.

Capture: files written, the earnings memo path, one before/after comparison (pre-fix `2026_Q4_6-K.txt` cover-only file vs new multi-document file), and the verify output.

- [ ] **Step 3: Write the author benchmark**

Copy `_benchmarks/template.md` to `_benchmarks/_contributions/2026-10-17-edgar-filings/author.md` and complete it from the captured evidence. Known fields:

```markdown
# Benchmark — opencode GLM on WSE

## Overview

| Field | Value |
|---|---|
| Role | author |
| Subject model | GLM (`opencode/glm-5.3-flash`), operating as opencode |
| Harness | opencode |
| Skill(s) evaluated | `edgar-filings.md` (+ `scripts/edgar` CLI it drives) |
| Skill version | branch `fix/edgar-cli-corpus-integrity` |
| Filing(s) used | Wise Group plc Q2 FY27 6-K (filed 2026-10-15, period 2026-09-30); 6-K range 2026-07-17..2026-10-17 |
| Ticker | WSE |
| Run date | 2026-10-17 |
| Prior version grade | n/a — first benchmark of this skill |

## What was run

Range fetch of all 6-K filings after the Q1 FY27 update, on the pre-fix CLI
(all 18 filings overwritten into `2026_Q4_6-K.txt`, exhibit dropped from txt
output) and again on the fixed CLI. `--verify` used to enumerate the damage
and confirm the repair. Downstream: `earnings-update` workflow completed from
the repaired files only.

## Grades

| Memo | Grade | Primary Strength | Primary Weakness |
|---|---|---|---|
| earnings-update (Q2 FY27) | <grade from the run> | <strength> | <weakness> |
| **Overall** | **<grade>** | | |
```

Complete the qualitative assessment, the four anti-summary questions, and the verdict from the actual run — these depend on the memo produced in Step 2 and cannot be pre-written.

- [ ] **Step 4: Prepend the SKILLS_CHANGELOG entry**

```markdown
## 2026-10-17 — edgar-filings

| Field | Value |
|---|---|
| PR | <PR number — filled by maintainer at push/PR time> |
| Author | @kalamajakapital |
| Skills changed | `edgar-filings.md` |
| Author benchmark | [`_benchmarks/_contributions/2026-10-17-edgar-filings/author.md`](_benchmarks/_contributions/2026-10-17-edgar-filings/author.md) |
| Reviewer benchmark | pending |
| Reviewer sign-off | pending |

### What changed
CLI fix: fiscal labels now derive from each filing's period date and the
inferred fiscal-year-end month; colliding filenames get date/accession
suffixes instead of overwriting; `txt` output converts every submission
document including furnished exhibits; new `--verify` flag audits the on-disk
corpus against EDGAR metadata without downloading. Skill doc updated to match.

### Why
On WSE (18 six-Ks in a quarter-and-a-half range fetch), the pre-fix CLI
overwrote the entire fetch into one file, mislabelled the Q2 FY27 earnings 6-K
as `2026_Q4`, and dropped the results exhibit from `txt` output — the memo
workflow was reading a cover page with no numbers. 8-K filers suffer the same
collapse year-round (every 8-K labelled `{year}_Q4`). Discovered 2026-10-17
during the WSE Q2 FY27 earnings update; the fix was forced by data loss, not
preference.
```

- [ ] **Step 5: Commit**

```bash
git add _benchmarks/_contributions/2026-10-17-edgar-filings/author.md SKILLS_CHANGELOG.md
git commit -m "edgar-filings: author benchmark and changelog for corpus-integrity fix"
```

---

### Task 4: Hand off for push and PR; finalise the downstream pointer

**Files:** none (git operations)

**Constraint:** the implementer is NOT authorised to push or open PRs. Work stops at committed local branches; push, PR, and merge are done by the maintainer.

- [ ] **Step 1: Verify the branch is committed and clean, then hand off**

```bash
cd /opt/github/kalamajakapital/equity-analysis-skills
git status --short
git log --oneline main..fix/edgar-cli-corpus-integrity
```

Expected: clean working tree; three commits (CLI fix + tests, doc sync, benchmark + changelog). Report the branch name, commit list, and the PR-base decision (T4 Step 2 options) to the maintainer. Do not push, do not run `gh pr create`.

- [ ] **Step 2: PR-base decision — for the maintainer**

The feature branch was cut from `dev-20261017`, so a PR against `main` also carries the unpushed README cleanup commit `4383559` ("Remove noise..."). Two options:
- **Option A:** first merge `dev-20261017` → `main` (README cleanup alone), then PR the feature branch → `main`. Clean history, two PRs.
- **Option B:** one PR feature branch → `main` including the README commit, noted in the description.

- [ ] **Step 3: Finalise the financial-models submodule pointer (maintainer-driven)**

After the maintainer's merge decision, in the financial-models repo: point `.claude/commands` at the chosen commit (`git submodule update --remote .claude/commands` once merged to `main`, or keep it on the fix branch while the PR is in review — the benchmark in Task 3 already requires the branch pointer locally).

- [ ] **Step 4: Corpus repair is a separate plan**

Out of scope here — different repo, different failure modes. It covers: refetching the WSE 6-K range (Task 3 Step 2 does WSE as a by-product of the benchmark), then running `--verify` for **every ticker in `research/data/`** — not only 6-K filers: 8-K filers suffered the same overwrite collapse, and 10-Q mid-year range fetches may carry shifted quarter labels — and refetching what it flags. Scope that plan once this PR is in review.

---

## Self-review

- **Spec coverage:** period-date labels for all form types (T1), collision-safe naming for all form types (T1), exhibit-inclusive txt for 6-K and 8-K (T1), cross-form regression tests (T1 Step 2), `--verify` audit (T1, exercised across all tickers in T4 Step 4), doc sync (T2), benchmark + changelog per repo contribution rules (T3), PR + submodule pointer (T4), corpus repair explicitly deferred as a separate plan (T4 Step 4). No gaps.
- **Placeholders:** benchmark grades and the PR number are inherently produced by T3 Step 2 and T4 Step 2 respectively — marked as such, not pre-written. Everything else is concrete: every step has exact commands or exact file content.
- **Type consistency:** `fiscal_label_from_report_date(date, int) -> tuple[int, int]`, `output_names_for_targets(list[FilingRecord]) -> dict[str, str]`, `verify_corpus(..., user_agent: str) -> None` — defined in T1 Step 2 and used unchanged in T3/T4 examples.
- **Ordering:** T3 Step 1 (submodule → fix branch) precedes the benchmark run; T4 Step 3 finalises the pointer after the maintainer's merge decision. No circular dependencies.
- **Authorization:** no step pushes or opens PRs — T4 hands off to the maintainer with a clean committed branch and the PR-base decision options.
- **Rendering:** nested code fences in T2 use four-backtick outer fences.
