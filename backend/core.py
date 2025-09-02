import os
import google.generativeai as genai
from dotenv import load_dotenv

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

def get_gpt_response(user_prompt: str) -> str:
    """
    Sends a prompt to the Gemini API and gets a response.
    """
    if not model:
        return "Sorry, my 'brain' (the Gemini API) is not available right now."
        
    try:
        # Gemini's API uses a conversational history format
        convo = model.start_chat(history=[
            {'role': 'user', 'parts': [SYSTEM_PROMPT]},
            {'role': 'model', 'parts': ["Understood. I will act as Momo."]}
        ])
        
        response = convo.send_message(user_prompt)
        return response.text.strip()
        
    except Exception as e:
        print(f"Gemini API call failed: {e}")
        return "I'm having a little trouble thinking right now."