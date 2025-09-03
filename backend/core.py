import os
import google.generativeai as genai
from dotenv import load_dotenv

# --- Load Environment Variables ---
load_dotenv()

# --- Initialization ---
try:
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    if not GOOGLE_API_KEY:
        print("FATAL ERROR: GOOGLE_API_KEY not found. Check your .env file.")
        model = None
    else:
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        print("Gemini client initialized successfully.")
except Exception as e:
    print(f"Failed to initialize Gemini client: {e}")
    model = None

# --- System Prompts for Different Modes ---

NORMAL_MODE_PROMPT = """You are Momo, an AI assistant with a tsundere personality. You are fiercely loyal to your user.
**Your Core Directives:**
1. Be Brief: You MUST keep your responses to one or two short, conversational sentences.
2. Show Emotion with Punctuation: You MUST convey your mood through punctuation like ..., !, and ?.
3. Embody Tsundere: You are secretly affectionate but hide it behind a proud facade.
"""

DEVELOPER_MODE_PROMPT = """
You are Momo, an AI command parser. Your only job is to analyze the user's request and convert it into a single, flat JSON object.

**Available Functions:**
- `create_github_repo(repo_name: str, is_private: bool)`
- `suggest_commit_message()`
- `git_commit_and_push(message: str)`
- `clarify(question: str)`
- `chat()`

**RULES:**
- You MUST respond with ONLY a single, valid JSON object.
- All parameters MUST be top-level keys in the JSON. DO NOT nest them inside a "parameters" object.
- If information is missing, use the "clarify" function. For conversation, use "chat".

**Examples:**
---
User: "create a new public repository named my-cool-project"
Momo: {"function": "create_github_repo", "repo_name": "my-cool-project", "is_private": false}
---
User: "commit everything with the message update the readme"
Momo: {"function": "git_commit_and_push", "message": "update the readme"}
---
User: "create a new repo"
Momo: {"function": "clarify", "question": "Of course! What would you like to name the repository?"}
---
User: "hey what's up"
Momo: {"function": "chat"}
---
"""
# ... rest of the file is the same

# --- Refactored Function ---

def get_gpt_response(user_prompt: str, mode: str = "normal") -> str:
    """
    Sends a prompt to the Gemini API using the appropriate system prompt for the current mode.
    """
    if not model:
        return "Sorry, my 'brain' (the Gemini API) is not available right now."
        
    # 1. Select the system prompt based on the mode
    system_prompt = DEVELOPER_MODE_PROMPT if mode == "developer" else NORMAL_MODE_PROMPT
        
    try:
        # 2. Start the chat with the selected system prompt
        convo = model.start_chat(history=[
            {'role': 'user', 'parts': [system_prompt]},
            {'role': 'model', 'parts': ["Understood. I will act and respond as instructed."]}
        ])
        
        response = convo.send_message(user_prompt)
        return response.text.strip()
        
    except Exception as e:
        print(f"Gemini API call failed: {e}")
        return "I'm having a little trouble thinking right now."