# backend/database.py
import sqlite3
import os
import datetime
import uuid

# --- Database Initialization ---
DB_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, 'memory.db')

def setup_database():
    """Creates the necessary tables in the database if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create a table for conversation sessions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        start_time TEXT NOT NULL
    )
    """)
    
    # Create a table to store individual messages
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        user_message TEXT NOT NULL,
        ai_response TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions (session_id)
    )
    """)
    
    conn.commit()
    conn.close()

def initialize_session() -> str:
    """Creates a new session and returns its ID."""
    session_id = f"session_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
    start_time = datetime.datetime.now().isoformat()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions (session_id, start_time) VALUES (?, ?)", (session_id, start_time))
    conn.commit()
    conn.close()
    
    print(f"New conversation session created in SQL database: {session_id}")
    return session_id

def store_conversation(session_id, user_message, ai_response):
    """Stores a single turn of a conversation in the database."""
    if not session_id:
        return
    
    timestamp = datetime.datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO conversations (session_id, user_message, ai_response, timestamp) VALUES (?, ?, ?, ?)",
        (session_id, user_message, ai_response, timestamp)
    )
    conn.commit()
    conn.close()

def get_conversation_history(session_id, limit=5):
    """Retrieves the last N turns of a conversation for a given session."""
    if not session_id:
        return []
    
    conn = sqlite3.connect(DB_PATH)
    # This allows us to get results as dictionaries
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT user_message, ai_response FROM conversations WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
        (session_id, limit)
    )
    
    history = cursor.fetchall()
    conn.close()
    
    # Convert the sqlite3.Row objects to standard dictionaries
    return [dict(row) for row in history]

# --- Run Setup on Import ---
# This ensures the database and tables are created when the module is first imported
setup_database()