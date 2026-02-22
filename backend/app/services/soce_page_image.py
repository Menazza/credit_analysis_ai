"""
Render SoCE PDF page to PNG and upload to S3 for storage and LLM layout analysis.
"""
from __future__ import annotations

from typing import Tuple

from app.services.storage import upload_bytes, generate_soce_page_key


def render_pdf_page_to_png(pdf_bytes: bytes, page_no: int) -> bytes:
    """Render a PDF page to PNG bytes. Uses PyMuPDF (fitz)."""
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[page_no - 1]
        # Render at 2x for readability (helps LLM see small text)
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def upload_soce_page_image(
    pdf_bytes: bytes,
    page_no: int,
    tenant_id: str,
    doc_version_id: str,
) -> Tuple[str, bytes]:
    """
    Render SoCE page to PNG, upload to S3, return (storage_url, png_bytes).
    png_bytes is returned for base64 encoding to send to LLM.
    """
    png_bytes = render_pdf_page_to_png(pdf_bytes, page_no)
    key = generate_soce_page_key(str(tenant_id), str(doc_version_id), page_no)
    url = upload_bytes(key, png_bytes, content_type="image/png")
    return url, png_bytes
