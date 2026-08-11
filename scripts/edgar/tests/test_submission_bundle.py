import unittest

from edgar_filings.cli import (
    SubmissionDocument,
    parse_full_submission,
    render_submission_html,
    render_submission_text,
    select_submission_documents,
)


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
<TEXT><html><body><p>Exhibit 99.1 is attached.</p></body></html></TEXT>
</DOCUMENT>
</SEC-DOCUMENT>"""


class SubmissionBundleTests(unittest.TestCase):
    def test_parse_full_submission_preserves_document_metadata_and_order(self) -> None:
        documents = parse_full_submission(FIXTURE)

        self.assertEqual(
            [
                (document.doc_type, document.filename)
                for document in documents
            ],
            [
                ("6-K", "form6k.htm"),
                ("EX-99.1", "ex99-1.htm"),
                ("EX-99.2", "ex99-2.htm"),
                ("GRAPHIC", "image.jpg"),
            ],
        )
        self.assertIsInstance(documents[0], SubmissionDocument)
        self.assertIn("Cover", documents[0].contents)

    def test_select_submission_documents_keeps_primary_and_exhibits_in_order(self) -> None:
        selected = select_submission_documents(
            parse_full_submission(FIXTURE), "form6k.htm"
        )

        self.assertEqual(
            [(document.doc_type, document.filename) for document in selected],
            [
                ("6-K", "form6k.htm"),
                ("EX-99.1", "ex99-1.htm"),
                ("EX-99.2", "ex99-2.htm"),
            ],
        )

    def test_render_submission_text_includes_primary_and_all_exhibits_with_separators(self) -> None:
        rendered = render_submission_text(
            select_submission_documents(parse_full_submission(FIXTURE), "form6k.htm")
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
            select_submission_documents(parse_full_submission(FIXTURE), "form6k.htm")
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
                parse_full_submission(NO_EXHIBIT_FIXTURE), "form6k.htm"
            )
        )

        self.assertEqual(rendered.count("Cover only"), 1)
        self.assertNotIn("EX-99", rendered)

    def test_missing_advertised_exhibit_raises_a_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "EX-99.1"):
            select_submission_documents(
                parse_full_submission(MISSING_EXHIBIT_FIXTURE), "form6k.htm"
            )


if __name__ == "__main__":
    unittest.main()
