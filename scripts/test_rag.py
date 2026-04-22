import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from config.settings import EMBEDDING_MODEL, RAG_LLM_MODEL, RERANK_MODEL
from src.core.RAG import get_policy_rag_service


def main() -> None:
    try:
        service = get_policy_rag_service()
    except RuntimeError as exc:
        print(exc)
        return

    print("\n" + "=" * 40)
    print(f"READY | LLM={RAG_LLM_MODEL} | Embeddings={EMBEDDING_MODEL}")
    print(f"Reranker={RERANK_MODEL}")
    print("=" * 40)

    while True:
        query = input("\nQuestion: ").strip()
        if query.lower() in {"exit", "quit"}:
            break

        response = service.answer(query)
        print(f"\nAI:\n{response.answer_text}")
        if response.sources:
            print("\n--- Sources Used (reranked) ---")
            for index, source in enumerate(response.sources, start=1):
                print(f"{index}. {source}")


if __name__ == "__main__":
    main()
