# commands/parser.py
import os
import sys
import json

# --- Setup to find other project files ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)
from backend.core import get_gpt_response
import commands.actions as actions

# ... (FUNCTION_CALLING_PROMPT is the same) ...
FUNCTION_CALLING_PROMPT = """
You are Momo, an AI command parser...
"""

def parse_command_with_llm(user_input: str, session_id: str):
    """
    Uses the LLM to parse natural language into a structured command.
    """
    print(f"--- Sending to LLM for command parsing: '{user_input}' ---")
    
    # Get a JSON command from the LLM, now passing the session_id
    llm_response = get_gpt_response(user_input, session_id, mode="developer")
    
    try:
        if "```json" in llm_response:
            json_text = llm_response.split("```json")[1].split("```")[0].strip()
        else:
            json_text = llm_response.strip()

        command = json.loads(json_text)
        print(f"--- LLM returned command: {command} ---")
        return command

    except (json.JSONDecodeError, IndexError, AttributeError) as e:
        print(f"Warning: LLM did not return valid JSON. Treating as chat. Error: {e}")
        return {"function_name": "chat", "parameters": {"text": user_input}}
    except Exception as e:
        print(f"An unexpected error occurred during parsing: {e}")
        return None