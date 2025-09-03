#!/usr/bin/env python3
"""
Test script for the conversation database functionality
"""

from backend.database import db
from backend.core import initialize_session, get_gpt_response, get_session_info

def test_database_functionality():
    """Test the database functionality."""
    print("=== Testing Database Functionality ===")
    
    # Test 1: Create a session
    print("\n1. Creating a new session...")
    session_id = initialize_session()
    print(f"Session created: {session_id}")
    
    # Test 2: Store some test conversations
    print("\n2. Storing test conversations...")
    test_conversations = [
        ("Hello, how are you?", "I'm doing great! How can I help you today?"),
        ("What's the weather like?", "I don't have access to real-time weather data, but I can help you with programming questions!"),
        ("Can you help me with Python?", "Absolutely! I'd love to help you with Python programming. What specific question do you have?")
    ]
    
    for user_msg, ai_resp in test_conversations:
        success = db.store_conversation(session_id, user_msg, ai_resp)
        print(f"Stored conversation: {'✓' if success else '✗'}")
    
    # Test 3: Retrieve conversation history
    print("\n3. Retrieving conversation history...")
    history = db.get_conversation_history(session_id)
    print(f"Found {len(history)} conversations:")
    for i, conv in enumerate(history, 1):
        print(f"  {i}. User: {conv['user_message']}")
        print(f"     Momo: {conv['ai_response']}")
    
    # Test 4: Get session info
    print("\n4. Getting session info...")
    session_info = get_session_info(session_id)
    print(f"Session Info: {session_info}")
    
    # Test 5: Test context enhancement
    print("\n5. Testing context enhancement...")
    from backend.core import get_context_enhanced_prompt
    enhanced = get_context_enhanced_prompt("What did we talk about earlier?", session_id)
    print(f"Enhanced prompt length: {len(enhanced)} characters")
    print("First 200 chars of enhanced prompt:")
    print(enhanced[:200] + "...")
    
    print("\n=== Database Test Complete ===")

if __name__ == "__main__":
    test_database_functionality() 