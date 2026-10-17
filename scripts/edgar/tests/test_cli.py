from __future__ import annotations

from datetime import date

import pytest

from edgar_filings.cli import (
    FilingRecord,
    assign_fiscal_labels,
    classify_corpus,
    fiscal_label_from_report_date,
    output_names_for_targets,
    parse_submission_documents,
    submission_to_text,
)


def row(
    accession: str,
    form: str,
    filed: str,
    period: str | None,
) -> FilingRecord:
    return FilingRecord(
        accession_number=accession,
        form=form,
        filing_date=date.fromisoformat(filed),
        report_date=date.fromisoformat(period) if period else None,
        primary_document="doc.htm",
    )


def labeled(*targets: FilingRecord) -> dict[str, str]:
    return output_names_for_targets(
        assign_fiscal_labels(sorted(targets, key=lambda r: r.filing_date))
    )


@pytest.mark.parametrize(
    ("period", "fiscal_year", "quarter"),
    [
        ("2026-06-30", 2027, 1),
        ("2026-09-30", 2027, 2),
        ("2026-12-31", 2027, 3),
        ("2027-03-31", 2027, 4),
        ("2026-03-31", 2026, 4),
    ],
)
def test_march_fye_quarters(period, fiscal_year, quarter):
    # Wise: fiscal year ends March 31, labelled by ending year.
    assert fiscal_label_from_report_date(date.fromisoformat(period), 3) == (
        fiscal_year,
        quarter,
    )


@pytest.mark.parametrize(
    ("period", "fiscal_year", "quarter"),
    [
        ("2026-03-31", 2026, 1),
        ("2026-06-30", 2026, 2),
        ("2026-09-30", 2026, 3),
        ("2026-12-31", 2026, 4),
    ],
)
def test_december_fye_quarters(period, fiscal_year, quarter):
    assert fiscal_label_from_report_date(date.fromisoformat(period), 12) == (
        fiscal_year,
        quarter,
    )


def test_6k_filings_do_not_burn_quarters():
    rows = [
        row("a1", "20-F", "2026-05-20", "2026-03-31"),
        row("a2", "6-K", "2026-07-16", "2026-06-30"),
        row("a3", "6-K", "2026-08-05", "2026-07-31"),
        row("a4", "6-K", "2026-10-15", "2026-09-30"),
        row("a5", "6-K", "2026-10-15", "2026-09-30"),
    ]
    by_accession = {r.accession_number: r for r in assign_fiscal_labels(rows)}
    assert by_accession["a1"].fiscal_year_label == 2026
    assert by_accession["a1"].fiscal_quarter == 4
    assert (by_accession["a2"].fiscal_year_label, by_accession["a2"].fiscal_quarter) == (2027, 1)
    assert (by_accession["a3"].fiscal_year_label, by_accession["a3"].fiscal_quarter) == (2027, 2)
    assert (by_accession["a4"].fiscal_year_label, by_accession["a4"].fiscal_quarter) == (2027, 2)
    assert (by_accession["a5"].fiscal_year_label, by_accession["a5"].fiscal_quarter) == (2027, 2)


def test_december_fye_10q():
    rows = [
        row("b1", "10-K", "2026-02-10", "2025-12-31"),
        row("b2", "10-Q", "2026-04-25", "2026-03-31"),
        row("b3", "10-Q", "2026-10-20", "2026-09-30"),
    ]
    by_accession = {r.accession_number: r for r in assign_fiscal_labels(rows)}
    assert by_accession["b1"].fiscal_year_label == 2025
    assert (by_accession["b2"].fiscal_year_label, by_accession["b2"].fiscal_quarter) == (2026, 1)
    assert (by_accession["b3"].fiscal_year_label, by_accession["b3"].fiscal_quarter) == (2026, 3)


def test_fallback_without_period_dates():
    rows = [
        row("c1", "20-F", "2026-05-20", None),
        row("c2", "6-K", "2026-07-16", None),
        row("c3", "6-K", "2026-08-05", None),
    ]
    by_accession = {r.accession_number: r for r in assign_fiscal_labels(rows)}
    assert by_accession["c1"].fiscal_year_label == 2026
    assert (by_accession["c2"].fiscal_year_label, by_accession["c2"].fiscal_quarter) == (2027, 1)
    assert (by_accession["c3"].fiscal_year_label, by_accession["c3"].fiscal_quarter) == (2027, 2)


def test_unique_label_keeps_base_name():
    names = labeled(row("d1", "10-K", "2026-02-10", "2025-12-31"))
    assert names["d1"] == "2025_Q4_10-K"


def test_colliding_quarter_names_get_filing_dates():
    names = labeled(
        row("0000000000-26-000001", "20-F", "2026-05-20", "2026-03-31"),
        row("0000950142-26-001564", "6-K", "2026-10-15", "2026-09-30"),
        row("0001193125-26-282767", "6-K", "2026-10-15", "2026-09-30"),
        row("0001193125-26-200001", "6-K", "2026-08-05", "2026-07-31"),
    )
    assert names["0001193125-26-200001"] == "2027_Q2_6-K_2026-08-05"
    assert names["0000950142-26-001564"] == "2027_Q2_6-K_2026-10-15"
    assert names["0001193125-26-282767"] == "2027_Q2_6-K_2026-10-15_282767"


def test_distinct_quarters_do_not_collide():
    names = labeled(
        row("f0", "20-F", "2026-05-20", "2026-03-31"),
        row("f1", "6-K", "2026-07-16", "2026-06-30"),
        row("f2", "6-K", "2026-10-15", "2026-09-30"),
    )
    assert names["f1"] == "2027_Q1_6-K"
    assert names["f2"] == "2027_Q2_6-K"


def test_8k_filings_get_labels_and_no_collision():
    # 8-Ks are not in QUARTERLY_FORMS or ANNUAL_FORMS: the old code
    # labelled them all {calendar_year}_Q4, collapsing every filing in a
    # calendar year into one filename.
    names = labeled(
        row("g0", "10-K", "2026-02-10", "2025-12-31"),
        row("g1", "8-K", "2026-03-15", "2026-03-12"),
        row("g2", "8-K", "2026-05-02", "2026-04-30"),
        row("g2b", "8-K", "2026-05-20", "2026-05-15"),
        row("g3", "8-K", "2026-11-09", "2026-11-06"),
    )
    assert names["g1"] == "2026_Q1_8-K"
    assert names["g2"] == "2026_Q2_8-K_2026-05-02"
    assert names["g2b"] == "2026_Q2_8-K_2026-05-20"
    assert names["g3"] == "2026_Q4_8-K"


def test_8k_exhibit_included_in_txt():
    raw = SAMPLE_SUBMISSION.replace("<TYPE>6-K", "<TYPE>8-K")
    text = submission_to_text(raw)
    assert "=== EX-99.1 (PRESS RELEASE) ===" in text
    assert "Net revenue increased 21% YoY" in text


def test_10q_range_starting_mid_year():
    # Mirrors production: the metadata set always includes annual forms,
    # so FY-end month is inferable even when the fetch range starts
    # mid-year and contains no annual filing.
    rows = [
        row("h0", "10-K", "2026-02-10", "2025-12-31"),
        row("h1", "10-Q", "2026-10-20", "2026-09-30"),
    ]
    by_accession = {r.accession_number: r for r in assign_fiscal_labels(rows)}
    assert (by_accession["h1"].fiscal_year_label, by_accession["h1"].fiscal_quarter) == (2026, 3)


SAMPLE_SUBMISSION = """<SEC-DOCUMENT>0001193125-26-282767.txt : 20260625
<SEC-HEADER>
HEADER DATA
</SEC-HEADER>
<DOCUMENT>
<TYPE>6-K
<DESCRIPTION>FORM 6-K
<TEXT>
<html><body><p>Cover page for the quarter ended September 30, 2026.</p></body></html>
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-99.1
<DESCRIPTION>PRESS RELEASE
<TEXT>
<html><body>
<p>Net revenue increased 21% YoY to $739.1 million.</p>
<table><tr><td>Net revenue</td><td>739.1</td></tr></table>
</body></html>
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-101
<DESCRIPTION>XBRL TAXONOMY
<TEXT>
<taxxn>machine-readable-noise</taxxn>
</TEXT>
</DOCUMENT>
"""


def test_parse_submission_documents():
    docs = parse_submission_documents(SAMPLE_SUBMISSION)
    assert [d.doc_type for d in docs] == ["6-K", "EX-99.1", "EX-101"]
    assert docs[1].description == "PRESS RELEASE"


def test_submission_to_text_includes_exhibit():
    text = submission_to_text(SAMPLE_SUBMISSION)
    assert "=== 6-K (FORM 6-K) ===" in text
    assert "Cover page for the quarter ended" in text
    assert "=== EX-99.1 (PRESS RELEASE) ===" in text
    assert "Net revenue increased 21% YoY" in text
    # Cover and exhibit must both survive in one readable file.
    assert "739.1" in text


def test_submission_to_text_skips_xbrl_taxonomy():
    text = submission_to_text(SAMPLE_SUBMISSION)
    assert "machine-readable-noise" not in text


def test_submission_to_text_without_document_markers():
    raw = "<SEC-HEADER>junk</SEC-HEADER><html><body><p>Plain filing.</p></body></html>"
    text = submission_to_text(raw)
    assert "Plain filing." in text
    assert "junk" not in text


def test_parse_submission_documents_warns_on_missing_text_block(capsys):
    raw = (
        "<DOCUMENT>\n<TYPE>6-K\n<TEXT>\n<p>Hello.</p>\n</TEXT>\n</DOCUMENT>\n"
        "<DOCUMENT>\n<TYPE>EX-99\n<DESCRIPTION>BROKEN\n</DOCUMENT>\n"
    )
    docs = parse_submission_documents(raw)
    assert [d.doc_type for d in docs] == ["6-K"]
    captured = capsys.readouterr()
    assert "warning: document EX-99 has no <TEXT> block; skipped" in captured.err


def touch(directory, name):
    path = directory / name
    path.write_text("placeholder")
    return path


def test_classify_corpus_present_target(tmp_path):
    target = row("t1", "10-K", "2026-02-10", "2025-12-31")
    targets = assign_fiscal_labels([target])
    name = output_names_for_targets(targets)[target.accession_number]
    touch(tmp_path, f"{name}.txt")
    present, missing, orphans = classify_corpus(tmp_path, targets, targets)
    assert [r.accession_number for r, _ in present] == ["t1"]
    assert missing == []
    assert orphans == []


def test_classify_corpus_out_of_range_file_not_orphan(tmp_path):
    older = row("o1", "6-K", "2024-08-05", "2024-07-31")
    target = row("t1", "6-K", "2026-08-05", "2026-07-31")
    all_rows = assign_fiscal_labels([older, target])
    targets = [r for r in all_rows if r.filing_date.year == 2026]
    older_name = output_names_for_targets(all_rows)[older.accession_number]
    touch(tmp_path, f"{older_name}.txt")
    present, missing, orphans = classify_corpus(tmp_path, all_rows, targets)
    assert present == []
    assert [r.accession_number for r in missing] == ["t1"]
    assert orphans == []


def test_classify_corpus_unmatched_file_is_orphan(tmp_path):
    target = row("t1", "10-K", "2026-02-10", "2025-12-31")
    targets = assign_fiscal_labels([target])
    touch(tmp_path, "1999_Q4_10-K_old.txt")
    present, missing, orphans = classify_corpus(tmp_path, targets, targets)
    assert present == []
    assert [r.accession_number for r in missing] == ["t1"]
    assert [p.name for p in orphans] == ["1999_Q4_10-K_old.txt"]


def test_classify_corpus_ignores_non_text_files(tmp_path):
    target = row("t1", "10-K", "2026-02-10", "2025-12-31")
    targets = assign_fiscal_labels([target])
    touch(tmp_path, "totally_unrelated.pdf")
    present, missing, orphans = classify_corpus(tmp_path, targets, targets)
    assert present == []
    assert [r.accession_number for r in missing] == ["t1"]
    assert orphans == []
