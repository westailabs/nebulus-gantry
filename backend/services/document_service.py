"""
Document Service for managing the Knowledge Vault.

Provides:
- Collection CRUD operations
- Document upload, processing, and indexing
- Text extraction from PDF, DOCX, TXT, CSV
- Chunking and embedding into ChromaDB
- Semantic search across documents
"""
import csv
import io
import logging
import math
import os

from sqlalchemy.orm import Session as DBSession

from backend.models.collection import Collection
from backend.models.document import Document
from backend.services.chroma_pool import get_vector_client
from backend.services.keyword_boost import apply_boost, boost_settings

logger = logging.getLogger(__name__)


class RetrievalError(Exception):
    """Document search could not run (vector store unavailable or failed)."""


# Recommended CPA-demo floor (see .env.example and docs); what a blank or bad value falls back to.
DEFAULT_MIN_SOURCE_SIMILARITY = 0.42


def _min_similarity() -> float:
    """GANTRY_MIN_SOURCE_SIMILARITY in [0, 1], the minimum similarity for a cited source.

    - Variable not set at all: 0, the floor is off (plain Gantry, unchanged).
    - Set to blank/whitespace, unparseable or non-finite (a typo, an empty compose
      substitution): the floor is NOT silently dropped. Blank falls back to 0.42; an invalid
      or non-finite value logs a WARNING and also falls back to 0.42.
    - Explicit 0 (or any value that clamps to 0, e.g. -0.3): the floor is off, on purpose.
    - Any other valid number is clamped to [0, 1].
    """
    raw = os.getenv("GANTRY_MIN_SOURCE_SIMILARITY")
    if raw is None:
        return 0.0
    raw = raw.strip()
    if not raw:
        return DEFAULT_MIN_SOURCE_SIMILARITY
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid GANTRY_MIN_SOURCE_SIMILARITY=%r; using the default floor %.2f",
                       raw, DEFAULT_MIN_SOURCE_SIMILARITY)
        return DEFAULT_MIN_SOURCE_SIMILARITY
    if not math.isfinite(value):
        logger.warning("Non-finite GANTRY_MIN_SOURCE_SIMILARITY=%r; using the default floor %.2f",
                       raw, DEFAULT_MIN_SOURCE_SIMILARITY)
        return DEFAULT_MIN_SOURCE_SIMILARITY
    return min(max(value, 0.0), 1.0)


# Chunk settings: ~500 tokens ≈ 2000 chars, with 100 char overlap
CHUNK_SIZE = 2000
CHUNK_OVERLAP = 100
CSV_ROW_LIMIT = 10_000
CSV_ROWS_PER_CHUNK = 50


def extract_text_from_pdf(content: bytes) -> str:
    """Extract text from PDF content."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        text_parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
        return "\n\n".join(text_parts)
    except Exception as e:
        logger.error(f"Failed to extract text from PDF: {e}")
        raise ValueError(f"Failed to extract text from PDF: {e}")


def extract_text_from_docx(content: bytes) -> str:
    """Extract text from DOCX content."""
    try:
        from docx import Document as DocxDocument

        doc = DocxDocument(io.BytesIO(content))
        text_parts = []
        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text)
        return "\n\n".join(text_parts)
    except Exception as e:
        logger.error(f"Failed to extract text from DOCX: {e}")
        raise ValueError(f"Failed to extract text from DOCX: {e}")


def extract_text_from_txt(content: bytes) -> str:
    """Extract text from TXT/CSV content."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return content.decode("latin-1")
        except Exception as e:
            logger.error(f"Failed to decode text file: {e}")
            raise ValueError(f"Failed to decode text file: {e}")


def extract_text_from_csv(
    content: bytes,
) -> tuple[list[str], list[list[str]]]:
    """Extract structured data from CSV content.

    Args:
        content: Raw CSV file bytes.

    Returns:
        Tuple of (headers, data_rows).
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise ValueError("CSV file is empty")

    headers = rows[0]
    data_rows = rows[1:]

    if len(data_rows) > CSV_ROW_LIMIT:
        logger.warning(
            f"CSV has {len(data_rows)} rows, capping at {CSV_ROW_LIMIT}. "
            "Remaining rows will be ignored."
        )
        data_rows = data_rows[:CSV_ROW_LIMIT]

    return headers, data_rows


def chunk_csv(
    headers: list[str],
    rows: list[list[str]],
    rows_per_chunk: int = CSV_ROWS_PER_CHUNK,
) -> list[str]:
    """Chunk CSV data into text blocks with headers repeated in each chunk.

    Args:
        headers: Column header names.
        rows: Data rows (list of lists).
        rows_per_chunk: Number of data rows per chunk.

    Returns:
        List of text chunks, each starting with the header row.
    """
    if not rows:
        return [",".join(headers)]

    chunks = []
    header_line = ",".join(headers)
    for i in range(0, len(rows), rows_per_chunk):
        batch = rows[i: i + rows_per_chunk]
        lines = [header_line]
        for row in batch:
            lines.append(",".join(row))
        chunks.append("\n".join(lines))
    return chunks


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks."""
    if not text:
        return []

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        # Try to break at a sentence or paragraph boundary
        if end < len(text):
            # Look for paragraph break
            para_break = text.rfind("\n\n", start, end)
            if para_break > start + chunk_size // 2:
                end = para_break + 2
            else:
                # Look for sentence break
                sentence_break = text.rfind(". ", start, end)
                if sentence_break > start + chunk_size // 2:
                    end = sentence_break + 2

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # Move start with overlap
        start = end - overlap if end < len(text) else len(text)

    return chunks


class DocumentService:
    """Service for managing documents and collections in the Knowledge Vault."""

    def __init__(self, db: DBSession):
        self.db = db
        self._vector_client = get_vector_client()
        self._chroma_available = self._vector_client is not None
        if self._chroma_available:
            logger.info("DocumentService: ChromaDB connected")
        else:
            logger.warning("ChromaDB unavailable for documents")

    def _get_collection_name(self, user_id: int) -> str:
        """Get the ChromaDB collection name for a user's documents."""
        return f"user_{user_id}_documents"

    # ========== Collection CRUD ==========

    def create_collection(
        self, user_id: int, name: str, description: str | None = None
    ) -> Collection:
        """Create a new collection."""
        collection = Collection(
            user_id=user_id,
            name=name,
            description=description,
        )
        self.db.add(collection)
        self.db.commit()
        self.db.refresh(collection)
        return collection

    def list_collections(self, user_id: int) -> list[Collection]:
        """List all collections for a user."""
        return (
            self.db.query(Collection)
            .filter(Collection.user_id == user_id)
            .order_by(Collection.created_at.desc())
            .all()
        )

    def get_collection(self, collection_id: int, user_id: int) -> Collection | None:
        """Get a single collection by ID."""
        return (
            self.db.query(Collection)
            .filter(Collection.id == collection_id, Collection.user_id == user_id)
            .first()
        )

    def update_collection(
        self,
        collection_id: int,
        user_id: int,
        name: str | None = None,
        description: str | None = None,
    ) -> Collection | None:
        """Update a collection."""
        collection = self.get_collection(collection_id, user_id)
        if not collection:
            return None

        if name is not None:
            collection.name = name
        if description is not None:
            collection.description = description

        self.db.commit()
        self.db.refresh(collection)
        return collection

    def delete_collection(self, collection_id: int, user_id: int) -> bool:
        """Delete a collection and all its documents."""
        collection = self.get_collection(collection_id, user_id)
        if not collection:
            return False

        # Delete document chunks from ChromaDB
        if self._chroma_available and self._vector_client:
            collection_name = self._get_collection_name(user_id)
            for doc in collection.documents:
                try:
                    ids_to_delete = [
                        f"doc_{doc.id}_chunk_{i}" for i in range(doc.chunk_count)
                    ]
                    if ids_to_delete:
                        self._vector_client.delete_documents(
                            collection_name, ids=ids_to_delete
                        )
                except Exception as e:
                    logger.warning(f"Failed to delete document chunks from ChromaDB: {e}")

        self.db.delete(collection)
        self.db.commit()
        return True

    # ========== Document CRUD ==========

    def upload_document(
        self,
        user_id: int,
        filename: str,
        content: bytes,
        content_type: str,
        collection_id: int | None = None,
    ) -> Document:
        """Upload and process a document."""
        # Validate collection if provided
        if collection_id is not None:
            collection = self.get_collection(collection_id, user_id)
            if not collection:
                raise ValueError("Collection not found")

        # Create document record
        document = Document(
            user_id=user_id,
            collection_id=collection_id,
            filename=filename,
            content_type=content_type,
            file_size=len(content),
            status="processing",
        )
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)

        try:
            # Extract text and chunk based on content type
            if content_type == "csv":
                headers, data_rows = extract_text_from_csv(content)
                chunks = chunk_csv(headers, data_rows)
            elif content_type == "pdf":
                text = extract_text_from_pdf(content)
                if not text.strip():
                    raise ValueError(
                        "No text could be extracted from the document"
                    )
                chunks = chunk_text(text)
            elif content_type == "docx":
                text = extract_text_from_docx(content)
                if not text.strip():
                    raise ValueError(
                        "No text could be extracted from the document"
                    )
                chunks = chunk_text(text)
            elif content_type == "txt":
                text = extract_text_from_txt(content)
                if not text.strip():
                    raise ValueError(
                        "No text could be extracted from the document"
                    )
                chunks = chunk_text(text)
            else:
                raise ValueError(f"Unsupported content type: {content_type}")

            document.chunk_count = len(chunks)

            # Index chunks in ChromaDB
            if self._chroma_available and self._vector_client and chunks:
                collection_name = self._get_collection_name(user_id)
                ids = [f"doc_{document.id}_chunk_{i}" for i in range(len(chunks))]
                metadatas = [
                    {
                        "document_id": document.id,
                        "chunk_index": i,
                        "filename": filename,
                        "collection_id": collection_id or -1,
                    }
                    for i in range(len(chunks))
                ]
                self._vector_client.add_documents(
                    collection_name, ids=ids, documents=chunks, metadatas=metadatas
                )

            document.status = "ready"
            self.db.commit()
            self.db.refresh(document)

        except Exception as e:
            logger.error(f"Failed to process document: {e}")
            document.status = "failed"
            document.error_message = str(e)
            self.db.commit()
            self.db.refresh(document)

        return document

    def list_documents(
        self, user_id: int, collection_id: int | None = None
    ) -> list[Document]:
        """List documents for a user, optionally filtered by collection."""
        query = self.db.query(Document).filter(Document.user_id == user_id)
        if collection_id is not None:
            query = query.filter(Document.collection_id == collection_id)
        return query.order_by(Document.created_at.desc()).all()

    def get_document(self, document_id: int, user_id: int) -> Document | None:
        """Get a single document by ID."""
        return (
            self.db.query(Document)
            .filter(Document.id == document_id, Document.user_id == user_id)
            .first()
        )

    def delete_document(self, document_id: int, user_id: int) -> bool:
        """Delete a document and its chunks from ChromaDB."""
        document = self.get_document(document_id, user_id)
        if not document:
            return False

        # Delete chunks from ChromaDB
        if self._chroma_available and self._vector_client and document.chunk_count > 0:
            try:
                collection_name = self._get_collection_name(user_id)
                ids_to_delete = [
                    f"doc_{document_id}_chunk_{i}"
                    for i in range(document.chunk_count)
                ]
                self._vector_client.delete_documents(
                    collection_name, ids=ids_to_delete
                )
            except Exception as e:
                logger.warning(f"Failed to delete chunks from ChromaDB: {e}")

        self.db.delete(document)
        self.db.commit()
        return True

    # ========== Search ==========

    def search_documents(
        self,
        user_id: int,
        query: str,
        collection_ids: list[int] | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        """Search documents using semantic search (errors -> empty list)."""
        where = {"collection_id": {"$in": collection_ids}} if collection_ids else None
        try:
            return self._search(user_id, query, where, top_k)
        except RetrievalError as e:
            logger.error(f"Failed to search documents: {e}")
            return []

    def _search(self, user_id: int, query: str, where: dict | None, top_k: int) -> list[dict]:
        """Semantic search; raises RetrievalError if the vector store is unusable."""
        if not self._chroma_available or not self._vector_client:
            raise RetrievalError("vector store unavailable")
        try:
            results = self._vector_client.search(
                self._get_collection_name(user_id), query, n_results=top_k, where=where
            )
        except Exception as e:
            raise RetrievalError(f"vector search failed: {type(e).__name__}") from e

        formatted_results = []
        if results.get("documents") and results["documents"][0]:
            documents = results["documents"][0]
            distances = results["distances"][0] if results.get("distances") else [0] * len(documents)
            metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(documents)
            for i, doc in enumerate(documents):
                meta = (metadatas[i] if i < len(metadatas) else {}) or {}
                # Convert distance to similarity (lower distance = higher similarity)
                similarity = 1.0 / (1.0 + (distances[i] if i < len(distances) else 0))
                formatted_results.append({
                    "document_id": meta.get("document_id", 0),
                    "filename": meta.get("filename", "Unknown"),
                    "chunk_text": doc,
                    "similarity": similarity,
                    "chunk_index": meta.get("chunk_index", 0),
                })
        return formatted_results

    def retrieve_sources(
        self,
        user_id: int,
        query: str,
        document_scope: list[dict] | None = None,
        top_k: int = 3,
    ) -> list[dict]:
        """Retrieve the top document chunks for a query, honoring the scope.

        Args:
            user_id: The user ID
            query: The search query
            document_scope: Optional list of {"type": "document"|"collection", "id": int}
            top_k: Number of results to return

        Returns:
            List of result dicts (document_id, filename, chunk_text,
            similarity, chunk_index, dense_similarity, keyword_boost), best first.
            Hits below GANTRY_MIN_SOURCE_SIMILARITY or without a document_id are
            dropped. A bounded lexical boost may lift an exact-term near-miss
            above the floor; the floor itself is unchanged.

        Raises:
            RetrievalError: if the vector store is unavailable or the search fails.
        """
        collection_ids: list[int] = []
        document_ids: list[int] = []
        for scope in document_scope or []:
            if scope.get("type") == "collection":
                collection_ids.append(scope["id"])
            elif scope.get("type") == "document":
                document_ids.append(scope["id"])

        # Scope is enforced inside the vector search (collections OR documents).
        clauses = []
        if collection_ids:
            clauses.append({"collection_id": {"$in": collection_ids}})
        if document_ids:
            clauses.append({"document_id": {"$in": document_ids}})
        where = None if not clauses else clauses[0] if len(clauses) == 1 else {"$or": clauses}

        max_boost, window, min_score = boost_settings()
        # Over-fetch when a boost may promote a near-miss that is just outside
        # the raw top_k, then re-sort and truncate after the floor is applied.
        candidate_k = top_k if max_boost <= 0 else max(top_k * 3, top_k)
        results = self._search(user_id, query, where, candidate_k)
        floor = _min_similarity()
        boosted: list[dict] = []
        for r in results:
            item = dict(r)
            try:
                dense = float(item.get("similarity", 0.0))
            except (TypeError, ValueError):
                dense = 0.0
            if not math.isfinite(dense):
                dense = 0.0
            dense = min(max(dense, 0.0), 1.0)
            similarity, boost = apply_boost(
                query,
                item.get("chunk_text") or "",
                dense,
                floor,
                filename=item.get("filename") or "",
                max_boost=max_boost,
                window=window,
                min_score=min_score,
            )
            item["dense_similarity"] = dense
            item["keyword_boost"] = boost
            item["similarity"] = similarity
            if item.get("document_id") and similarity >= floor:
                boosted.append(item)
        boosted.sort(key=lambda h: h["similarity"], reverse=True)
        return boosted[:top_k]

    def build_rag_context(
        self,
        user_id: int,
        query: str,
        document_scope: list[dict] | None = None,
        top_k: int = 3,
    ) -> str:
        """Build RAG context (legacy string form) from document search results."""
        try:
            results = self.retrieve_sources(user_id, query, document_scope, top_k)
        except RetrievalError as e:
            logger.error(f"RAG retrieval failed: {e}")
            return ""
        return format_sources_context(results)

    def get_chunk_text(self, user_id: int, document_id: int, chunk_index: int) -> str | None:
        """Return the stored text of one chunk, or None if unavailable."""
        if not self._chroma_available or not self._vector_client:
            return None
        try:
            collection = self._vector_client.get_or_create_collection(
                self._get_collection_name(user_id)
            )
            res = collection.get(ids=[f"doc_{document_id}_chunk_{chunk_index}"])
            docs = res.get("documents") or []
            return docs[0] if docs else None
        except Exception as e:
            logger.warning(f"Failed to fetch chunk {document_id}/{chunk_index}: {e}")
            return None


def sources_to_citations(results: list[dict], snippet_chars: int = 240) -> list[dict]:
    """Convert retrieval results into numbered, client-safe citation dicts."""
    return [
        {
            "n": i + 1,
            "document_id": r["document_id"],
            "filename": r["filename"],
            "chunk_index": r["chunk_index"],
            "similarity": round(float(r.get("similarity", 0.0)), 4),
            "snippet": (r.get("chunk_text") or "")[:snippet_chars],
        }
        for i, r in enumerate(results)
    ]


def format_sources_context(results: list[dict], chunk_chars: int = 1500) -> str:
    """Format retrieved chunks as numbered sources for the system prompt."""
    if not results:
        return ""
    parts = [
        "Answer ONLY from the numbered sources below. Cite every fact with its "
        "source number in square brackets, e.g. [1]. If the sources do not "
        "contain the answer, say you could not find it in the documents.",
        "",
        "Sources:",
    ]
    for i, r in enumerate(results):
        parts.append(
            f"[{i + 1}] {r['filename']} (chunk {r['chunk_index'] + 1}):\n"
            f"{(r.get('chunk_text') or '')[:chunk_chars]}"
        )
    return "\n".join(parts)
