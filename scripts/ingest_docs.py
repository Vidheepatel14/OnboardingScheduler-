import sys
from pathlib import Path
# Add parent dir to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import os
import sqlite3
import pypdf
from config.settings import DB_PATH, DOCS_DIR
from src.database.connection import init_db

def load_docs():
    print("🚀 Starting PDF Ingestion...")
    init_db() 
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    if not os.path.exists(DOCS_DIR):
        os.makedirs(DOCS_DIR)
        print(f"⚠️ Created {DOCS_DIR}. Add your PDFs there!")
        return

    pdf_files = list(DOCS_DIR.glob("*.pdf"))
    print(f"📂 Found {len(pdf_files)} PDF(s)...")
    
    for file_path in pdf_files:
        try:
            reader = pypdf.PdfReader(file_path)
            content = ""
            for page in reader.pages:
                content += page.extract_text() + "\n"
            
            mod_id = file_path.stem.upper()
            title = file_path.stem.replace("_", " ").title()
            
            print(f"   ➡️  Processing '{title}'...")
            cur.execute("""
                INSERT OR REPLACE INTO training_modules (module_id, title, content, duration_hours)
                VALUES (?, ?, ?, 1.0)
            """, (mod_id, title, content))
            
        except Exception as e:
            print(f"   ❌ Error reading {file_path.name}: {e}")
        
    conn.commit()
    conn.close()
    print("✅ Ingestion Complete.")

if __name__ == "__main__":
    load_docs()