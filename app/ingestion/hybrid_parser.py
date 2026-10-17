"""
hybrid_parser.py

Intelligent layout-aware document parser for RegOps AI.
Preserves document structures, maps section/clause hierarchies, extracts tables,
computes segmentation confidence scores, and falls back to legacy parsing.
"""

import logging
import os
import re
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

from app.ingestion.pdf_cleaner import (
    extract_and_clean,
    strip_headers_footers,
    dehyphenate,
    normalize_whitespace,
    remove_boilerplate,
)
from app.ingestion.clause_splitter import split_into_clauses


def is_inside_table(bbox, table_rects) -> bool:
    """Checks if the center of a block is located inside any of the table rectangles."""
    bx0, by0, bx1, by1 = bbox
    cx = (bx0 + bx1) / 2
    cy = (by0 + by1) / 2
    for tx0, ty0, tx1, ty1 in table_rects:
        if tx0 <= cx <= tx1 and ty0 <= cy <= ty1:
            return True
    return False


def table_to_markdown(rows: list[list[str]]) -> str:
    """Converts a table grid (list of list of cells) into a GFM Markdown string."""
    if not rows:
        return ""
    clean_rows = []
    for r in rows:
        clean_rows.append([str(c or "").strip().replace("\n", " ") for c in r])

    if not clean_rows or not any(clean_rows):
        return ""

    markdown = []
    headers = clean_rows[0]
    markdown.append("| " + " | ".join(headers) + " |")
    markdown.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in clean_rows[1:]:
        markdown.append("| " + " | ".join(row) + " |")
    return "\n".join(markdown)


def parse_pdf_structured(pdf_path: str) -> list[dict]:
    """
    Main entry point for intelligent PDF parsing.
    Attempts layout-aware block and table extraction.
    Falls back gracefully to legacy cleaners/splitters on any failure.
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.warning("Failed to open PDF with PyMuPDF: %s. Running legacy fallback.", e)
        return run_legacy_fallback(pdf_path)

    structured_chunks = []

    current_section = "General"
    current_subsection = ""
    current_clause = ""
    current_annexure = ""
    parent_clause = ""

    # Heuristics patterns for headers
    ANNEXURE_PATTERN = re.compile(
        r"^\s*(Annexure|Schedule|Appendix)\s*([A-Za-z0-9]*)\b", re.IGNORECASE
    )
    SECTION_PATTERN = re.compile(
        r"^\s*([I|V|X|L|C|D|M]+)\.\s+(.*)", re.IGNORECASE
    )  # e.g., I. Introduction
    SUBSECTION_PATTERN = re.compile(r"^\s*([A-Z])\.\s+(.*)")  # e.g., A. General
    CLAUSE_PATTERN = re.compile(
        r"^\s*(\d+(?:\.\d+)*)\.?\s+(.*)"
    )  # e.g., 2.3 or 1.

    clause_headers_count = 0

    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1

        # 1. Extract tables
        table_rects = []
        page_tables = []
        try:
            tables = page.find_tables()
            for tab in tables:
                table_rects.append(tab.bbox)
                rows = tab.extract()
                md_text = table_to_markdown(rows)
                if md_text.strip():
                    page_tables.append({"bbox": tab.bbox, "text": md_text})
        except Exception as e:
            logger.warning("Table extraction failed on page %s: %s", page_num, e)

        # 2. Extract layout text blocks
        try:
            blocks = page.get_text("blocks")
        except Exception as e:
            logger.warning("Block extraction failed on page %s: %s. Skipping page.", page_num, e)
            continue

        # Sort blocks by vertical position, then horizontal (reading order)
        blocks = sorted(blocks, key=lambda b: (b[1], b[0]))

        for block in blocks:
            bbox = block[:4]
            block_text = block[4].strip()
            block_type = block[6]

            # Skip empty or image blocks
            if not block_text or block_type != 0:
                continue

            # Skip if inside table boundary
            if is_inside_table(bbox, table_rects):
                continue

            # Clean and normalize paragraph text
            clean_block_text = strip_headers_footers(block_text)
            clean_block_text = dehyphenate(clean_block_text)
            clean_block_text = normalize_whitespace(clean_block_text)
            clean_block_text = remove_boilerplate(clean_block_text)

            if not clean_block_text.strip():
                continue

            # Group lines into paragraphs, splitting when a line starts with a new header
            raw_lines = [l.strip() for l in clean_block_text.split("\n") if l.strip()]
            paragraphs = []
            current_para = []
            
            for line in raw_lines:
                line_clean = normalize_whitespace(line)
                is_header = (
                    ANNEXURE_PATTERN.match(line_clean) or
                    SECTION_PATTERN.match(line_clean) or
                    SUBSECTION_PATTERN.match(line_clean) or
                    CLAUSE_PATTERN.match(line_clean)
                )
                
                if is_header and current_para:
                    paragraphs.append(" ".join(current_para))
                    current_para = [line]
                else:
                    current_para.append(line)
                    
            if current_para:
                paragraphs.append(" ".join(current_para))

            for para_text in paragraphs:
                clean_para_text = normalize_whitespace(para_text)
                if not clean_para_text:
                    continue

                annex_match = ANNEXURE_PATTERN.match(clean_para_text)
                sec_match = SECTION_PATTERN.match(clean_para_text)
                subsec_match = SUBSECTION_PATTERN.match(clean_para_text)
                clause_match = CLAUSE_PATTERN.match(clean_para_text)

                if annex_match:
                    current_annexure = clean_para_text[:100]
                    current_section = "General"
                    current_subsection = ""
                    current_clause = ""
                    parent_clause = ""

                    type_val = "annexure"
                    text_val = clean_para_text
                    confidence_val = 0.90
                elif sec_match:
                    current_section = sec_match.group(2)[:100]
                    current_subsection = ""
                    current_clause = ""
                    parent_clause = ""

                    type_val = "section"
                    text_val = clean_para_text
                    confidence_val = 0.90
                elif subsec_match:
                    current_subsection = subsec_match.group(2)[:100]
                    current_clause = ""
                    parent_clause = ""

                    type_val = "section"
                    text_val = clean_para_text
                    confidence_val = 0.90
                elif clause_match:
                    clause_num = clause_match.group(1)
                    current_clause = clause_num

                    if "." in clause_num:
                        parts = clause_num.split(".")
                        parent_clause = ".".join(parts[:-1])
                    else:
                        parent_clause = ""

                    clause_headers_count += 1
                    type_val = "obligation"
                    text_val = clean_para_text
                    confidence_val = 0.95
                else:
                    type_val = "obligation"
                    text_val = clean_para_text
                    confidence_val = 0.85
                    if not current_clause:
                        confidence_val = 0.60  # low confidence if no clause context is established

                    if len(clean_para_text) < 30 and not clean_para_text.endswith((".", ":", ";")):
                        confidence_val = 0.65  # possible orphan snippet

                structured_chunks.append({
                    "page": page_num,
                    "section": current_annexure or current_section,
                    "clause": current_clause,
                    "parent": parent_clause,
                    "text": text_val,
                    "type": type_val,
                    "confidence": confidence_val,
                })

        # Append tables as distinct blocks associated with the current section
        for page_table in page_tables:
            structured_chunks.append({
                "page": page_num,
                "section": current_annexure or current_section,
                "clause": current_clause,
                "parent": parent_clause,
                "text": page_table["text"],
                "type": "table",
                "confidence": 0.90,
            })

    # Flag document-wide low confidence if no clause numbers were detected at all
    if clause_headers_count == 0 and structured_chunks:
        logger.warning("No clause numbers detected in PDF. Flagging overall low confidence.")
        for chunk in structured_chunks:
            if chunk["type"] == "obligation":
                chunk["confidence"] = 0.50

    if not structured_chunks:
        logger.warning("Structured parser returned no chunks. Running legacy fallback.")
        return run_legacy_fallback(pdf_path)

    return structured_chunks


def run_legacy_fallback(pdf_path: str) -> list[dict]:
    """Helper to run the clean-and-split legacy code, returning uniform structures."""
    try:
        cleaned_text = extract_and_clean(pdf_path)
        clauses = split_into_clauses(cleaned_text)
    except Exception as exc:
        raise RuntimeError(f"Fallback parser failed: {exc}") from exc

    fallback_chunks = []
    for i, clause_text in enumerate(clauses):
        first_word = clause_text.split()[0] if clause_text.split() else ""
        clean_word = re.sub(r"[^0-9\.]", "", first_word)
        clause_num = ""
        if clean_word and (clean_word.endswith(".") or "." in clean_word):
            clause_num = clean_word.rstrip(".")

        parent_clause = ""
        if "." in clause_num:
            parent_clause = ".".join(clause_num.split(".")[:-1])

        fallback_chunks.append({
            "page": 1,
            "section": "General",
            "clause": clause_num,
            "parent": parent_clause,
            "text": clause_text,
            "type": "obligation",
            "confidence": 0.50,  # low confidence to trigger human review safely
        })
    return fallback_chunks
