from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence

from pypdf import PdfReader, PdfWriter


class MergeMode(str, Enum):
    DUPLEX_GUARD = "duplex_guard"
    STANDARD = "standard"


class PdfMergeError(Exception):
    """Base error suitable for display to the user."""


class PdfValidationError(PdfMergeError):
    def __init__(self, issues: Sequence[tuple[Path, str]]) -> None:
        self.issues = list(issues)
        super().__init__("; ".join(f"{path}: {reason}" for path, reason in issues))


class OutputExistsError(PdfMergeError):
    pass


@dataclass(frozen=True)
class PdfInfo:
    path: Path
    page_count: int


@dataclass(frozen=True)
class MergeResult:
    output_path: Path
    source_pages: int
    blank_pages: int

    @property
    def final_pages(self) -> int:
        return self.source_pages + self.blank_pages


ProgressCallback = Callable[[int, int, Path], None]


def normalized_output_path(directory: str | Path, filename: str) -> Path:
    clean_name = filename.strip()
    if not clean_name:
        raise PdfMergeError("output_name_empty")
    if Path(clean_name).name != clean_name or clean_name in {".", ".."}:
        raise PdfMergeError("output_name_invalid")
    if not clean_name.lower().endswith(".pdf"):
        clean_name += ".pdf"
    return Path(directory).expanduser().resolve() / clean_name


def inspect_pdf(path: str | Path) -> PdfInfo:
    pdf_path = Path(path).expanduser().resolve()
    if not pdf_path.is_file():
        raise PdfMergeError("file_missing")
    try:
        reader = PdfReader(str(pdf_path), strict=False)
        if reader.is_encrypted:
            raise PdfMergeError("file_encrypted")
        count = len(reader.pages)
    except PdfMergeError:
        raise
    except (OSError, ValueError, EOFError) as exc:
        raise PdfMergeError("file_unreadable") from exc
    except Exception as exc:
        raise PdfMergeError("file_invalid") from exc
    if count == 0:
        raise PdfMergeError("file_empty")
    return PdfInfo(pdf_path, count)


def validate_inputs(paths: Sequence[str | Path], output_path: str | Path) -> list[PdfInfo]:
    if len(paths) < 2:
        raise PdfMergeError("need_two_files")

    output = Path(output_path).expanduser().resolve()
    issues: list[tuple[Path, str]] = []
    infos: list[PdfInfo] = []
    seen: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        key = Path(os.path.normcase(str(path)))
        if key in seen:
            issues.append((path, "file_duplicate"))
            continue
        seen.add(key)
        if path == output:
            issues.append((path, "output_matches_input"))
            continue
        try:
            infos.append(inspect_pdf(path))
        except PdfMergeError as exc:
            issues.append((path, str(exc)))
    if issues:
        raise PdfValidationError(issues)
    return infos


def merge_pdfs(
    paths: Sequence[str | Path],
    output_path: str | Path,
    mode: MergeMode = MergeMode.DUPLEX_GUARD,
    *,
    overwrite: bool = False,
    progress: ProgressCallback | None = None,
) -> MergeResult:
    output = Path(output_path).expanduser().resolve()
    infos = validate_inputs(paths, output)
    if output.exists() and not overwrite:
        raise OutputExistsError("output_exists")
    if not output.parent.is_dir():
        raise PdfMergeError("output_directory_missing")

    writer = PdfWriter()
    source_pages = 0
    blank_pages = 0
    temporary_path: Path | None = None
    try:
        for index, info in enumerate(infos):
            reader = PdfReader(str(info.path), strict=False)
            for page in reader.pages:
                writer.add_page(page)
            source_pages += info.page_count

            should_pad = (
                mode == MergeMode.DUPLEX_GUARD
                and index < len(infos) - 1
                and info.page_count % 2 == 1
            )
            if should_pad:
                last_page = reader.pages[-1]
                width = float(last_page.mediabox.width)
                height = float(last_page.mediabox.height)
                blank = writer.add_blank_page(width=width, height=height)
                rotation = int(last_page.get("/Rotate", 0)) % 360
                if rotation:
                    blank.rotate(rotation)
                blank_pages += 1
            if progress:
                progress(index + 1, len(infos), info.path)

        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".tmp", prefix=".pdf-merge-guard-", dir=output.parent, delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            writer.write(handle)
        os.replace(temporary_path, output)
        temporary_path = None
    except PdfMergeError:
        raise
    except PermissionError as exc:
        raise PdfMergeError("output_permission_denied") from exc
    except OSError as exc:
        raise PdfMergeError("output_write_failed") from exc
    finally:
        writer.close()
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    return MergeResult(output, source_pages, blank_pages)

