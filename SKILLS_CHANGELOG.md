# Skills Changelog

All skill changes that modify `.md` command files are recorded here. Each entry must include an author benchmark and an independently-produced reviewer benchmark before the change is merged. See `_benchmarks/README.md` for the benchmark process.

Entries are newest-first.

---

<!--
## YYYY-MM-DD — <skill-name>

| Field | Value |
|---|---|
| PR | #N |
| Author | @handle |
| Skills changed | `skill-name.md` |
| Author benchmark | [`_benchmarks/_contributions/YYYY-MM-DD-<skill>/author.md`](_benchmarks/_contributions/YYYY-MM-DD-<skill>/author.md) |
| Reviewer benchmark | [`_benchmarks/_contributions/YYYY-MM-DD-<skill>/reviewer.md`](_benchmarks/_contributions/YYYY-MM-DD-<skill>/reviewer.md) |
| Reviewer sign-off | @handle — validated on [TICKER] — YYYY-MM-DD |

### What changed
One or two sentences describing the change.

### Why
What output failure or gap motivated the change. Reference the benchmark evidence.
-->

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
inferred fiscal-year-end month; event-form filenames (6-K, 8-K) are
deterministic — always date- and accession-suffixed, independent of fetch
scope; `txt` output converts every submission document including furnished
exhibits; new `--verify` flag audits the on-disk corpus against EDGAR
metadata without downloading. Skill doc updated to match. Tests: 28 pytest.

### Why
On WSE (18 six-Ks in a single range fetch), the pre-fix CLI overwrote the
entire fetch into one file, mislabelled the Q2 FY27 earnings 6-K as
`2026_Q4`, and dropped the results exhibit from `txt` output — the memo
workflow was reading a cover page with no numbers. 8-K filers suffer the
same collapse year-round (every 8-K labelled `{year}_Q4`). Discovered
2026-10-17 during the WSE Q2 FY27 earnings update; the fix was forced by
data loss, not preference.

---

## 2026-03-31 — Initial release

| Field | Value |
|---|---|
| PR | — |
| Author | @kalamajakapital |
| Skills added | all 11 skills migrated from private research repo |
| Author benchmark | [`_benchmarks/CLAUDE.md`](_benchmarks/CLAUDE.md), [`_benchmarks/CODEX.md`](_benchmarks/CODEX.md) |
| Reviewer benchmark | cross-model: each model reviewed the other's work |
| Reviewer sign-off | Claude reviewed Codex (ONTO pack); Codex reviewed Claude (WISE.L pack) — 2026-03-30 |

### What changed
Initial public release. Skills and analytical rules extracted from a private research repo and published as a standalone submodule-ready repository.

### Why
Benchmarks across two models (Claude Sonnet 4.6 and GPT-5 Codex) and two tickers (ONTO, WISE.L) established a quality baseline. The analytical standard in `CLAUDE.md` was iterated three times during Codex benchmarking before stabilising at the version included here. See `_benchmarks/CODEX.md` for the full iteration history.
