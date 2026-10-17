from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_submission_6k() -> str:
    """Raw SEC full-submission text file: 6-K cover + EX-99.1 press release + EX-101 XBRL."""
    return (FIXTURES_DIR / "sample_submission_6k.txt").read_text()


@pytest.fixture
def sample_submission_8k() -> str:
    """Raw SEC full-submission text file: 8-K cover + EX-99.1 press release + EX-101 XBRL."""
    return (FIXTURES_DIR / "sample_submission_8k.txt").read_text()


@pytest.fixture
def submission_no_document_markers() -> str:
    """Raw submission with no <DOCUMENT> markers — exercises the fallback path."""
    return (FIXTURES_DIR / "submission_no_document_markers.txt").read_text()


@pytest.fixture
def submission_missing_text_block() -> str:
    """Raw submission where one document lacks a <TEXT> block — exercises the warning path."""
    return (FIXTURES_DIR / "submission_missing_text_block.txt").read_text()
