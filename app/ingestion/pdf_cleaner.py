"""
pdf_cleaner.py

Preprocessing steps that MUST run before clause-splitting/chunking a SEBI
circular PDF. Skipping these corrupts clause boundaries and pollutes
embeddings with header/footer noise.

Usage:
    from app.ingestion.pdf_cleaner import extract_and_clean
    clean_text = extract_and_clean("data/raw_pdfs/stockbroker_mc_2025-06-17.pdf")
"""

import logging
import re
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


def extract_pages(pdf_path: str) -> list[str]:
    """Extract raw text per page. Flags pages that look like scanned
    images (empty/near-empty text) so they can be routed to OCR."""
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text()
        if len(text.strip()) < 20:
            logger.warning(
                "Page %d returned near-empty text - likely scanned/image page, needs OCR.", i + 1
            )
        pages.append(text)
    return pages


def strip_headers_footers(text: str) -> str:
    """Remove repeating page numbers and circular reference lines that
    appear on every page (not part of clause content)."""
    text = re.sub(r'Page \d+ of \d+', '', text)
    text = re.sub(r'SEBI/HO/[A-Z\-]+/[A-Z0-9\-/]+/\d{4}(/\d+)?', '', text)
    text = re.sub(r'\b(Circular No\.?|Ref\.? No\.?)\s*:?\s*$', '', text, flags=re.MULTILINE)
    return text


def dehyphenate(text: str) -> str:
    """Fix words split across line-wraps, e.g. 'segrega-\\ntion' -> 'segregation'."""
    return re.sub(r'-\n(?=[a-z])', '', text)


def normalize_whitespace(text: str) -> str:
    """Collapse inconsistent spacing/newlines from PDF extraction."""
    text = text.replace('\xa0', ' ')          # non-breaking spaces
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


BOILERPLATE_PATTERNS = [
    r"In exercise of the powers conferred.*?(?=\n)",
    r"Securities and Exchange Board of India.*?hereby issues.*?(?=\n)",
    r"This Master Circular is a compilation of.*?(?=\n)",
]

def remove_boilerplate(text: str) -> str:
    """Strip standard legal preamble boilerplate that isn't an obligation
    and would confuse the extractor if chunked as if it were a clause."""
    for pattern in BOILERPLATE_PATTERNS:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)
    return text


def extract_and_clean(pdf_path: str) -> str:
    """Full preprocessing pipeline: extract -> clean each page -> join."""
    pages = extract_pages(pdf_path)
    cleaned_pages = []
    for page_text in pages:
        t = strip_headers_footers(page_text)
        t = dehyphenate(t)
        t = normalize_whitespace(t)
        cleaned_pages.append(t)

    full_text = "\n\n".join(cleaned_pages)
    full_text = remove_boilerplate(full_text)
    return full_text


def qa_spot_check(clean_text: str, n: int = 5):
    """Print a handful of paragraphs so you can manually verify no
    header/footer junk or broken words remain before chunking."""
    paras = [p for p in clean_text.split("\n\n") if len(p.strip()) > 40]
    print(f"Total usable paragraphs: {len(paras)}")
    for p in paras[:n]:
        print("---")
        print(p[:300])


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "data/raw_pdfs/stockbroker_mc_2025-06-17.pdf"
    cleaned = extract_and_clean(path)
    qa_spot_check(cleaned)
