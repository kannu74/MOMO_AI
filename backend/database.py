import sqlite3
import json
import datetime
import os
from typing import List, Dict, Optional, Tuple

class ConversationDatabase:
    def __init__(self, db_path: str = "conversations.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize the database with required tables."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create conversations table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    user_message TEXT NOT NULL,
                    ai_response TEXT NOT NULL,
                    context_summary TEXT,
                    metadata TEXT
                )
            ''')
            
            # Create sessions table for session management
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_activity DATETIME DEFAULT CURRENT_TIMESTAMP,
                    total_messages INTEGER DEFAULT 0
                )
            ''')
            
            conn.commit()
    
    def create_session(self, session_id: str) -> bool:
        """Create a new conversation session."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR IGNORE INTO sessions (session_id, created_at, last_activity)
                    VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ''', (session_id,))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error creating session: {e}")
            return False
    
    def store_conversation(self, session_id: str, user_message: str, ai_response: str, 
                         context_summary: str = None, metadata: Dict = None) -> bool:
        """Store a conversation exchange in the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Store the conversation
                cursor.execute('''
                    INSERT INTO conversations (session_id, user_message, ai_response, context_summary, metadata)
                    VALUES (?, ?, ?, ?, ?)
                ''', (session_id, user_message, ai_response, context_summary, 
                     json.dumps(metadata) if metadata else None))
                
                # Update session activity
                cursor.execute('''
                    UPDATE sessions 
                    SET last_activity = CURRENT_TIMESTAMP, total_messages = total_messages + 1
                    WHERE session_id = ?
                ''', (session_id,))
                
                conn.commit()
                return True
        except Exception as e:
            print(f"Error storing conversation: {e}")
            return False
    
    def get_conversation_history(self, session_id: str, limit: int = 10) -> List[Dict]:
        """Retrieve conversation history for a session."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT user_message, ai_response, timestamp, context_summary
                    FROM conversations 
                    WHERE session_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (session_id, limit))
                
                conversations = []
                for row in cursor.fetchall():
                    conversations.append({
                        'user_message': row[0],
                        'ai_response': row[1],
                        'timestamp': row[2],
                        'context_summary': row[3]
                    })
                
                return conversations[::-1]  # Reverse to get chronological order
        except Exception as e:
            print(f"Error retrieving conversation history: {e}")
            return []
    
    def get_context_summary(self, session_id: str) -> str:
        """Generate a context summary from recent conversations."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT user_message, ai_response
                    FROM conversations 
                    WHERE session_id = ?
                    ORDER BY timestamp DESC
                    LIMIT 5
                ''', (session_id,))
                
                recent_conversations = cursor.fetchall()
                if not recent_conversations:
                    return ""
                
                # Create a simple context summary
                context_parts = []
                for user_msg, ai_resp in recent_conversations:
                    context_parts.append(f"User: {user_msg}")
                    context_parts.append(f"Assistant: {ai_resp}")
                
                return "\n".join(context_parts)
        except Exception as e:
            print(f"Error generating context summary: {e}")
            return ""
    
    def get_session_info(self, session_id: str) -> Optional[Dict]:
        """Get information about a session."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT session_id, created_at, last_activity, total_messages
                    FROM sessions 
                    WHERE session_id = ?
                ''', (session_id,))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'session_id': row[0],
                        'created_at': row[1],
                        'last_activity': row[2],
                        'total_messages': row[3]
                    }
                return None
        except Exception as e:
            print(f"Error getting session info: {e}")
            return None

# Global database instance
db = ConversationDatabase() 