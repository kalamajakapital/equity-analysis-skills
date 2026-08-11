import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from edgar_filings import cli
from edgar_filings.cli import (
    FilingRecord,
    SubmissionDocument,
    download_selected_filings,
    parse_full_submission,
    render_submission_html,
    render_submission_text,
    select_submission_documents,
)


ACCESSION = "0000000-26-000001"

FIXTURE = """<SEC-DOCUMENT>demo.txt<SEC-HEADER>header</SEC-HEADER>
<DOCUMENT>
<TYPE>6-K
<SEQUENCE>1
<FILENAME>form6k.htm
<TEXT><html><body><h1>Cover</h1><p>Exhibit 99.1 is attached.</p></body></html>
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-99.1
<SEQUENCE>2
<FILENAME>ex99-1.htm
<TEXT><html><body><h1>Results</h1><p>Revenue 123</p></body></html>
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-99.2
<SEQUENCE>3
<FILENAME>ex99-2.htm
<TEXT><html><body><p>Supplement</p></body></html>
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>GRAPHIC
<SEQUENCE>4
<FILENAME>image.jpg
<TEXT>binary-placeholder</TEXT>
</DOCUMENT>
</SEC-DOCUMENT>"""

NO_EXHIBIT_FIXTURE = """<SEC-DOCUMENT>no-exhibit.txt
<DOCUMENT>
<TYPE>6-K
<SEQUENCE>1
<FILENAME>form6k.htm
<TEXT><html><body><h1>Cover only</h1></body></html></TEXT>
</DOCUMENT>
</SEC-DOCUMENT>"""

MISSING_EXHIBIT_FIXTURE = """<SEC-DOCUMENT>missing-exhibit.txt
<DOCUMENT>
<TYPE>6-K
<SEQUENCE>1
<FILENAME>form6k.htm
<TEXT><html><body><p>Exhibit 99.1 (ex99-1.htm) is attached.</p></body></html></TEXT>
</DOCUMENT>
</SEC-DOCUMENT>"""


class SubmissionBundleTests(unittest.TestCase):
    def test_parse_full_submission_preserves_document_metadata_and_order(self) -> None:
        documents = parse_full_submission(FIXTURE)

        # SEC sequence is both retained metadata and the source document order.
        self.assertEqual(
            [
                (document.doc_type, document.sequence, document.filename)
                for document in documents
            ],
            [
                ("6-K", 1, "form6k.htm"),
                ("EX-99.1", 2, "ex99-1.htm"),
                ("EX-99.2", 3, "ex99-2.htm"),
                ("GRAPHIC", 4, "image.jpg"),
            ],
        )
        self.assertIsInstance(documents[0], SubmissionDocument)
        self.assertIn("Cover", documents[0].contents)

    def test_select_submission_documents_keeps_primary_and_exhibits_in_order(self) -> None:
        selected = select_submission_documents(
            parse_full_submission(FIXTURE), "form6k.htm", ACCESSION
        )

        self.assertEqual(
            [
                (document.doc_type, document.sequence, document.filename)
                for document in selected
            ],
            [
                ("6-K", 1, "form6k.htm"),
                ("EX-99.1", 2, "ex99-1.htm"),
                ("EX-99.2", 3, "ex99-2.htm"),
            ],
        )

    def test_render_submission_text_includes_primary_and_all_exhibits_with_separators(self) -> None:
        rendered = render_submission_text(
            select_submission_documents(
                parse_full_submission(FIXTURE), "form6k.htm", ACCESSION
            )
        )

        self.assertIn("Cover", rendered)
        self.assertIn("Results", rendered)
        self.assertIn("Supplement", rendered)
        self.assertIn("===== EX-99.1 ex99-1.htm =====", rendered)
        self.assertIn("===== EX-99.2 ex99-2.htm =====", rendered)
        self.assertLess(
            rendered.index("===== EX-99.1 ex99-1.htm ====="),
            rendered.index("===== EX-99.2 ex99-2.htm ====="),
        )

    def test_render_submission_html_includes_all_document_headings(self) -> None:
        rendered = render_submission_html(
            select_submission_documents(
                parse_full_submission(FIXTURE), "form6k.htm", ACCESSION
            )
        )

        self.assertIn("<h1>6-K form6k.htm</h1>", rendered)
        self.assertIn("<h1>EX-99.1 ex99-1.htm</h1>", rendered)
        self.assertIn("<h1>EX-99.2 ex99-2.htm</h1>", rendered)
        self.assertIn("Cover", rendered)
        self.assertIn("Results", rendered)
        self.assertIn("Supplement", rendered)

    def test_no_exhibit_submission_renders_primary_once_without_exhibit_separator(self) -> None:
        rendered = render_submission_text(
            select_submission_documents(
                parse_full_submission(NO_EXHIBIT_FIXTURE), "form6k.htm", ACCESSION
            )
        )

        self.assertEqual(rendered.count("Cover only"), 1)
        self.assertNotIn("EX-99", rendered)

    def test_missing_advertised_exhibit_raises_a_clear_error(self) -> None:
        with self.assertRaisesRegex(
            ValueError, r"0000000-26-000001.*EX-99\.1.*ex99-1\.htm"
        ):
            select_submission_documents(
                parse_full_submission(MISSING_EXHIBIT_FIXTURE), "form6k.htm", ACCESSION
            )

    def test_downloader_renders_a_complete_dht_style_submission_bundle(self) -> None:
        class FakeDownloader:
            def __init__(self, company_name: str, email: str, download_root: str) -> None:
                self.download_root = Path(download_root)

            def get(self, form: str, ticker: str, **kwargs: object) -> None:
                source = (
                    self.download_root
                    / cli.ROOT_SAVE_FOLDER_NAME
                    / ticker
                    / form
                    / ACCESSION
                    / cli.FILING_FULL_SUBMISSION_FILENAME
                )
                source.parent.mkdir(parents=True)
                source.write_text(FIXTURE)

        row = FilingRecord(
            accession_number=ACCESSION,
            form="6-K",
            filing_date=date(2026, 8, 5),
            report_date=date(2026, 6, 30),
            primary_document="form6k.htm",
            fiscal_year_label=2026,
            fiscal_quarter=2,
        )
        with tempfile.TemporaryDirectory() as output_root:
            with (
                patch.object(cli, "Downloader", FakeDownloader),
                patch.object(cli, "filings_dir", return_value=Path(output_root)),
            ):
                written = download_selected_filings(
                    ticker="DHT",
                    forms=["6-K"],
                    targets=[row],
                    start=None,
                    end=date(2026, 8, 11),
                    company_name="test-company",
                    email="test@example.com",
                    output_format="txt",
                )
                written_raw = download_selected_filings(
                    ticker="DHT",
                    forms=["6-K"],
                    targets=[row],
                    start=None,
                    end=date(2026, 8, 11),
                    company_name="test-company",
                    email="test@example.com",
                    output_format="raw",
                )

            rendered = written[ACCESSION].read_text()
            raw_submission = written_raw[ACCESSION].read_bytes()

        self.assertIn("Cover", rendered)
        self.assertIn("Results", rendered)
        self.assertIn("Supplement", rendered)
        self.assertEqual(raw_submission, FIXTURE.encode())

    def test_downloader_reports_missing_exhibits_as_a_click_error_without_overwriting_output(self) -> None:
        class FakeDownloader:
            def __init__(self, company_name: str, email: str, download_root: str) -> None:
                self.download_root = Path(download_root)

            def get(self, form: str, ticker: str, **kwargs: object) -> None:
                source = (
                    self.download_root
                    / cli.ROOT_SAVE_FOLDER_NAME
                    / ticker
                    / form
                    / ACCESSION
                    / cli.FILING_FULL_SUBMISSION_FILENAME
                )
                source.parent.mkdir(parents=True)
                source.write_text(MISSING_EXHIBIT_FIXTURE)

        row = FilingRecord(
            accession_number=ACCESSION,
            form="6-K",
            filing_date=date(2026, 8, 5),
            report_date=date(2026, 6, 30),
            primary_document="form6k.htm",
            fiscal_year_label=2026,
            fiscal_quarter=2,
        )
        with tempfile.TemporaryDirectory() as output_root:
            output_path = Path(output_root) / "2026_Q2_6-K.txt"
            output_path.write_text("existing complete filing")
            with (
                patch.object(cli, "Downloader", FakeDownloader),
                patch.object(cli, "filings_dir", return_value=Path(output_root)),
                patch.object(cli, "resolve_user_agent", return_value=("test-company", "test@example.com")),
                patch.object(cli, "fetch_submission_rows", return_value=[row]),
                patch.object(cli, "select_target_rows", return_value=[row]),
            ):
                result = CliRunner().invoke(
                    cli.main,
                    ["--ticker", "DHT", "--filing", "6-K", "--range-end", "2026-08-11"],
                )

            self.assertEqual(result.exit_code, 1)
            self.assertIn(ACCESSION, result.output)
            self.assertIn("EX-99.1", result.output)
            self.assertEqual(output_path.read_text(), "existing complete filing")


if __name__ == "__main__":
    unittest.main()
