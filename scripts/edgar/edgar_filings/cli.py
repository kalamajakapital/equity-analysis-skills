from __future__ import annotations

import html
import os
import re
import tempfile
from dataclasses import dataclass, replace
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
# Event-driven forms: multiple filings per fiscal quarter are expected.
EVENT_FORMS = {"6-K", "8-K"}


@dataclass(frozen=True)
class FilingRecord:
    accession_number: str
    form: str
    filing_date: date
    report_date: date | None
    primary_document: str
    fiscal_year_label: int | None = None
    fiscal_quarter: int | None = None


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


def infer_fy_end_month(rows: list[FilingRecord]) -> int | None:
    """Infer the fiscal-year-end month from the most recent annual report's period date."""
    annual_rows = [
        row for row in rows if row.form in ANNUAL_FORMS and row.report_date is not None
    ]
    if not annual_rows:
        return None
    latest = max(annual_rows, key=lambda row: row.filing_date)
    return latest.report_date.month


def fiscal_label_from_report_date(report_date: date, fy_end_month: int) -> tuple[int, int]:
    """Return (fiscal_year, quarter) for a periodic filing.

    Fiscal years are labelled by the calendar year in which they end. A period
    ending exactly on the fiscal year-end is Q4 of the fiscal year ending that
    year; later periods belong to the following fiscal year.
    """
    month_diff = (report_date.month - fy_end_month) % 12
    quarter = 4 if month_diff == 0 else (month_diff - 1) // 3 + 1
    fiscal_year = report_date.year + (1 if report_date.month > fy_end_month else 0)
    return fiscal_year, quarter


def assign_fiscal_labels(rows: list[FilingRecord]) -> list[FilingRecord]:
    labeled: list[FilingRecord] = []
    fy_end_month = infer_fy_end_month(rows)
    active_fiscal_year: int | None = None
    next_quarter = 1

    for row in rows:
        if row.form in ANNUAL_FORMS:
            if row.report_date is None:
                fiscal_year = row.filing_date.year
            else:
                end_month = (
                    fy_end_month if fy_end_month is not None else row.report_date.month
                )
                fiscal_year = row.report_date.year + (
                    1 if row.report_date.month > end_month else 0
                )

            labeled.append(
                replace(
                    row,
                    fiscal_year_label=fiscal_year,
                    fiscal_quarter=4,
                )
            )
            active_fiscal_year = fiscal_year + 1
            next_quarter = 1
            continue

        if row.report_date is not None and fy_end_month is not None:
            fiscal_year, quarter = fiscal_label_from_report_date(
                row.report_date, fy_end_month
            )
            labeled.append(
                replace(
                    row,
                    fiscal_year_label=fiscal_year,
                    fiscal_quarter=quarter,
                )
            )
            continue

        # Fallback when no period date is available: assign quarters
        # sequentially after the most recent annual report.
        fiscal_year = active_fiscal_year
        quarter = next_quarter if next_quarter <= 3 else None

        labeled.append(
            replace(
                row,
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


# Submission document types that are machine-readable XBRL taxonomies or
# binary artifacts, not readable filing content.
SKIP_DOCUMENT_TYPES = re.compile(
    r"^(EX-10[0-9]|GRAPHIC|ZIP|XLS|XLSX|XML|JSON|EXCEL|PNG|JPG|JPEG|GIF|SVG)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SubmissionDocument:
    doc_type: str
    description: str
    content: str


def parse_submission_documents(raw_submission: str) -> list[SubmissionDocument]:
    """Split a full EDGAR submission text file into its <DOCUMENT> sections."""
    documents: list[SubmissionDocument] = []
    skipped_types: list[str] = []
    chunks = re.split(r"<DOCUMENT>", raw_submission, flags=re.IGNORECASE)[1:]
    for chunk in chunks:
        type_match = re.search(r"<TYPE>\s*([^\r\n<]+)", chunk, re.IGNORECASE)
        desc_match = re.search(r"<DESCRIPTION>\s*([^\r\n<]*)", chunk, re.IGNORECASE)
        text_match = re.search(r"<TEXT>(.*?)</TEXT>", chunk, re.IGNORECASE | re.DOTALL)
        if text_match is None:
            skipped_types.append(
                (type_match.group(1) if type_match else "").strip().upper()
            )
            continue
        documents.append(
            SubmissionDocument(
                doc_type=(type_match.group(1) if type_match else "").strip().upper(),
                description=(desc_match.group(1) if desc_match else "").strip(),
                content=text_match.group(1),
            )
        )

    if skipped_types:
        for doc_type in skipped_types:
            click.echo(
                f"warning: document {doc_type or 'unnamed'} has no <TEXT> block; skipped",
                err=True,
            )

    return documents


def submission_to_text(raw_submission: str) -> str:
    """Convert every readable document in a full submission to text.

    The primary document of a 6-K is typically only a cover page; the actual
    content lives in furnished exhibits. Converting the whole submission keeps
    cover and exhibits together in one readable file.
    """
    sections: list[str] = []
    for document in parse_submission_documents(raw_submission):
        if not document.doc_type and not document.content.strip():
            continue
        if SKIP_DOCUMENT_TYPES.match(document.doc_type):
            continue
        label = document.doc_type or "DOCUMENT"
        if document.description:
            label = f"{label} ({document.description})"
        sections.append(f"=== {label} ===\n\n{convert_html_to_text(document.content)}")

    if sections:
        return "\n\n".join(sections) + "\n"

    # Fallback: submission without <DOCUMENT> markers.
    without_header = re.sub(
        r"<SEC-HEADER>.*?</SEC-HEADER>", "", raw_submission,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if re.search(r"<SEC-HEADER>", without_header, re.IGNORECASE):
        # Unclosed <SEC-HEADER>: strip through the end of the header-opening
        # line rather than leaking header junk into the converted text.
        without_header = re.sub(
            r"(?is)^.*<SEC-HEADER>[^\n]*\n?", "", without_header, count=1
        )
    return convert_html_to_text(without_header)


def output_names_for_targets(targets: list[FilingRecord]) -> dict[str, str]:
    """Map accession number to a collision-free output base name (no extension).

    Determinism contract: same filing ⇒ same name. For rows carrying a
    fiscal label the name is independent of fetch scope; rows that fall
    back to sequential labelling (no report_date, no annual form in the
    metadata) inherit scope dependence from the labelling layer.
    Event-driven forms (6-K, 8-K) always carry the filing date and an
    accession suffix, because several of them land in the same fiscal quarter
    (earnings releases, press responses, trading updates) — the suffix is
    unconditional so the name never depends on what else is being fetched.
    Periodic forms (10-K, 10-Q, 20-F, 40-F) keep the short base name, which
    is unique per fiscal period by construction.
    """
    names: dict[str, str] = {}
    used: set[str] = set()
    for row in targets:
        fiscal_year = row.fiscal_year_label or row.filing_date.year
        quarter = row.fiscal_quarter or 4
        form = re.sub(r"[^A-Za-z0-9.-]", "_", row.form)
        base = f"{fiscal_year}_Q{quarter}_{form}"
        # 6-K/A and 8-K/A amendments do not exact-match EVENT_FORMS, so they
        # take the periodic branch below (quarter-anchored naming) — intentional.
        if row.form in EVENT_FORMS:
            accession6 = row.accession_number.replace("-", "")[-6:]
            name = f"{base}_{row.filing_date.isoformat()}_{accession6}"
            # Theoretical-only guard: two distinct accessions sharing the
            # same last-6 characters would silently map to one path. On
            # collision, rebuild the name from the full dash-stripped
            # accession (unique per filing). The fallback name is still a
            # pure function of the row, but WHICH name applies depends on
            # whether the colliding sibling is in scope — acceptably
            # theoretical, since accession6 collisions across filing agents
            # are vanishingly rare.
            if name in used:
                name = f"{base}_{row.filing_date.isoformat()}_{row.accession_number.replace('-', '')}"
            while name in used:
                name = f"{name}_x"
        else:
            # Periodic filings are unique per period by construction, so the
            # catch-all below inspects the fetch set only for periodic-form
            # collisions (e.g. a 10-Q/A amendment in the same fiscal quarter).
            # Event forms never reach it: their suffix is unconditional,
            # keeping their names a pure function of the row's own fields.
            name = base
            while name in used:
                name = f"{name}_x"
        used.add(name)
        names[row.accession_number] = name
    return names


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
                # Only the html format needs the primary document itself;
                # txt conversion reads every document from the full submission.
                download_details=output_format == "html",
                accession_numbers_to_skip={
                    row.accession_number
                    for row in targets
                    if row.form == form and row not in form_targets
                },
            )

            for row in form_targets:
                if output_format == "html":
                    details_suffix = Path(row.primary_document).suffix.replace("htm", "html")
                    source_path = (
                        Path(temp_dir)
                        / ROOT_SAVE_FOLDER_NAME
                        / ticker_upper
                        / form
                        / row.accession_number
                        / f"primary-document{details_suffix}"
                    )
                else:
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

        output_names = output_names_for_targets(targets)

        for row in targets:
            source_path = paths_by_accession.get(row.accession_number)
            if source_path is None:
                continue

            output_name = output_names[row.accession_number] + output_extension(output_format)
            output_path = output_dir / output_name
            source_text = source_path.read_text(errors="replace")

            if output_format == "txt":
                output_path.write_text(submission_to_text(source_text))
            else:
                output_path.write_text(source_text)

            written_paths[row.accession_number] = output_path

        return written_paths


def classify_corpus(
    output_dir: Path,
    all_rows: list[FilingRecord],
    targets: list[FilingRecord],
) -> tuple[list[tuple[FilingRecord, Path]], list[FilingRecord], list[Path]]:
    """Classify on-disk filing artifacts against EDGAR metadata.

    ``present``/``missing`` are computed from the range-filtered ``targets``.
    The orphan scan accepts any file whose name matches a filing EDGAR knows
    about: names are computed over ``all_rows`` (the full fetched history for
    the requested forms plus the always-included annual forms) as well as
    ``targets``, so files outside the requested range or form are not falsely
    flagged as overwritten or mislabelled downloads.
    """
    extensions = [output_extension(fmt) for fmt in ("txt", "raw", "html")]

    target_names = output_names_for_targets(targets)
    expected_files: set[str] = set()
    for rows in (targets, all_rows):
        for name in output_names_for_targets(rows).values():
            expected_files.update(f"{name}{ext}" for ext in extensions)

    present: list[tuple[FilingRecord, Path]] = []
    missing: list[FilingRecord] = []
    for row in targets:
        base = target_names[row.accession_number]
        candidates = [output_dir / f"{base}{ext}" for ext in extensions]
        found = [c for c in candidates if c.exists()]
        if found:
            present.append((row, found[0]))
        else:
            missing.append(row)

    orphans: list[Path] = []
    if output_dir.is_dir():
        for path in sorted(output_dir.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".txt", ".html"}:
                continue  # manually imported files (e.g. PDFs) are out of scope
            if path.name in expected_files:
                continue
            orphans.append(path)

    return present, missing, orphans


def verify_corpus(
    ticker: str,
    forms: list[str],
    start: date | None,
    end: date,
    user_agent: str,
) -> None:
    """Compare the on-disk filing corpus against EDGAR metadata.

    Reports which filings in the requested range are present, missing, and
    which on-disk text artifacts no longer match any expected filename
    (evidence of prior overwrite bugs or mislabelled downloads). Downloads
    nothing.
    """
    ticker_upper = ticker.upper()
    # Full history regardless of range so fiscal-year anchoring has annuals.
    all_rows = fetch_submission_rows(ticker_upper, set(forms), None, user_agent)
    targets = [
        row
        for row in all_rows
        if row.form in forms
        and row.filing_date <= end
        and (start is None or row.filing_date >= start)
    ]
    if not targets:
        raise click.ClickException(
            f"No {', '.join(forms)} filings found for {ticker_upper} "
            f"between {start or 'earliest available'} and {end}."
        )

    output_dir = filings_dir(ticker_upper)
    present, missing, orphans = classify_corpus(output_dir, all_rows, targets)

    date_span = f"{start or 'earliest available'} .. {end}"
    click.echo(
        f"Verify {ticker_upper} ({', '.join(forms)}; {date_span}): "
        f"{len(present)} present, {len(missing)} missing, {len(orphans)} unrecognized"
    )

    if present:
        click.echo("Present:")
        for row, path in present:
            period = f" (period {row.report_date.isoformat()})" if row.report_date else ""
            click.echo(f"  {row.form} {row.filing_date.isoformat()}{period} -> {path.name}")

    if missing:
        click.echo("MISSING (filings known to EDGAR but not on disk):")
        for row in missing:
            period = f" (period {row.report_date.isoformat()})" if row.report_date else ""
            click.echo(f"  {row.form} {row.filing_date.isoformat()}{period}")

    if orphans:
        click.echo(
            "UNRECOGNIZED text files (possible overwritten or mislabelled downloads):"
        )
        for path in orphans:
            click.echo(f"  {path.name}")


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
@click.option(
    "--verify",
    "verify_only",
    is_flag=True,
    default=False,
    help="Compare on-disk filings against EDGAR metadata without downloading.",
)
def main(
    ticker: str,
    filings: tuple[str, ...],
    range_start: datetime | None,
    range_end: datetime | None,
    output_format: str,
    verify_only: bool,
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

    if verify_only:
        verify_corpus(
            ticker=ticker_upper,
            forms=forms,
            start=start,
            end=end,
            user_agent=user_agent,
        )
        return

    rows = fetch_submission_rows(ticker_upper, set(forms), start, user_agent)
    if not rows:
        raise click.ClickException(f"No {', '.join(forms)} filings found for {ticker_upper}.")

    targets = select_target_rows(rows, forms, start, end)
    if not targets:
        raise click.ClickException(
            f"No matching filings found for {ticker_upper} between {start or 'earliest available'} and {end}."
        )

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

    if not written_paths:
        raise click.ClickException("Downloader completed, but no filing files were written.")

    for row in sorted(targets, key=lambda item: (item.filing_date, item.form)):
        output_path = written_paths.get(row.accession_number)
        if output_path is None:
            continue
        period = f" (period {row.report_date.isoformat()})" if row.report_date else ""
        click.echo(
            f"{row.form} {row.filing_date.isoformat()}{period} -> "
            f"{output_path.relative_to(repo_root())}"
        )


if __name__ == "__main__":
    main()
