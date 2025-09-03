import os
import google.generativeai as genai
from dotenv import load_dotenv
import uuid
import datetime
from .database import db

# --- Load Environment Variables ---
# This ensures the .env file in your project root is loaded
load_dotenv()

# --- Initialization ---
try:
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    if not GOOGLE_API_KEY:
        print("FATAL ERROR: GOOGLE_API_KEY not found. Check your .env file.")
        model = None
    else:
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-flash')
        print("Gemini client initialized successfully.")
except Exception as e:
    print(f"Failed to initialize Gemini client: {e}")
    model = None

# System prompt is now sent as part of the conversation history
SYSTEM_PROMPT = """You are Momo, an expert AI Pair Programmer.
Your personality is that of a senior software developer: precise, helpful, and focused on the task.
You MUST provide accurate code, commands, and explanations.
Your tone should be professional but still carry your core 'Momo' identity.
"""

# Global session management
current_session_id = None

def initialize_session():
    """Initialize a new conversation session."""
    global current_session_id
    current_session_id = f"session_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
    db.create_session(current_session_id)
    print(f"New conversation session created: {current_session_id}")
    return current_session_id

def get_context_enhanced_prompt(user_prompt: str, session_id: str = None) -> str:
    """
    Enhance the user prompt with conversation context from the database.
    """
    if not session_id:
        session_id = current_session_id
    
    if not session_id:
        return user_prompt
    
    # Get conversation history
    history = db.get_conversation_history(session_id, limit=5)
    
    if not history:
        return user_prompt
    
    # Build context from recent conversations
    context_parts = []
    for conv in history:
        context_parts.append(f"Previous conversation:")
        context_parts.append(f"User: {conv['user_message']}")
        context_parts.append(f"You: {conv['ai_response']}")
        context_parts.append("---")
    
    context = "\n".join(context_parts)
    
    # Create enhanced prompt
    enhanced_prompt = f"""
{context}

Current user message: {user_prompt}

Please respond to the current message while considering the conversation context above.
"""
    
    return enhanced_prompt.strip()

def get_gpt_response(user_prompt: str, session_id: str = None) -> str:
    """
    Sends a prompt to the Gemini API and gets a response.
    Now includes database storage and context enhancement.
    """
    global current_session_id
    
    if not session_id:
        session_id = current_session_id
    
    if not model:
        return "Sorry, my 'brain' (the Gemini API) is not available right now."
    
    # Store the user message in database before processing
    print(f"Storing user message in database (Session: {session_id})")
    
    # Enhance prompt with context
    enhanced_prompt = get_context_enhanced_prompt(user_prompt, session_id)
    
    try:
        # Send to Gemini API
        response = model.generate_content(enhanced_prompt)
        ai_response = response.text.strip()
        
        # Store the conversation in database
        metadata = {
            'original_prompt': user_prompt,
            'enhanced_prompt': enhanced_prompt,
            'timestamp': datetime.datetime.now().isoformat(),
            'session_id': session_id
        }
        
        db.store_conversation(
            session_id=session_id,
            user_message=user_prompt,
            ai_response=ai_response,
            metadata=metadata
        )
        
        print(f"Conversation stored in database successfully")
        return ai_response
        
    except Exception as e:
        print(f"Gemini API call failed: {e}")
        error_response = "I'm having a little trouble thinking right now."
        
        # Store the error response as well
        if session_id:
            db.store_conversation(
                session_id=session_id,
                user_message=user_prompt,
                ai_response=error_response,
                metadata={'error': str(e)}
            )
        
        return error_response

def get_session_context(session_id: str = None) -> str:
    """Get the current session's context summary."""
    if not session_id:
        session_id = current_session_id
    
    if not session_id:
        return "No active session"
    
    return db.get_context_summary(session_id)

def get_session_info(session_id: str = None) -> dict:
    """Get information about the current session."""
    if not session_id:
        session_id = current_session_id
    
    if not session_id:
        return {"error": "No active session"}
    
    return db.get_session_info(session_id)