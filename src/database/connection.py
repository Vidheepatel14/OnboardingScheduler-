import sqlite3
from config.settings import DB_PATH

def get_conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    
    # 1. Partner's RAG Table (Stores content from PDFs)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS training_modules (
        module_id TEXT PRIMARY KEY,
        title TEXT,
        content TEXT,
        duration_hours REAL
    )""")

    # 2. Your Task Table (Tracks schedule & status)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_tasks (
        task_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT,
        module_id TEXT,
        status TEXT DEFAULT 'pending', 
        scheduled_start TEXT,
        scheduled_end TEXT,
        FOREIGN KEY(module_id) REFERENCES training_modules(module_id)
    )""")
    
    conn.commit()
    conn.close()