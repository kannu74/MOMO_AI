#!/usr/bin/env python3
"""
Conversation Manager - Utility to view and manage conversation history
"""

import argparse
import sys
import sqlite3
from backend.database import db
from backend.core import get_session_info, get_session_context

def list_sessions():
    """List all conversation sessions."""
    try:
        with sqlite3.connect(db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT session_id, created_at, last_activity, total_messages
                FROM sessions 
                ORDER BY last_activity DESC
                LIMIT 20
            ''')
            
            sessions = cursor.fetchall()
            
            if not sessions:
                print("No conversation sessions found.")
                return
            
            print("\n=== Conversation Sessions ===")
            print(f"{'Session ID':<25} {'Created':<20} {'Last Activity':<20} {'Messages':<10}")
            print("-" * 75)
            
            for session in sessions:
                session_id, created, last_activity, messages = session
                print(f"{session_id:<25} {created:<20} {last_activity:<20} {messages:<10}")
                
    except Exception as e:
        print(f"Error listing sessions: {e}")

def view_session(session_id):
    """View conversation history for a specific session."""
    try:
        # Get session info
        session_info = get_session_info(session_id)
        if not session_info:
            print(f"Session {session_id} not found.")
            return
        
        print(f"\n=== Session: {session_id} ===")
        print(f"Created: {session_info['created_at']}")
        print(f"Last Activity: {session_info['last_activity']}")
        print(f"Total Messages: {session_info['total_messages']}")
        print("-" * 50)
        
        # Get conversation history
        history = db.get_conversation_history(session_id, limit=50)
        
        if not history:
            print("No conversation history found.")
            return
        
        for i, conv in enumerate(history, 1):
            print(f"\n--- Exchange {i} ---")
            print(f"Time: {conv['timestamp']}")
            print(f"User: {conv['user_message']}")
            print(f"Momo: {conv['ai_response']}")
            if conv['context_summary']:
                print(f"Context: {conv['context_summary']}")
            print("-" * 30)
            
    except Exception as e:
        print(f"Error viewing session: {e}")

def export_session(session_id, output_file):
    """Export conversation history to a text file."""
    try:
        history = db.get_conversation_history(session_id, limit=1000)
        
        if not history:
            print(f"No conversation history found for session {session_id}")
            return
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"Conversation Export - Session: {session_id}\n")
            f.write("=" * 50 + "\n\n")
            
            for i, conv in enumerate(history, 1):
                f.write(f"Exchange {i} - {conv['timestamp']}\n")
                f.write(f"User: {conv['user_message']}\n")
                f.write(f"Momo: {conv['ai_response']}\n")
                f.write("-" * 30 + "\n\n")
        
        print(f"Conversation exported to {output_file}")
        
    except Exception as e:
        print(f"Error exporting session: {e}")

def delete_session(session_id):
    """Delete a conversation session."""
    try:
        with sqlite3.connect(db.db_path) as conn:
            cursor = conn.cursor()
            
            # Delete conversations first (foreign key constraint)
            cursor.execute('DELETE FROM conversations WHERE session_id = ?', (session_id,))
            conversations_deleted = cursor.rowcount
            
            # Delete session
            cursor.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
            session_deleted = cursor.rowcount
            
            conn.commit()
            
            if session_deleted > 0:
                print(f"Session {session_id} deleted successfully.")
                print(f"Deleted {conversations_deleted} conversation records.")
            else:
                print(f"Session {session_id} not found.")
                
    except Exception as e:
        print(f"Error deleting session: {e}")

def main():
    parser = argparse.ArgumentParser(description='Manage Momo AI conversation history')
    parser.add_argument('action', choices=['list', 'view', 'export', 'delete'], 
                       help='Action to perform')
    parser.add_argument('--session-id', '-s', help='Session ID for view/export/delete actions')
    parser.add_argument('--output', '-o', help='Output file for export action')
    
    args = parser.parse_args()
    
    if args.action == 'list':
        list_sessions()
    elif args.action in ['view', 'export', 'delete']:
        if not args.session_id:
            print(f"Error: --session-id is required for {args.action} action")
            sys.exit(1)
        
        if args.action == 'view':
            view_session(args.session_id)
        elif args.action == 'export':
            if not args.output:
                args.output = f"conversation_{args.session_id}.txt"
            export_session(args.session_id, args.output)
        elif args.action == 'delete':
            confirm = input(f"Are you sure you want to delete session {args.session_id}? (y/N): ")
            if confirm.lower() == 'y':
                delete_session(args.session_id)
            else:
                print("Deletion cancelled.")

if __name__ == "__main__":
    main() 