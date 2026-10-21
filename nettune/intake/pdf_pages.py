"""Turns a scanned PDF into one image per page.

The office scanner produces multi-page PDFs -- one day's sheet per page -- and
the Vision API takes images, so each page is rasterised before transcription.
Uses poppler's pdftoppm, which is already a dependency of any Debian scanner
setup and needs no Python bindings.
"""

import glob
import logging
import os
import shutil
import subprocess

PDF_EXTENSIONS = frozenset({".pdf"})


class PdfRenderError(RuntimeError):
    """The PDF could not be read or rasterised."""


def is_pdf(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in PDF_EXTENSIONS


def _require_poppler(tool: str) -> str:
    found = shutil.which(tool)
    if not found:
        raise PdfRenderError(
            f"{tool} not found. Install poppler-utils (sudo apt install poppler-utils)."
        )
    return found


def page_count(pdf_path: str) -> int:
    """Number of pages, or 0 if it cannot be determined."""
    try:
        out = subprocess.run(
            [_require_poppler("pdfinfo"), pdf_path],
            capture_output=True, text=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise PdfRenderError(f"Could not read {pdf_path}: {exc}") from exc
    for line in out.splitlines():
        if line.lower().startswith("pages:"):
            return int(line.split(":", 1)[1].strip())
    return 0


def render_pages(pdf_path: str, out_dir: str, dpi: int = 300) -> list[str]:
    """Rasterise every page to JPEG at *dpi*, returning the paths in order."""
    os.makedirs(out_dir, exist_ok=True)
    prefix = os.path.join(out_dir, "page")
    try:
        result = subprocess.run(
            [_require_poppler("pdftoppm"), "-jpeg", "-r", str(dpi), pdf_path, prefix],
            capture_output=True, text=True, timeout=900,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PdfRenderError(f"Could not rasterise {pdf_path}: {exc}") from exc

    pages = sorted(glob.glob(prefix + "-*.jpg"))
    if not pages:
        raise PdfRenderError(
            f"No pages rendered from {pdf_path}. pdftoppm said: "
            f"{(result.stderr or '').strip()[:200]}"
        )
    logging.warning(f"Rendered {len(pages)} page(s) from {os.path.basename(pdf_path)} at {dpi} dpi")
    return pages
