from src.database.connection import get_conn

STOP_WORDS = {"policy", "the", "what", "how", "when", "is", "for", "about", "regarding"}


def get_all_modules() -> list[tuple]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT module_id, title, duration_hours, content FROM training_modules")
        return cur.fetchall()


def extract_search_term(query: str) -> str:
    words = query.replace("'", "").replace('"', "").split()
    keywords = [word for word in words if word.lower() not in STOP_WORDS and len(word) > 3]
    if keywords:
        return keywords[0]
    return words[0] if words else query


def search_training_content(query: str) -> list[tuple[str, str]]:
    search_term = extract_search_term(query)
    if not search_term.strip():
        return []

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT title, content
            FROM training_modules
            WHERE content LIKE ? OR title LIKE ?
            """,
            (f"%{search_term}%", f"%{search_term}%"),
        )
        return cur.fetchall()
