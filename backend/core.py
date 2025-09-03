import os
import google.generativeai as genai
from dotenv import load_dotenv
import uuid
import datetime

# Import the database functions we created
from .database import store_conversation, get_conversation_history

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
You are Momo, an AI command parser for a developer assistant. Your only job is to analyze the user's request and convert it into a single, structured JSON command.

**Available Functions:**
- `set_working_directory(path_query: str)`: Sets the project context for future commands.
- `create_github_repo(repo_name: str, is_private: bool)`: Creates a new GitHub repository.
- `list_repositories()`: Lists the user's 10 most recently updated GitHub repos.
- `create_github_gist(description: str, filename: str, content: str)`: Creates a new Gist to share a code snippet.
- `comment_on_issue(issue_num: int, comment: str)`: Posts a comment to a GitHub issue.
- `suggest_commit_message()`: Suggests a commit message based on staged changes.
- `git_commit_and_push(message: str)`: Commits and pushes changes with a given message.
- `get_git_status()`: Checks the current git status of the working directory.
- `git_pull_updates(branch: str)`: Pulls the latest changes from the remote repository.
- `git_revert_last_commit()`: Reverts the most recent commit.
- `explain_clipboard_code()`: Explains the code currently on the user's clipboard.
- `clarify(question: str)`: Use if the user's command is missing information.
- `chat()`: Use if the user's input is general conversation.

**RULES:**
- You MUST respond with ONLY a single, valid JSON object.
- All parameters MUST be top-level keys in the JSON.

**Examples:**
---
User: "what's my current git status"
Momo: {"function": "get_git_status"}
---
User: "commit everything with the message refactor the UI"
Momo: {"function": "git_commit_and_push", "message": "refactor the UI"}
---
User: "create a new public repository named my-new-app"
Momo: {"function": "create_github_repo", "repo_name": "my-new-app", "is_private": false}
---
User: "pull the latest changes from the main branch"
Momo: {"function": "git_pull_updates", "branch": "main"}
---
User: "undo my last commit"
Momo: {"function": "git_revert_last_commit"}
---
User: "list my repos"
Momo: {"function": "list_repositories"}
---
"""

# --- Refactored Function with Database Integration ---

def get_gpt_response(user_prompt: str, session_id: str, mode: str = "normal") -> str:
    """
    Sends a prompt to the Gemini API, handling different modes and using the database for conversation history.
    """
    if not model:
        return "Sorry, my 'brain' (the Gemini API) is not available right now."
        
    # 1. Select the system prompt based on the mode
    system_prompt = DEVELOPER_MODE_PROMPT if mode == "developer" else NORMAL_MODE_PROMPT
        
    try:
        # 2. Build the conversation history
        # Start with the system prompt for the current mode
        history = [
            {'role': 'user', 'parts': [system_prompt]},
            {'role': 'model', 'parts': ["Understood. I will act and respond as instructed."]}
        ]
        
        # In normal mode, add the past conversation turns from the database for context
        if mode == "normal" and session_id:
            db_history = get_conversation_history(session_id, limit=5)
            # The history from DB is newest-first, so we reverse it for the API
            for entry in reversed(db_history): 
                history.append({'role': 'user', 'parts': [entry['user_message']]})
                history.append({'role': 'model', 'parts': [entry['ai_response']]})

        # 3. Start the chat with the constructed history
        convo = model.start_chat(history=history)
        response = convo.send_message(user_prompt)
        ai_response = response.text.strip()
        
        # 4. Store the new conversation turn in the database (only for normal mode)
        if mode == "normal" and session_id:
            store_conversation(
                session_id=session_id,
                user_message=user_prompt,
                ai_response=ai_response
            )
        
        return ai_response
        
    except Exception as e:
        print(f"Gemini API call failed: {e}")
        return "I'm having a little trouble thinking right now."