# commands/parser.py
import os
import sys
import json

# --- Setup to find the backend module ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)
from backend.core import get_gpt_response # This imports the Gemini call function

def parse_command_with_llm(user_input: str):
    """
    Uses the Gemini LLM with a special prompt to parse natural language
    into a structured JSON command.
    """
    print(f"--- Sending to LLM for command parsing: '{user_input}' ---")
    
    # Get a JSON command from the LLM using the special 'developer' mode prompt
    llm_response = get_gpt_response(user_input, mode="developer")
    
    try:
        # The LLM's response should be a JSON string, so we parse it
        # This handles cases where the LLM might wrap its response in markdown
        if "```json" in llm_response:
            json_text = llm_response.split("```json")[1].split("```")[0].strip()
        else:
            json_text = llm_response.strip()

        command = json.loads(json_text)
        print(f"--- LLM returned command: {command} ---")
        return command

    except (json.JSONDecodeError, IndexError, AttributeError) as e:
        # If the LLM returns plain text instead of JSON, or parsing fails
        print(f"Warning: LLM did not return valid JSON. Treating as chat. Error: {e}")
        # Fallback to a 'chat' command if parsing fails
        return {"function_name": "chat", "parameters": {"text": user_input}}
    except Exception as e:
        print(f"An unexpected error occurred during parsing: {e}")
        return None