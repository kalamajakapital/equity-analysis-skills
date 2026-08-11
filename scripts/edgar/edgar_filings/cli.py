from __future__ import annotations

import html
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

import click
from sec_edgar_downloader import Downloader
from sec_edgar_downloader._constants import (
    FILING_FULL_SUBMISSION_FILENAME,
    ROOT_SAVE_FOLDER_NAME,
    SUBMISSION_FILE_FORMAT,
    URL_SUBMISSIONS,
)
from sec_edgar_downloader._orchestrator import get_ticker_to_cik_mapping
from sec_edgar_downloader._sec_gateway import get_list_of_available_filings

# Annual-report form types used to anchor fiscal-year labelling.
ANNUAL_FORMS = {"10-K", "10-K405", "10-KSB", "20-F", "40-F"}
# Quarterly-report form types.
QUARTERLY_FORMS = {"10-Q", "10-QSB", "6-K"}


@dataclass(frozen=True)
class FilingRecord:
    accession_number: str
    form: str
    filing_date: date
    report_date: date | None
    primary_document: str
    fiscal_year_label: int | None = None
    fiscal_quarter: int | None = None


@dataclass(frozen=True)
class SubmissionDocument:
    doc_type: str
    sequence: int
    filename: str
    contents: str


def repo_root() -> Path:
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(result.stdout.strip())
    except Exception:
        return Path(__file__).resolve().parents[3]


def research_root() -> Path:
    return repo_root() / "research"


def filings_dir(ticker: str) -> Path:
    return research_root() / "data" / ticker.upper() / "filings"


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def load_repo_env_if_present() -> None:
    env_path = repo_root() / ".env"
    if not env_path.is_file():
        return

    for line_number, raw_line in enumerate(env_path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise click.ClickException(f"Invalid line in {env_path} at {line_number}: {raw_line}")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise click.ClickException(f"Invalid empty key in {env_path} at {line_number}.")
        if key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ[key] = value


def resolve_user_agent() -> tuple[str, str]:
    load_repo_env_if_present()
    email = os.environ.get("SEC_EDGAR_EMAIL")
    if not email:
        raise click.ClickException(
            "SEC_EDGAR_EMAIL is required. Set it in your environment or a .env file.\n"
            "Example: export SEC_EDGAR_EMAIL=you@example.com"
        )

    company_name = os.environ.get("SEC_EDGAR_COMPANY_NAME")
    if not company_name:
        raise click.ClickException(
            "SEC_EDGAR_COMPANY_NAME is required. Set it in your environment or a .env file.\n"
            "Example: export SEC_EDGAR_COMPANY_NAME=my-research"
        )

    return company_name, email


def fetch_submission_rows(
    ticker: str,
    forms: set[str],
    start: date | None,
    user_agent: str,
) -> list[FilingRecord]:
    ticker = ticker.upper()
    cik = get_ticker_to_cik_mapping(user_agent)[ticker]
    forms_for_metadata = set(forms)
    # Always pull all annual-report variants so fiscal-year anchoring works.
    forms_for_metadata.update(ANNUAL_FORMS)
    submissions_uri = URL_SUBMISSIONS.format(
        submission=SUBMISSION_FILE_FORMAT.format(cik=cik)
    )

    rows: list[FilingRecord] = []
    additional_pages: list[str] | None = None

    while submissions_uri:
        payload = get_list_of_available_filings(submissions_uri, user_agent)
        if additional_pages is None:
            recent = payload["filings"]["recent"]
            additional_pages = [page["name"] for page in payload["filings"]["files"]]
        else:
            recent = payload

        page_rows = [
            FilingRecord(
                accession_number=accession_number,
                form=form,
                filing_date=parse_iso_date(filing_date),
                report_date=parse_iso_date(report_date),
                primary_document=primary_document,
            )
            for accession_number, form, filing_date, report_date, primary_document in zip(
                recent["accessionNumber"],
                recent["form"],
                recent["filingDate"],
                recent["reportDate"],
                recent["primaryDocument"],
            )
            if form in forms_for_metadata
        ]

        rows.extend(page_rows)

        if start and any(row.filing_date < start for row in page_rows):
            break

        if not additional_pages:
            break

        submissions_uri = URL_SUBMISSIONS.format(submission=additional_pages.pop(0))

    if not rows:
        return []

    return assign_fiscal_labels(sorted(rows, key=lambda row: row.filing_date))


def assign_fiscal_labels(rows: list[FilingRecord]) -> list[FilingRecord]:
    labeled: list[FilingRecord] = []
    active_fiscal_year: int | None = None
    next_quarter = 1

    for row in rows:
        if row.form in ANNUAL_FORMS:
            if row.report_date is None:
                fiscal_year = row.filing_date.year
            else:
                fiscal_year = (
                    row.report_date.year - 1
                    if row.report_date.month <= 3
                    else row.report_date.year
                )

            labeled.append(
                FilingRecord(
                    accession_number=row.accession_number,
                    form=row.form,
                    filing_date=row.filing_date,
                    report_date=row.report_date,
                    primary_document=row.primary_document,
                    fiscal_year_label=fiscal_year,
                    fiscal_quarter=4,
                )
            )
            active_fiscal_year = fiscal_year + 1
            next_quarter = 1
            continue

        fiscal_year = active_fiscal_year
        quarter = next_quarter if next_quarter <= 3 else None

        labeled.append(
            FilingRecord(
                accession_number=row.accession_number,
                form=row.form,
                filing_date=row.filing_date,
                report_date=row.report_date,
                primary_document=row.primary_document,
                fiscal_year_label=fiscal_year,
                fiscal_quarter=quarter,
            )
        )

        if next_quarter <= 3:
            next_quarter += 1

    return labeled


def select_target_rows(
    rows: Iterable[FilingRecord],
    forms: list[str],
    start: date | None,
    end: date,
) -> list[FilingRecord]:
    filtered = [row for row in rows if row.filing_date <= end]
    if start is not None:
        return [row for row in filtered if row.filing_date >= start]

    latest_by_form: list[FilingRecord] = []
    for form in forms:
        form_rows = [row for row in filtered if row.form == form]
        if form_rows:
            latest_by_form.append(max(form_rows, key=lambda row: row.filing_date))
    return latest_by_form


def output_extension(output_format: str) -> str:
    return {
        "txt": ".txt",
        "raw": ".raw.txt",
        "html": ".html",
    }[output_format]


class FilingHTMLToTextParser(HTMLParser):
    BLOCK_TAGS = {"p", "div", "section", "article", "header", "footer", "ul", "ol"}
    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.in_table = False
        self.current_row: list[str] = []
        self.current_cell: list[str] = []
        self.table_rows: list[list[str]] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "ix:header"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "br":
            self.parts.append("\n")
        elif tag == "table":
            self.flush_inline_space()
            self.in_table = True
            self.table_rows = []
        elif tag == "tr" and self.in_table:
            self.current_row = []
        elif tag in {"td", "th"} and self.in_table:
            self.current_cell = []
        elif tag in self.HEADING_TAGS:
            self.parts.append("\n\n")
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "ix:header"}:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in {"td", "th"} and self.in_table:
            cell_text = normalize_whitespace("".join(self.current_cell))
            self.current_row.append(cell_text)
            self.current_cell = []
        elif tag == "tr" and self.in_table:
            if any(cell for cell in self.current_row):
                self.table_rows.append(self.current_row)
            self.current_row = []
        elif tag == "table":
            self.emit_table()
            self.in_table = False
        elif tag in self.HEADING_TAGS | self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.in_table and self.current_cell is not None:
            self.current_cell.append(data)
        else:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")

    def flush_inline_space(self) -> None:
        if self.parts and not self.parts[-1].endswith(("\n", " ")):
            self.parts.append("\n")

    def emit_table(self) -> None:
        if not self.table_rows:
            self.parts.append("\n")
            return

        compact_rows = [[cell for cell in row if cell] for row in self.table_rows]
        compact_rows = [row for row in compact_rows if row]
        if not compact_rows:
            self.parts.append("\n")
            return

        col_count = max(len(row) for row in compact_rows)
        widths = [0] * col_count
        for row in compact_rows:
            for idx, cell in enumerate(row):
                widths[idx] = min(max(widths[idx], len(cell)), 40)

        self.parts.append("\n")
        for row in compact_rows:
            padded = []
            for idx in range(col_count):
                cell = row[idx] if idx < len(row) else ""
                if idx == col_count - 1:
                    padded.append(cell)
                else:
                    padded.append(cell.ljust(widths[idx]))
            line = " | ".join(part.rstrip() for part in padded).rstrip()
            if line:
                self.parts.append(f"{line}\n")
        self.parts.append("\n")

    def get_text(self) -> str:
        return "".join(self.parts)


def normalize_whitespace(text: str) -> str:
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def convert_html_to_text(contents: str) -> str:
    parser = FilingHTMLToTextParser()
    parser.feed(html.unescape(contents))
    text = parser.get_text()
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def parse_full_submission(contents: str) -> list[SubmissionDocument]:
    """Extract complete document blocks from a SEC full-submission file."""
    documents: list[SubmissionDocument] = []
    document_blocks = re.finditer(
        r"<DOCUMENT>\s*(.*?)</DOCUMENT\s*>", contents, re.IGNORECASE | re.DOTALL
    )

    def field(block: str, name: str) -> str | None:
        match = re.search(rf"<{name}>\s*([^<\r\n]+)", block, re.IGNORECASE)
        return match.group(1).strip() if match else None

    for block_match in document_blocks:
        block = block_match.group(1)
        doc_type = field(block, "TYPE")
        sequence_text = field(block, "SEQUENCE")
        filename = field(block, "FILENAME")
        text_match = re.search(
            r"<TEXT>(.*?)(?:</TEXT\s*>|$)", block, re.IGNORECASE | re.DOTALL
        )
        if not all((doc_type, sequence_text, filename, text_match)):
            continue
        try:
            sequence = int(sequence_text)
        except ValueError:
            continue
        documents.append(
            SubmissionDocument(doc_type, sequence, filename, text_match.group(1))
        )

    return sorted(documents, key=lambda document: document.sequence)


def _advertised_exhibits(contents: str) -> tuple[set[str], list[str]]:
    exhibit_types = {
        f"EX-{match.group(1)}"
        for match in re.finditer(
            r"\b(?:exhibit|ex)\s*-?\s*(99(?:\.\d+)?)\b",
            contents,
            re.IGNORECASE,
        )
    }
    advertised_filenames = [
        match.group(1)
        for match in re.finditer(
            r"\b([\w.-]*ex[-_]?99[\w.-]*\.(?:html?|txt))\b",
            contents,
            re.IGNORECASE,
        )
    ]
    return exhibit_types, advertised_filenames


def select_submission_documents(
    documents: list[SubmissionDocument], primary_document: str, accession_number: str
) -> list[SubmissionDocument]:
    """Keep the primary document and all 99-series exhibits in SEC sequence order."""
    primary_name = Path(primary_document).name.casefold()
    primary = next(
        (document for document in documents if Path(document.filename).name.casefold() == primary_name),
        None,
    )
    if primary is None:
        raise ValueError(
            f"Primary document {primary_document!r} is missing from submission {accession_number}."
        )

    exhibits = [
        document
        for document in documents
        if document is not primary and document.doc_type.upper().startswith("EX-99")
    ]
    selected = [primary, *exhibits]

    advertised_types, advertised_filenames = _advertised_exhibits(primary.contents)
    selected_types = {document.doc_type.upper() for document in exhibits}
    missing_types = sorted(advertised_types - selected_types)
    selected_filenames = {Path(document.filename).name.casefold() for document in exhibits}
    missing_filenames = sorted(
        filename
        for filename in advertised_filenames
        if Path(filename).name.casefold() not in selected_filenames
    )
    if missing_types or missing_filenames:
        missing_types_text = ", ".join(missing_types) or "none"
        missing_filenames_text = ", ".join(missing_filenames) or "none"
        raise ValueError(
            f"Submission {accession_number} advertises missing exhibit(s) "
            f"type(s): {missing_types_text}; filename(s): {missing_filenames_text}."
        )
    return selected


def render_submission_text(documents: list[SubmissionDocument]) -> str:
    sections = [
        f"===== {document.doc_type} {document.filename} =====\n\n"
        f"{convert_html_to_text(document.contents).rstrip()}"
        for document in documents
    ]
    return "\n\n".join(sections) + "\n"


def render_submission_html(documents: list[SubmissionDocument]) -> str:
    sections = []
    for document in documents:
        heading = html.escape(f"{document.doc_type} {document.filename}")
        sections.append(f"<h1>{heading}</h1>\n{document.contents}")
    return "<!DOCTYPE html>\n<html><body>\n" + "\n<hr>\n".join(sections) + "\n</body></html>\n"


def download_selected_filings(
    ticker: str,
    forms: list[str],
    targets: list[FilingRecord],
    start: date | None,
    end: date,
    company_name: str,
    email: str,
    output_format: str,
) -> dict[str, Path]:
    paths_by_accession: dict[str, Path] = {}
    ticker_upper = ticker.upper()

    with tempfile.TemporaryDirectory(prefix="edgar-filings-") as temp_dir:
        downloader = Downloader(company_name, email, temp_dir)

        for form in forms:
            form_targets = [row for row in targets if row.form == form]
            if not form_targets:
                continue

            after = start.isoformat() if start else None
            before = end.isoformat()
            downloader.get(
                form,
                ticker_upper,
                limit=None if start else 1,
                after=after,
                before=before,
                download_details=output_format in {"txt", "html"},
                accession_numbers_to_skip={
                    row.accession_number
                    for row in targets
                    if row.form == form and row not in form_targets
                },
            )

            for row in form_targets:
                source_path = (
                    Path(temp_dir)
                    / ROOT_SAVE_FOLDER_NAME
                    / ticker_upper
                    / form
                    / row.accession_number
                    / FILING_FULL_SUBMISSION_FILENAME
                )
                if source_path.exists():
                    paths_by_accession[row.accession_number] = source_path

        output_dir = filings_dir(ticker_upper)
        output_dir.mkdir(parents=True, exist_ok=True)
        written_paths: dict[str, Path] = {}

        for row in targets:
            source_path = paths_by_accession.get(row.accession_number)
            if source_path is None:
                continue

            fiscal_year = row.fiscal_year_label or row.filing_date.year
            quarter = row.fiscal_quarter or 4
            output_name = f"{fiscal_year}_Q{quarter}_{row.form}{output_extension(output_format)}"
            output_path = output_dir / output_name

            if output_format == "raw":
                output_path.write_bytes(source_path.read_bytes())
            else:
                source_text = source_path.read_text(errors="replace")
                documents = select_submission_documents(
                    parse_full_submission(source_text),
                    row.primary_document,
                    row.accession_number,
                )
                rendered = (
                    render_submission_text(documents)
                    if output_format == "txt"
                    else render_submission_html(documents)
                )
                output_path.write_text(rendered)

            written_paths[row.accession_number] = output_path

        return written_paths


@click.command()
@click.option("--ticker", required=True, help="Ticker symbol, for example AAPL.")
@click.option(
    "--filing",
    "filings",
    multiple=True,
    type=str,
    default=("10-K",),
    show_default=True,
    help="One or more SEC form types to download (e.g. 10-K, 10-Q, 20-F, 40-F, 6-K, 8-K).",
)
@click.option(
    "--range-start",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Optional filing-date lower bound. If set, download all matching filings in range.",
)
@click.option(
    "--range-end",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Optional filing-date upper bound. Defaults to today.",
)
@click.option(
    "--output-format",
    type=click.Choice(("txt", "raw", "html"), case_sensitive=True),
    default="txt",
    show_default=True,
    help="Choose plain text, raw SEC submission, or HTML output.",
)
def main(
    ticker: str,
    filings: tuple[str, ...],
    range_start: datetime | None,
    range_end: datetime | None,
    output_format: str,
) -> None:
    """Download SEC EDGAR filings into research/data/<TICKER>/filings."""

    company_name, email = resolve_user_agent()
    user_agent = f"{company_name} {email}"

    ticker_upper = ticker.upper()
    start = range_start.date() if range_start else None
    end = range_end.date() if range_end else date.today()

    if start and start > end:
        raise click.ClickException("--range-start cannot be later than --range-end.")

    forms = list(dict.fromkeys(filings))
    rows = fetch_submission_rows(ticker_upper, set(forms), start, user_agent)
    if not rows:
        raise click.ClickException(f"No {', '.join(forms)} filings found for {ticker_upper}.")

    targets = select_target_rows(rows, forms, start, end)
    if not targets:
        raise click.ClickException(
            f"No matching filings found for {ticker_upper} between {start or 'earliest available'} and {end}."
        )

    try:
        written_paths = download_selected_filings(
            ticker=ticker_upper,
            forms=forms,
            targets=targets,
            start=start,
            end=end,
            company_name=company_name,
            email=email,
            output_format=output_format,
        )
    except ValueError as error:
        raise click.ClickException(str(error)) from error

    if not written_paths:
        raise click.ClickException("Downloader completed, but no filing files were written.")

    for row in sorted(targets, key=lambda item: (item.filing_date, item.form)):
        output_path = written_paths.get(row.accession_number)
        if output_path is None:
            continue
        click.echo(f"{row.form} {row.filing_date.isoformat()} -> {output_path.relative_to(repo_root())}")


if __name__ == "__main__":
    main()
