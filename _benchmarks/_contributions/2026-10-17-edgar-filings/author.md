# Benchmark — opencode GLM on WSE

## Overview

| Field | Value |
|---|---|
| Role | author |
| Subject model | GLM (`opencode/glm-5.3-flash`), operating as opencode |
| Harness | opencode |
| Skill(s) evaluated | `edgar-filings.md` (+ `scripts/edgar` CLI it drives) |
| Skill version | branch `fix/edgar-cli-corpus-integrity` at `4252ccd` |
| Filing(s) used | Wise Group plc Q2 FY27 6-K (filed 2026-10-15, period/event 2026-10-15, quarter ended 2026-09-30); 6-K range 2026-05-11..2026-10-17; FY2026 20-F (filed 2026-06-25) |
| Ticker | WSE |
| Run date | 2026-10-17 |
| Prior version grade | n/a — first benchmark of this skill |

---

## What was run

Discovery run, then damage enumeration, then repair, then downstream consumption:

1. **Pre-fix fetch (old CLI, commit `442dcbe`):** range fetch of 18 six-K filings (2026-07-21..2026-10-15). Every filing was written to the same output filename (`2026_Q4_6-K.txt`) — each download overwrote the previous, so 17 of 18 filings were silently destroyed. The surviving file converted only the primary document: a 57-line cover page with zero financial content. The Q2 FY27 results exhibit (EX-99.1) never reached the readable output; the memo workflow was left reading a cover page with no numbers.
2. **`--verify` audit (fixed CLI):** compared EDGAR metadata against the on-disk corpus: correctly reported 0 present / 23 missing / 5 unrecognized on the damaged corpus, enumerated every missing filing with its period date, and flagged the stray pre-fix artifacts. Zero downloads during audit.
3. **Repaired fetch:** full 6-K history + 20-F under the fixed CLI — 24 files, all uniquely and deterministically named (`{fy}_Q{q}_{form}_{date}_{accession6}.txt` for event forms), every file containing cover page AND exhibits separated by `=== TYPE (DESCRIPTION) ===` headers. Re-verified: 24 present / 0 missing / 0 unrecognized.
4. **Idempotency check:** refetching the same range reproduced identical filenames (the naming is a pure function of filing metadata — a scope-independence regression test pins this in `tests/test_cli.py::test_event_form_name_independent_of_fetch_scope`, verified to fail against the old implementation).
5. **Downstream consumption:** the `earnings-update` workflow was completed from the repaired files only — Q2 FY27 memo prepended to `research/results/WSE/memos/earnings-updates.md` in the consuming research repo, with guidance-raise documentation, derived net-interest-yield compression (~1.68% → ~1.63% QoQ), and the interest-expense divergence flagged from Exhibit 99.1 tables that the pre-fix CLI would have dropped.

---

## Grades

| Memo | Grade | Primary Strength | Primary Weakness |
|---|---|---|---|
| earnings-update (Q2 FY27) | A− | Every figure traceable to Exhibit 99.1 tables the old tooling would have silently dropped; derived metrics (NII yield, volume/customer, revenue mix share) computed, not quoted | IBT margin section rests on guidance prose; no P&L detail exists in the filing to test it — a filing-format limit, not a tooling one |
| **Overall** | **A−** | Tooling defect produced zero contamination in the final memo once repaired; provenance chain (EDGAR → full submission → exhibit → memo) intact and auditable | Pre-fix run destroyed 17 filings silently — the damage was only discoverable because `--verify` was built; without it, the corpus would look healthy while missing 70% of known filings |

---

## Qualitative assessment

### What the skill produced well

The fixed CLI turned a silent data-loss failure mode into an auditable, idempotent corpus. `--verify` enumerated the exact damage (23 missing filings with period dates, 5 stray artifacts) without downloading anything, and the repaired fetch produced complete multi-document txt files — the Q2 FY27 exhibit tables (9-quarter KPI history, revenue decomposition, take-rate detail by segment) all present and machine-readable. The downstream memo was written entirely from filing-sourced content; nothing needed reconstruction from outside EDGAR.

### Where the skill fell short

The pre-fix CLI's failure was silent by design: overwrites and exhibit drops produced exit code 0 and plausible-looking output. That is the failure class this change fixes, but it also shows the limit — the fix's value depends on `--verify` actually being run. The skill doc now instructs running it after multi-filing fetches, but nothing enforces it. Also: 6-K event-date semantics mean the Q2 FY27 earnings 6-K is named `2027_Q3_*` (furnished in fiscal Q3) — defensible and documented, but initially confusing; analysts must read period dates, not filenames, to locate a quarter's results.

### Comparison to prior version

Prior version (no benchmark — first one): no audit capability, scope-dependent filenames, cover-page-only txt for 6-K/8-K filers. The improvement is binary on all three. What did not change: PDF artifacts from manual imports remain invisible to `--verify` (out of scope by design); annual-form fiscal labels for January–March FYE companies now derive from period dates rather than a hardcoded March assumption — correct for Wise, worth re-checking on a January-FYE filer if one enters the corpus.

---

## Anti-summary check

1. **What did the skill compute that was not explicitly in the filing?** The expected-corpus set itself: which filings EDGAR knows about vs which survived on disk — a reconciliation that exists in no single source. Downstream, the memo derived NII yield, volume-per-customer, and revenue-mix shares from raw exhibit tables.
2. **What did the skill falsify or pressure-test rather than repeat?** The assumption that an existing corpus is complete. `--verify` falsified it: 23 of 24 known 6-Ks were missing or damaged while the directory looked populated.
3. **What would an investor be unable to decide without this output?** Whether any earnings-update memo written from this corpus is missing the quarter's actual numbers. The Q2 FY27 memo's guidance-raise analysis was only possible because the exhibit survived the fetch.
4. **What is the single most damaging number in the filing — and did the skill use it?** Interest expense on customer liabilities growing 15% QoQ against 6% for interest income — it attacks the guidance's static passthrough assumption and the highest-margin revenue stream. The memo uses it as the lead risk.

---

## Verdict

This skill version meets the standard: the tooling failure that would have produced a memo citing a cover page is fixed, the damage is enumerable, and the repaired pipeline is deterministic and re-runnable. Merge recommended. The reviewer should independently run `--verify` on their own corpus before sign-off — the feature's value is exactly reproducible.
