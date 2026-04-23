import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "onboarding.db"
DOCS_DIR = BASE_DIR / "data" / "training_docs"
CHROMA_DIR = BASE_DIR / "data" / "chroma_db"
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"

# Scheduler Rules
WORK_START_HOUR = 8  # 8 AM
WORK_END_HOUR = 17   # 5 PM
LOCAL_TIMEZONE = "America/New_York"

# Hugging Face API configuration
def _load_hf_token() -> str:
    token = os.getenv("HF_TOKEN")
    if token:
        return token
    try:
        import streamlit as st

        return st.secrets["HF_TOKEN"]
    except Exception:
        return ""


HF_TOKEN = _load_hf_token()
HF_API_TIMEOUT = int(os.getenv("HF_API_TIMEOUT", "90"))

# Hosted model configuration
AGENT_LLM_MODEL = "meta-llama/Llama-3.1-8B-Instruct"
LLM_MODEL = AGENT_LLM_MODEL  # Backwards compatibility for existing imports
RAG_LLM_MODEL = os.getenv("HF_RAG_MODEL", AGENT_LLM_MODEL)
EMBEDDING_MODEL = os.getenv("HF_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
DOCUMENT_QA_TEXT_MODEL = os.getenv("HF_DOCUMENT_QA_TEXT_MODEL", AGENT_LLM_MODEL)
VISION_MODEL = "llava-hf/llava-1.5-7b-hf"
DOCUMENT_QA_MAX_CONTEXT_CHARS = 50000
POLICY_NOT_FOUND_RESPONSE = "Information not found in company documentation."
