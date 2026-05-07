"""
seed.py — Index documents into ChromaDB for Vantage Chat RAG pipeline.

Usage:
  # Index a directory of PDFs
  python seed.py --dir ./docs --device-class hvac --type manual

  # Index a directory of markdown/text runbooks
  python seed.py --dir ./docs/runbooks --device-class network --type runbook

  # Index a fault history CSV
  python seed.py --file fault_history.csv --type fault_action

  # Index a single PDF
  python seed.py --file HVAC_AHU_Series7_Manual.pdf --device-class hvac --type manual

  # List current collection stats
  python seed.py --stats

CSV format for --type fault_action:
  Columns: entity_id, device_class, question, resolution, ts
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Allow running from repo root or knowledge_base/ directory
sys.path.insert(0, str(Path(__file__).parent.parent / "fastapi"))

from config import settings  # noqa: E402

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
SUPPORTED_PDF = {".pdf"}
SUPPORTED_TEXT = {".txt", ".md", ".rst"}

splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
)


# ── ChromaDB connection ───────────────────────────────────────────────────────

def get_collection() -> chromadb.Collection:
    client = chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
    )
    # Use default embedding function (sentence-transformers/all-MiniLM-L6-v2)
    # which runs locally without any API key
    return client.get_or_create_collection(
        name=settings.chroma_collection,
        metadata={"hnsw:space": "cosine"},
    )


# ── Extraction helpers ────────────────────────────────────────────────────────

def extract_pdf(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text.strip())
    return "\n\n".join(pages)


def extract_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def chunk_text(text: str) -> list[str]:
    return splitter.split_text(text)


# ── Indexing functions ────────────────────────────────────────────────────────

def index_file(
    path: Path,
    device_class: str,
    document_type: str,
    collection: chromadb.Collection,
) -> int:
    suffix = path.suffix.lower()

    if suffix in SUPPORTED_PDF:
        raw = extract_pdf(path)
    elif suffix in SUPPORTED_TEXT:
        raw = extract_text(path)
    else:
        print(f"  [skip] Unsupported file type: {path.name}")
        return 0

    chunks = chunk_text(raw)
    if not chunks:
        print(f"  [skip] No text extracted from: {path.name}")
        return 0

    ids, documents, metadatas = [], [], []
    for i, chunk in enumerate(chunks):
        chunk_id = f"{path.stem}_{i}"
        ids.append(chunk_id)
        documents.append(chunk)
        metadatas.append({
            "source": path.name,
            "document_type": document_type,
            "device_class": device_class,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        })

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return len(chunks)


def index_fault_csv(path: Path, collection: chromadb.Collection) -> int:
    """
    CSV columns: entity_id, device_class, question, resolution, ts
    Each row becomes one fault_action document.
    """
    total = 0
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        ids, documents, metadatas = [], [], []

        for i, row in enumerate(reader):
            entity_id = row.get("entity_id", "").strip()
            device_class = row.get("device_class", "general").strip()
            question = row.get("question", "").strip()
            resolution = row.get("resolution", "").strip()
            ts = row.get("ts", datetime.now(timezone.utc).isoformat()).strip()

            if not question or not resolution:
                continue

            content = f"Fault question: {question}\n\nResolution: {resolution}"
            ids.append(f"fault_{i}_{entity_id or 'unknown'}")
            documents.append(content)
            metadatas.append({
                "source": path.name,
                "document_type": "fault_action",
                "device_class": device_class,
                "entity_id": entity_id,
                "indexed_at": ts,
            })
            total += 1

        if ids:
            collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    return total


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed ChromaDB knowledge base for Vantage Chat"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dir", help="Directory of files to index")
    group.add_argument("--file", help="Single file to index")
    parser.add_argument(
        "--device-class",
        default="general",
        help="Device class filter: hvac | energy | network | infra | general",
    )
    parser.add_argument(
        "--type",
        dest="doc_type",
        default="manual",
        choices=["manual", "runbook", "fault_action", "topology"],
        help="Document type label",
    )
    parser.add_argument("--stats", action="store_true", help="Print collection stats and exit")
    args = parser.parse_args()

    print(f"[chroma] Connecting to {settings.chroma_host}:{settings.chroma_port} ...")
    collection = get_collection()

    if args.stats:
        count = collection.count()
        print(f"[stats] Collection '{settings.chroma_collection}': {count} documents")
        return

    if not args.dir and not args.file:
        parser.error("One of --dir, --file, or --stats is required.")

    files: list[Path] = []

    if args.file:
        p = Path(args.file)
        if not p.exists():
            print(f"ERROR: File not found: {p}")
            sys.exit(1)
        files = [p]

    elif args.dir:
        d = Path(args.dir)
        if not d.is_dir():
            print(f"ERROR: Not a directory: {d}")
            sys.exit(1)
        files = [
            f for f in d.iterdir()
            if f.is_file() and f.suffix.lower() in SUPPORTED_PDF | SUPPORTED_TEXT | {".csv"}
        ]
        if not files:
            print(f"No supported files found in {d}")
            sys.exit(0)

    total_chunks = 0
    total_files = 0

    for path in sorted(files):
        print(f"  [{path.name}] indexing ...", end=" ", flush=True)

        if path.suffix.lower() == ".csv" and args.doc_type == "fault_action":
            n = index_fault_csv(path, collection)
        else:
            n = index_file(path, args.device_class, args.doc_type, collection)

        print(f"{n} chunks")
        total_chunks += n
        total_files += 1

    final_count = collection.count()
    print(
        f"\n[done] {total_files} file(s) processed, "
        f"{total_chunks} chunks added. "
        f"Total documents in collection: {final_count}"
    )


if __name__ == "__main__":
    main()
