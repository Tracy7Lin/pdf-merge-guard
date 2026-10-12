from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from pdf_merge_guard.core import (
    MergeMode,
    OutputExistsError,
    PdfMergeError,
    PdfValidationError,
    inspect_pdf,
    merge_pdfs,
    normalized_output_path,
)


def make_pdf(path: Path, pages: int, width: float = 300, height: float = 500, rotation: int = 0) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=width, height=height)
        if rotation:
            page.rotate(rotation)
    with path.open("wb") as handle:
        writer.write(handle)
    writer.close()
    return path


@pytest.mark.parametrize(
    ("counts", "expected_blanks", "expected_total"),
    [
        ([3, 4, 5], 1, 13),
        ([2, 3], 0, 5),
        ([3, 3, 3], 2, 11),
        ([3, 2], 1, 6),
    ],
)
def test_duplex_guard_padding(tmp_path: Path, counts: list[int], expected_blanks: int, expected_total: int) -> None:
    inputs = [make_pdf(tmp_path / f"{index}.pdf", count) for index, count in enumerate(counts)]
    result = merge_pdfs(inputs, tmp_path / "out.pdf", MergeMode.DUPLEX_GUARD)

    assert result.blank_pages == expected_blanks
    assert result.final_pages == expected_total
    assert len(PdfReader(result.output_path).pages) == expected_total


def test_standard_merge_keeps_order_without_padding(tmp_path: Path) -> None:
    first = make_pdf(tmp_path / "first.pdf", 3, width=111)
    second = make_pdf(tmp_path / "second.pdf", 2, width=222)
    result = merge_pdfs([first, second], tmp_path / "out.pdf", MergeMode.STANDARD)
    pages = PdfReader(result.output_path).pages

    assert result.blank_pages == 0
    assert [float(page.mediabox.width) for page in pages] == [111, 111, 111, 222, 222]


def test_padding_copies_size_and_rotation(tmp_path: Path) -> None:
    first = make_pdf(tmp_path / "landscape.pdf", 1, width=700, height=400, rotation=90)
    second = make_pdf(tmp_path / "second.pdf", 1)
    result = merge_pdfs([first, second], tmp_path / "out.pdf")
    blank = PdfReader(result.output_path).pages[1]

    assert float(blank.mediabox.width) == 700
    assert float(blank.mediabox.height) == 400
    assert blank.rotation == 90


def test_last_odd_file_is_not_padded(tmp_path: Path) -> None:
    first = make_pdf(tmp_path / "first.pdf", 2)
    last = make_pdf(tmp_path / "last.pdf", 3)
    result = merge_pdfs([first, last], tmp_path / "out.pdf")
    assert result.blank_pages == 0
    assert result.final_pages == 5


def test_rejects_missing_corrupt_empty_and_encrypted_files(tmp_path: Path) -> None:
    valid = make_pdf(tmp_path / "valid.pdf", 1)
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_text("not a pdf", encoding="utf-8")
    empty_pdf = make_pdf(tmp_path / "empty.pdf", 0)
    encrypted = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    with encrypted.open("wb") as handle:
        writer.write(handle)

    with pytest.raises(PdfValidationError) as caught:
        merge_pdfs(
            [valid, tmp_path / "missing.pdf", corrupt, empty_pdf, encrypted],
            tmp_path / "out.pdf",
        )
    reasons = {reason for _, reason in caught.value.issues}
    assert {"file_missing", "file_empty", "file_encrypted"} <= reasons
    assert reasons & {"file_invalid", "file_unreadable"}


def test_rejects_output_input_collision_and_duplicates(tmp_path: Path) -> None:
    first = make_pdf(tmp_path / "first.pdf", 1)
    second = make_pdf(tmp_path / "second.pdf", 1)
    with pytest.raises(PdfValidationError):
        merge_pdfs([first, second], first)
    with pytest.raises(PdfValidationError):
        merge_pdfs([first, first], tmp_path / "out.pdf")


def test_existing_output_is_preserved_without_permission(tmp_path: Path) -> None:
    first = make_pdf(tmp_path / "first.pdf", 1)
    second = make_pdf(tmp_path / "second.pdf", 1)
    output = tmp_path / "out.pdf"
    output.write_bytes(b"keep me")
    with pytest.raises(OutputExistsError):
        merge_pdfs([first, second], output)
    assert output.read_bytes() == b"keep me"


def test_output_name_normalization(tmp_path: Path) -> None:
    assert normalized_output_path(tmp_path, " result ") == tmp_path.resolve() / "result.pdf"
    assert normalized_output_path(tmp_path, "result.PDF").name == "result.PDF"
    with pytest.raises(PdfMergeError):
        normalized_output_path(tmp_path, "../escape.pdf")
    with pytest.raises(PdfMergeError):
        normalized_output_path(tmp_path, "bad:name.pdf")
    with pytest.raises(PdfMergeError):
        normalized_output_path(tmp_path, "CON.pdf")
    with pytest.raises(PdfMergeError, match="output_directory_missing"):
        normalized_output_path("", "result.pdf")


def test_single_file_is_rejected(tmp_path: Path) -> None:
    only = make_pdf(tmp_path / "only.pdf", 1)
    with pytest.raises(PdfMergeError, match="need_two_files"):
        merge_pdfs([only], tmp_path / "out.pdf")


def test_inspect_pdf_reports_pages(tmp_path: Path) -> None:
    path = make_pdf(tmp_path / "sample.pdf", 4)
    assert inspect_pdf(path).page_count == 4

