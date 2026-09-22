"""PDF ingestion with page-aware provenance and selective OCR."""

from typing import List

import fitz  # pip package is "pymupdf", import name is "fitz"

from domain.models import (
    DocumentPageText,
    SourceTextOrigin,
    SourceVerificationStatus,
)


DEFAULT_OCR_LANGUAGE = "eng"
DEFAULT_OCR_DPI = 300


def extract_document_pages(
    pdf_bytes: bytes,
    *,
    ocr_empty_pages: bool = True,
    ocr_language: str = DEFAULT_OCR_LANGUAGE,
    ocr_dpi: int = DEFAULT_OCR_DPI,
) -> List[DocumentPageText]:
    """Extract one provenance-aware record per physical PDF page.

    Embedded text is preferred and never replaced by OCR. OCR is attempted
    only when a page has no usable embedded text. OCR text is explicitly
    marked REQUIRES_VERIFICATION because recognition quality depends on the
    raster input and OCR engine.

    Raises:
        RuntimeError: The PDF cannot be read, or OCR is required but cannot
            be executed for a scanned page.
    """
    doc = None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages: List[DocumentPageText] = []
        for page_number, page in enumerate(doc, start=1):
            embedded_text = page.get_text()
            if isinstance(embedded_text, str) and embedded_text.strip():
                pages.append(
                    DocumentPageText(
                        page_number=page_number,
                        text=embedded_text,
                        origin=SourceTextOrigin.EMBEDDED,
                        verification=SourceVerificationStatus.VERIFIED,
                    )
                )
                continue

            if not ocr_empty_pages:
                pages.append(
                    DocumentPageText(
                        page_number=page_number,
                        text="",
                        origin=SourceTextOrigin.UNKNOWN,
                        verification=(
                            SourceVerificationStatus.REQUIRES_VERIFICATION
                        ),
                    )
                )
                continue

            try:
                text_page = page.get_textpage_ocr(
                    language=ocr_language,
                    dpi=ocr_dpi,
                    full=True,
                )
                ocr_text = page.get_text(textpage=text_page)
            except Exception as error:
                raise RuntimeError(
                    "OCR is required for scanned page "
                    f"{page_number}, but OCR could not run. "
                    "Check the Tesseract OCR installation and language data."
                ) from error

            pages.append(
                DocumentPageText(
                    page_number=page_number,
                    text=ocr_text if isinstance(ocr_text, str) else "",
                    origin=SourceTextOrigin.OCR,
                    verification=(
                        SourceVerificationStatus.REQUIRES_VERIFICATION
                    ),
                    ocr_language=ocr_language,
                    ocr_dpi=ocr_dpi,
                )
            )
        return pages
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError(f"Could not read this PDF: {error}") from error
    finally:
        if doc is not None:
            doc.close()


def extract_page_texts(pdf_bytes: bytes) -> List[str]:
    """Backward-compatible embedded-text-only page extraction.

    This API intentionally performs no OCR, preserving the Phase 3A.1
    contract for callers/tests that need the exact historical behavior.
    """
    doc = None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return [page.get_text() for page in doc]
    except Exception as error:
        raise RuntimeError(f"Could not read this PDF: {error}") from error
    finally:
        if doc is not None:
            doc.close()


def extract_text(pdf_bytes: bytes) -> str:
    """Backward-compatible flattened embedded-text extraction."""
    return "".join(extract_page_texts(pdf_bytes))
