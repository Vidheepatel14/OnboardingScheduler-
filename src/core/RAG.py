import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import numpy as np
from huggingface_hub import InferenceClient

from config.settings import (
    CHROMA_DIR,
    DOCS_DIR,
    EMBEDDING_MODEL,
    HF_TOKEN,
    POLICY_NOT_FOUND_RESPONSE,
    RAG_LLM_MODEL,
    RERANK_MODEL,
)

try:
    from langchain_community.document_loaders import DirectoryLoader, PyMuPDFLoader
    from langchain_community.retrievers import BM25Retriever
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    import rank_bm25  # noqa: F401
    from sentence_transformers import CrossEncoder, SentenceTransformer
except ImportError as exc:
    DirectoryLoader = None
    PyMuPDFLoader = None
    BM25Retriever = None
    Chroma = None
    Document = Any
    RecursiveCharacterTextSplitter = None
    CrossEncoder = None
    SentenceTransformer = None
    RAG_IMPORT_ERROR = exc
else:
    RAG_IMPORT_ERROR = None

RAG_DEPENDENCY_ERROR = (
    "RAG dependencies are missing. Install the packages in "
    "OnboardingScheduler/requirements.txt before using `search_policy`."
)

_HF_CLIENT: InferenceClient | None = None


def _hf_client() -> InferenceClient:
    global _HF_CLIENT
    if _HF_CLIENT is None:
        _HF_CLIENT = InferenceClient(token=HF_TOKEN)
    return _HF_CLIENT


def _response_text(response) -> str:
    try:
        return response.choices[0].message.content or ""
    except AttributeError:
        return response["choices"][0]["message"].get("content", "")


def _chat_text(messages: list[dict[str, Any]]) -> str:
    response = _hf_client().chat_completion(
        model=RAG_LLM_MODEL,
        messages=messages,
        max_tokens=700,
        temperature=0.1,
    )
    return _response_text(response).strip()


def _embedding_vector(raw: Any) -> list[float]:
    values = np.asarray(raw, dtype="float32")
    if values.ndim == 3:
        values = values[0]
    if values.ndim == 2:
        values = values[0] if values.shape[0] == 1 else values.mean(axis=0)
    if values.ndim != 1:
        values = values.reshape(-1)
    return values.astype("float32").tolist()


class HFApiEmbeddings:
    def __init__(self, model: str):
        _require_rag_dependencies()
        self.model_name = model
        self._model = SentenceTransformer(model)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts),
            batch_size=32,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=False,
        )
        return [vec.astype("float32").tolist() for vec in vectors]

    def embed_query(self, text: str) -> list[float]:
        vector = self._model.encode(
            text,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=False,
        )
        return vector.astype("float32").tolist()

MAX_VECTORSTORE_REBUILD_ATTEMPTS = 2
RERANK_TOP_N = 8
VECTOR_FETCH_K = 80
VECTOR_K = 25
BM25_K = 25
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120
KEYWORD_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "by",
    "do",
    "for",
    "i",
    "if",
    "in",
    "is",
    "it",
    "me",
    "my",
    "need",
    "of",
    "on",
    "or",
    "prior",
    "the",
    "their",
    "to",
    "we",
    "would",
    "you",
    "your",
}

_RAG_SERVICE = None
MANIFEST_FILE = "docs_manifest.json"
LEGACY_NOT_FOUND_RESPONSES = {
    "Not found in provided context.",
    POLICY_NOT_FOUND_RESPONSE,
}
NOT_FOUND_PATTERNS = (
    r"information not found in (?:company )?documentation",
    r"not found in provided context",
    r"document provided does not contain (?:any )?information",
    r"does not contain (?:any )?information about",
    r"no information (?:about|regarding) .* (?:in|from) the (?:document|context)",
    r"the (?:document|context) does not mention",
)


@dataclass
class RAGResponse:
    answer_text: str
    sources: list[str]

    def as_tool_output(self) -> str:
        if self.answer_text.strip() == POLICY_NOT_FOUND_RESPONSE:
            return POLICY_NOT_FOUND_RESPONSE
        if not self.sources:
            return self.answer_text
        source_lines = "\n".join(f"- {source}" for source in self.sources)
        return f"{self.answer_text}\nSources:\n{source_lines}"


def _require_rag_dependencies() -> None:
    if RAG_IMPORT_ERROR is not None:
        raise RuntimeError(RAG_DEPENDENCY_ERROR) from RAG_IMPORT_ERROR


def stable_doc_id(doc: Document) -> str:
    src = doc.metadata.get("source", "")
    page = str(doc.metadata.get("page", ""))
    text = (doc.page_content or "").strip()
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()
    return f"{src}::p{page}::{digest}"


def expand_query(query: str) -> list[str]:
    base = query.strip()
    lowered = base.lower()
    expansions = [base]

    if "pto" not in lowered and "paid time off" not in lowered:
        expansions.append(f"{base} policy")
        expansions.append(f"{base} handbook")

    if "misconduct" in lowered or "ethics" in lowered or "report" in lowered:
        expansions.extend(
            [
                f"{base} reporting channels",
                f"{base} ethicsline",
                f"{base} employee relations",
            ]
        )

    if "pto" in lowered or "paid time off" in lowered or "vacation" in lowered or "leave" in lowered:
        expansions.extend(
            [
                f"{base} paid time off",
                f"{base} accrual",
                f"{base} hours",
            ]
        )

    if "photo" in lowered or "badge" in lowered or "security access card" in lowered:
        expansions.extend(
            [
                f"{base} first day",
                f"{base} security access card",
                f"{base} photo requirements",
            ]
        )

    if "customer care center" in lowered:
        expansions.extend(
            [
                "customer care center photo first day",
                "customer care center security access card",
                "customer care center do not need to submit photo prior to first day",
            ]
        )

    seen = set()
    unique_expansions = []
    for item in expansions:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_expansions.append(normalized)
    return unique_expansions


def build_generation_prompt(query: str, docs: list[Document]) -> str:
    context_blocks = []
    for doc in docs:
        context_blocks.append(
            "Source: {filename}\nPage: {page_label}\nContent:\n{content}".format(
                filename=doc.metadata.get("filename", "Unknown File"),
                page_label=doc.metadata.get("page_label", "Unknown"),
                content=doc.page_content,
            )
        )

    return (
        "You are the AI Onboarding Concierge for new employees.\n"
        "Answer ONLY using the provided CONTEXT.\n"
        "If the answer is missing, say exactly:\n"
        f"{POLICY_NOT_FOUND_RESPONSE}\n"
        "Keep the answer professional and grounded in the context.\n"
        "If the question asks for a list, reporting channels, steps, requirements, phone numbers, URLs, or thresholds, "
        "provide the complete list from the context and preserve important details.\n"
        "If the context contains both a general rule and a specific exception, apply the specific exception when it matches the user's role, group, location, or program.\n"
        "Do not omit contact details or compress enumerated items into a short summary.\n"
        "Do not invent or summarize citations. Source labels are added automatically.\n\n"
        "If the answer is present, output exactly:\n"
        "Answer: <complete answer from context. Use bullets when the source is a list.>\n"
        "Quote: <supporting quote, <=25 words>\n\n"
        "CONTEXT:\n"
        f"{chr(10).join(context_blocks)}\n\n"
        f"Question: {query}"
    )


def extract_query_keywords(query: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    return [
        token
        for token in tokens
        if len(token) >= 4 and token not in KEYWORD_STOPWORDS
    ]


def lexical_overlap_score(query: str, doc: Document) -> int:
    text = f"{doc.metadata.get('filename', '')} {doc.page_content or ''}".lower()
    keyword_hits = sum(1 for keyword in extract_query_keywords(query) if keyword in text)

    phrase_hits = 0
    lowered_query = query.lower()
    for phrase in (
        "customer care center",
        "first day",
        "security access card",
        "reporting channels",
        "employee relations",
        "ethicsline",
    ):
        if phrase in lowered_query and phrase in text:
            phrase_hits += 2

    return keyword_hits + phrase_hits


def normalize_answer_text(answer_text: str) -> str:
    cleaned = answer_text.strip()
    if cleaned in LEGACY_NOT_FOUND_RESPONSES:
        return POLICY_NOT_FOUND_RESPONSE
    lowered = re.sub(r"\s+", " ", cleaned.lower())
    if any(re.search(pattern, lowered) for pattern in NOT_FOUND_PATTERNS):
        return POLICY_NOT_FOUND_RESPONSE
    cleaned = re.sub(r"\s*\bQuote:\s*", "\n\nQuote: ", cleaned)
    return cleaned.strip()


def _load_pdfs_with_labels(docs_dir: Path) -> list[Document]:
    import fitz

    pages: list[Document] = []
    for pdf_path in sorted(docs_dir.glob("*.pdf")):
        try:
            pdf = fitz.open(str(pdf_path))
        except Exception as exc:
            print(f"   ❌ Failed to open {pdf_path.name}: {exc}")
            continue

        for page_index, page in enumerate(pdf):
            try:
                text = page.get_text("text") or ""
            except Exception:
                text = ""
            printed_label = ""
            try:
                printed_label = page.get_label() or ""
            except Exception:
                printed_label = ""
            page_label = printed_label.strip() or str(page_index + 1)

            pages.append(
                Document(
                    page_content=text,
                    metadata={
                        "source": str(pdf_path),
                        "file_path": str(pdf_path),
                        "filename": pdf_path.name,
                        "page": page_index,
                        "page_label": page_label,
                        "total_pages": pdf.page_count,
                    },
                )
            )
        pdf.close()
    return pages


def load_or_create_vectorstore(embeddings) -> tuple[Any, list[Document]]:
    _require_rag_dependencies()
    persist_directory = str(CHROMA_DIR)
    docs_directory = str(DOCS_DIR)
    current_manifest = build_docs_manifest()

    for attempt in range(MAX_VECTORSTORE_REBUILD_ATTEMPTS + 1):
        if CHROMA_DIR.exists():
            if docs_manifest_has_changed(current_manifest):
                if attempt >= MAX_VECTORSTORE_REBUILD_ATTEMPTS:
                    raise RuntimeError(
                        "Training documents still appear changed after rebuilding the vector database."
                    )
                print("--- Training documents changed. Rebuilding vector database... ---")
                shutil.rmtree(CHROMA_DIR, ignore_errors=True)
                if CHROMA_DIR.exists():
                    raise RuntimeError(f"Could not remove existing vector database at {CHROMA_DIR}.")
                continue

            print("--- Found existing database. Loading vectors... ---")
            vectorstore = Chroma(persist_directory=persist_directory, embedding_function=embeddings)

            store = vectorstore.get(include=["documents", "metadatas"])
            docs = [
                Document(page_content=text or "", metadata=(metadata or {}))
                for text, metadata in zip(store.get("documents", []), store.get("metadatas", []))
            ]

            if not docs:
                if attempt >= MAX_VECTORSTORE_REBUILD_ATTEMPTS:
                    raise RuntimeError(
                        "Vector database is empty even after rebuilding. Delete the Chroma directory manually and retry."
                    )
                print("Database found but empty. Wiping and re-indexing...")
                shutil.rmtree(CHROMA_DIR, ignore_errors=True)
                if CHROMA_DIR.exists():
                    raise RuntimeError(f"Could not remove empty vector database at {CHROMA_DIR}.")
                continue

            return vectorstore, docs

        print("--- No database found. Indexing PDFs... ---")
        pages = _load_pdfs_with_labels(DOCS_DIR)
        print(f"Loaded {len(pages)} pages.")

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
        chunks = splitter.split_documents(pages)

        for chunk in chunks:
            source = chunk.metadata.get("source", "")
            chunk.metadata["filename"] = Path(source).name if source else "Unknown File"

        vectorstore = Chroma.from_documents(
            documents=chunks,
            embedding=embeddings,
            persist_directory=persist_directory,
        )
        save_docs_manifest(current_manifest)
        return vectorstore, chunks

    raise RuntimeError("Unable to initialize the vector database.")


def build_docs_manifest() -> dict[str, Any]:
    docs = []
    for pdf_path in sorted(DOCS_DIR.glob("*.pdf")):
        stat = pdf_path.stat()
        sha256 = hashlib.sha256()
        with pdf_path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                sha256.update(block)
        docs.append(
            {
                "name": pdf_path.name,
                "size": int(stat.st_size),
                "sha256": sha256.hexdigest(),
            }
        )
    return {"embedding_model": EMBEDDING_MODEL, "docs": docs}


def load_docs_manifest() -> dict[str, Any] | None:
    manifest_path = CHROMA_DIR / MANIFEST_FILE
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text())
    except Exception:
        return None


def save_docs_manifest(manifest: dict[str, Any]) -> None:
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = CHROMA_DIR / MANIFEST_FILE
    manifest_path.write_text(json.dumps(manifest, indent=2))


def docs_manifest_has_changed(current_manifest: dict[str, Any]) -> bool:
    saved_manifest = load_docs_manifest()
    if saved_manifest is None:
        return True
    return saved_manifest != current_manifest


class CrossEncoderReranker:
    def __init__(self, model_name: str):
        _require_rag_dependencies()
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, docs: list[Document], top_n: int) -> list[Document]:
        if not docs:
            return []

        pairs = [(query, (doc.page_content or "")[:1800]) for doc in docs]
        scores = self.model.predict(pairs)

        scored_docs = list(zip(docs, scores))
        scored_docs.sort(
            key=lambda item: float(item[1]) + (0.25 * lexical_overlap_score(query, item[0])),
            reverse=True,
        )

        top_docs = []
        for doc, score in scored_docs[:top_n]:
            doc.metadata["rerank_score"] = float(score)
            doc.metadata["keyword_overlap"] = lexical_overlap_score(query, doc)
            top_docs.append(doc)

        return top_docs


def hybrid_multiquery_retrieve(query: str, bm25, vectorstore) -> list[Document]:
    vector_retriever = vectorstore.as_retriever(
        search_type="mmr",
        search_kwargs={"fetch_k": VECTOR_FETCH_K, "k": VECTOR_K, "lambda_mult": 0.6},
    )

    all_docs: list[Document] = []
    for expanded_query in expand_query(query):
        try:
            all_docs.extend(bm25.get_relevant_documents(expanded_query))
        except Exception:
            all_docs.extend(bm25.invoke(expanded_query))

        try:
            all_docs.extend(vector_retriever.get_relevant_documents(expanded_query))
        except Exception:
            all_docs.extend(vector_retriever.invoke(expanded_query))

    unique_docs = {}
    for doc in all_docs:
        key = stable_doc_id(doc)
        if key in unique_docs:
            continue
        source = doc.metadata.get("source", "")
        doc.metadata.setdefault("filename", Path(source).name if source else "Unknown File")
        unique_docs[key] = doc

    return list(unique_docs.values())


def hybrid_multiqueue_retrieve(query: str, bm25, vectorstore) -> list[Document]:
    return hybrid_multiquery_retrieve(query, bm25, vectorstore)


def summarize_sources(docs: list[Document], max_sources: int = 5) -> list[str]:
    seen = set()
    sources = []

    for doc in docs[:max_sources]:
        filename = doc.metadata.get("filename", "Unknown File")
        label_value = doc.metadata.get("page_label")
        if not label_value:
            page = doc.metadata.get("page", 0)
            label_value = page + 1 if isinstance(page, int) else page
        label = f"{filename} (Page {label_value})"
        if label in seen:
            continue
        seen.add(label)
        sources.append(label)

    return sources


def prepare_docs_for_prompt(docs: list[Document]) -> list[Document]:
    prepared_docs = []
    for doc in docs:
        metadata = dict(doc.metadata or {})
        source = metadata.get("source", "")
        metadata.setdefault("filename", Path(source).name if source else "Unknown File")
        if not metadata.get("page_label"):
            page = metadata.get("page", 0)
            metadata["page_label"] = page + 1 if isinstance(page, int) else page
        prepared_docs.append(Document(page_content=doc.page_content, metadata=metadata))
    return prepared_docs


class PolicyRAGService:
    def __init__(self):
        _require_rag_dependencies()
        embeddings = HFApiEmbeddings(model=EMBEDDING_MODEL)
        self.vectorstore, docs_for_bm25 = load_or_create_vectorstore(embeddings)
        self.bm25 = BM25Retriever.from_documents(docs_for_bm25)
        self.bm25.k = BM25_K
        self.reranker = CrossEncoderReranker(RERANK_MODEL)

    def answer(self, query: str) -> RAGResponse:
        clean_query = query.strip()
        if not clean_query:
            return RAGResponse(POLICY_NOT_FOUND_RESPONSE, [])

        candidates = hybrid_multiquery_retrieve(clean_query, self.bm25, self.vectorstore)
        top_docs = self.reranker.rerank(clean_query, candidates, top_n=RERANK_TOP_N)
        if not top_docs:
            return RAGResponse(POLICY_NOT_FOUND_RESPONSE, [])

        prompt_docs = prepare_docs_for_prompt(top_docs)
        prompt = build_generation_prompt(clean_query, prompt_docs)
        answer_text = _chat_text([{"role": "user", "content": prompt}])
        answer_text = normalize_answer_text(answer_text)
        if answer_text == POLICY_NOT_FOUND_RESPONSE:
            return RAGResponse(answer_text=answer_text, sources=[])
        return RAGResponse(answer_text=answer_text, sources=summarize_sources(top_docs))


def get_policy_rag_service() -> PolicyRAGService:
    global _RAG_SERVICE
    if _RAG_SERVICE is None:
        _RAG_SERVICE = PolicyRAGService()
    return _RAG_SERVICE


def answer_policy_with_rag(query: str) -> str:
    response = get_policy_rag_service().answer(query)
    return response.as_tool_output()
