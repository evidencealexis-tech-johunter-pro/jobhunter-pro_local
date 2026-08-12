"""
Robust PDF Text Extraction — Industry-Standard Cascade Pattern
Updated with explicit Tesseract path for Windows.
"""

import io
import fitz  # PyMuPDF
from PIL import Image
import pytesseract

# --- Tesseract Configuration ---
# Explicitly point to your local Tesseract installation
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

MIN_CHARS_PER_PAGE = 40  # Threshold for "failed" extraction

def _extract_native_text(pdf_path):
    """Fast path: pull text directly from the PDF's embedded text layer."""
    pages = []
    doc = fitz.open(pdf_path)
    try:
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            pages.append((page_num, text))
    finally:
        doc.close()
    return pages

def _ocr_page(pdf_path, page_num):
    """Fallback path: render page as image, run Tesseract OCR."""
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_num - 1]
        # Render at 2x zoom for better OCR accuracy on small resume fonts
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img).strip()
    finally:
        doc.close()

def extract_text_from_pdf(pdf_path, verbose=True):
    """
    Main entry point for robust extraction.
    Returns: { "success": bool, "text": str, ... }
    """
    try:
        native_pages = _extract_native_text(pdf_path)
    except Exception as e:
        return {
            "success": False, "text": "", "pages_total": 0,
            "pages_native": 0, "pages_ocr": 0, "pages_failed": 0,
            "error": f"Could not open PDF: {e}",
        }

    if not native_pages:
        return {
            "success": False, "text": "", "pages_total": 0,
            "pages_native": 0, "pages_ocr": 0, "pages_failed": 0,
            "error": "PDF has no pages.",
        }

    final_pages = []
    pages_native = 0
    pages_ocr = 0
    pages_failed = 0

    for page_num, text in native_pages:
        if len(text) >= MIN_CHARS_PER_PAGE:
            final_pages.append(text)
            pages_native += 1
            continue

        # Native extraction failed - try OCR
        if verbose:
            print(f"Page {page_num}: native extraction returned {len(text)} chars - trying OCR...")
        try:
            ocr_text = _ocr_page(pdf_path, page_num)
        except Exception as e:
            ocr_text = ""
            if verbose:
                print(f"Page {page_num}: OCR failed - {e}")

        if len(ocr_text) >= MIN_CHARS_PER_PAGE:
            final_pages.append(ocr_text)
            pages_ocr += 1
            if verbose:
                print(f"Page {page_num}: OCR recovered {len(ocr_text)} chars.")
        else:
            pages_failed += 1
            if verbose:
                print(f"Page {page_num}: unreadable by both methods.")

    full_text = "\n\n".join(final_pages).strip()
    total = len(native_pages)

    if not full_text:
        return {
            "success": False, "text": "", "pages_total": total,
            "pages_native": pages_native, "pages_ocr": pages_ocr,
            "pages_failed": pages_failed,
            "error": f"All {total} page(s) failed both native extraction and OCR.",
        }

    return {
        "success": True, "text": full_text, "pages_total": total,
        "pages_native": pages_native, "pages_ocr": pages_ocr,
        "pages_failed": pages_failed, "error": None,
    }