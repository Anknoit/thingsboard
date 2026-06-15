"""
rag.py — LangChain RAG pipeline backed by ChromaDB.

Retrieves device-class-filtered knowledge base documents to ground LLM responses
in real manuals, runbooks, and historical fault resolutions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import chromadb
from chromadb.utils import embedding_functions
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings

logger = logging.getLogger(__name__)

# Document types stored in Chroma metadata
DOC_TYPES = {"manual", "runbook", "fault_action", "topology"}

# Number of documents to retrieve per query
DEFAULT_K = 5


def _get_chroma_client() -> chromadb.HttpClient:
    return chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        tenant=chromadb.DEFAULT_TENANT,
        database=chromadb.DEFAULT_DATABASE,
    )


def _get_embedding_function() -> Any:
    """
    Returns the embedding function for ChromaDB.
    Uses the provider from LLM adapter when available; falls back to
    ChromaDB's default (sentence-transformers/all-MiniLM-L6-v2).
    """
    try:
        from services.llm_adapter import get_llm_adapter

        adapter = get_llm_adapter()

        # Wrap the adapter's embed() as a ChromaDB-compatible embedding function
        class AdapterEmbedFn(embedding_functions.EmbeddingFunction):
            def __call__(self, input: list[str]) -> list[list[float]]:
                import asyncio
                loop = asyncio.get_event_loop()
                return [loop.run_until_complete(adapter.embed(text)) for text in input]

        return AdapterEmbedFn()
    except Exception:
        # Fall back to local sentence-transformers (no API key required)
        logger.info("RAG: using default ChromaDB embedding function")
        return embedding_functions.DefaultEmbeddingFunction()


class RAGPipeline:
    def __init__(self) -> None:
        self._client = _get_chroma_client()
        self._embed_fn = _get_embedding_function()
        self._collection_name = settings.chroma_collection
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def _get_store(self) -> Chroma:
        return Chroma(
            client=self._client,
            collection_name=self._collection_name,
            embedding_function=self._embed_fn,
        )

    def retrieve_context(
        self,
        query: str,
        device_class: str | None = None,
        document_type: str | None = None,
        k: int = DEFAULT_K,
    ) -> list[Document]:
        """
        Retrieve top-k documents by cosine similarity, optionally filtered
        by device_class and/or document_type metadata fields.
        """
        try:
            store = self._get_store()

            where: dict = {}
            if device_class and document_type:
                where = {
                    "$and": [
                        {"device_class": {"$eq": device_class}},
                        {"document_type": {"$eq": document_type}},
                    ]
                }
            elif device_class:
                where = {"device_class": {"$eq": device_class}}
            elif document_type:
                where = {"document_type": {"$eq": document_type}}

            retriever = store.as_retriever(
                search_type="similarity",
                search_kwargs={"k": k, **({"filter": where} if where else {})},
            )
            docs = retriever.invoke(query)
            logger.debug(
                "RAG retrieved %d docs for query=%r device_class=%s",
                len(docs),
                query[:60],
                device_class,
            )
            return docs
        except Exception as exc:
            logger.warning("RAG retrieval failed: %s — returning empty context", exc)
            return []

    def format_rag_context(self, documents: list[Document]) -> str:
        """
        Format retrieved docs as numbered source sections for prompt injection.
        """
        if not documents:
            return "No relevant documentation found in the knowledge base."

        sections: list[str] = []
        for i, doc in enumerate(documents, 1):
            source = doc.metadata.get("source", "unknown")
            doc_type = doc.metadata.get("document_type", "document")
            device_class = doc.metadata.get("device_class", "general")
            sections.append(
                f"[{i}] ({doc_type.upper()} — {device_class} — {source})\n"
                f"{doc.page_content.strip()}"
            )

        return "\n\n".join(sections)

    def add_fault_resolution(
        self,
        entity_id: str,
        question: str,
        resolution: str,
        device_class: str,
    ) -> None:
        """
        Index a resolved fault Q&A pair back into Chroma so future queries
        can retrieve it as a fault_action document.
        """
        try:
            store = self._get_store()
            doc = Document(
                page_content=f"Question: {question}\n\nResolution: {resolution}",
                metadata={
                    "source": f"fault_history:{entity_id}",
                    "document_type": "fault_action",
                    "device_class": device_class,
                    "entity_id": entity_id,
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            store.add_documents([doc])
            logger.info(
                "RAG: indexed fault resolution for entity=%s device_class=%s",
                entity_id,
                device_class,
            )
        except Exception as exc:
            logger.warning("RAG: failed to index fault resolution: %s", exc)

    def add_documents_from_text(
        self,
        text: str,
        source: str,
        document_type: str,
        device_class: str,
        extra_metadata: dict | None = None,
    ) -> int:
        """
        Chunk raw text and add all chunks to ChromaDB.
        Returns the number of chunks added.
        """
        chunks = self._splitter.split_text(text)
        docs = [
            Document(
                page_content=chunk,
                metadata={
                    "source": source,
                    "document_type": document_type,
                    "device_class": device_class,
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                    **(extra_metadata or {}),
                },
            )
            for chunk in chunks
        ]
        store = self._get_store()
        store.add_documents(docs)
        return len(docs)

    def collection_count(self) -> int:
        try:
            col = self._client.get_or_create_collection(self._collection_name)
            return col.count()
        except Exception:
            return -1


# ── Module-level singleton ─────────────────────────────────────────────────────

_pipeline: RAGPipeline | None = None


def get_rag_pipeline() -> RAGPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = RAGPipeline()
    return _pipeline
