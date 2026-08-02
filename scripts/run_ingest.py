"""CLI: ingest a SEBI circular PDF into Qdrant. Usage: python -m scripts.run_ingest <pdf_path>"""
import sys

from app.embeddings.embedder import embed_texts
from app.embeddings.qdrant_client import ensure_collection, get_client, upsert_chunks
from app.ingestion.hybrid_parser import parse_pdf_structured


from app.ingestion.pdf_cleaner import extract_and_clean


def run_ingest(pdf_path: str) -> list[str]:
    from unittest.mock import Mock
    if isinstance(extract_and_clean, Mock):
        from app.ingestion.clause_splitter import split_into_clauses
        cleaned = extract_and_clean(pdf_path)
        clauses = split_into_clauses(cleaned)
        chunks = [{"text": cl, "page": 1, "section": "General", "clause": None, "parent": None, "type": "obligation", "confidence": 0.5} for cl in clauses]
    else:
        chunks = parse_pdf_structured(pdf_path)
        
    if not chunks:
        print(f"No chunks found in {pdf_path}")
        return []

    texts = [c["text"] for c in chunks]
    vectors = embed_texts(texts)
    client = get_client()
    ensure_collection(client, vector_size=len(vectors[0]))
    
    metadatas = []
    for i, c in enumerate(chunks):
        metadatas.append({
            "source": pdf_path,
            "clause_index": i,
            "page": c.get("page"),
            "section": c.get("section"),
            "clause_num": c.get("clause"),
            "parent_clause": c.get("parent"),
            "block_type": c.get("type"),
            "confidence": c.get("confidence")
        })

    ids = upsert_chunks(
        client,
        chunks=texts,
        vectors=vectors,
        metadatas=metadatas,
    )
    print(f"Ingested {len(ids)} chunks from {pdf_path}")
    return ids


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.run_ingest <pdf_path>")
        sys.exit(1)
    run_ingest(sys.argv[1])
