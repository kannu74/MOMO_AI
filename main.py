import sounddevice as sd
import numpy as np
import queue
import re
import time
import os
import sys
import json
from dotenv import load_dotenv

# --- Add project root to path to find custom modules ---
project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)
load_dotenv() # Load .env file from root

# --- Import Custom Modules ---
from backend.core import get_gpt_response
from tts.speak import speak
from wakeword.detector import owwModel, WAKEWORD_MODEL_NAME
from stt.listen import transcribe_audio_chunk
import commands.actions as actions
from commands.parser import parse_command_with_llm
from backend.database import initialize_session

# --- Audio Configuration ---
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512
CHANNELS = 1
SILENCE_THRESHOLD = 150
SILENCE_CHUNKS_NEEDED = 8
INITIAL_TIMEOUT_CHUNKS = 80

# --- State Management ---
class State:
    WAITING_FOR_WAKE_WORD = 1
    LISTENING_FOR_COMMAND = 2

def main(ui_queue, tts_finished_event):
    """Main AI logic loop with Developer Mode as default."""
    audio_queue = queue.Queue()
    current_mode = "developer"  # <-- Default mode is now developer
    current_project_path = None
    current_repo_name = None
    
    GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
    session_id = initialize_session()

    def audio_callback(indata, frames, time, status):
        if status: print(status)
        audio_queue.put(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='int16', blocksize=CHUNK_SAMPLES, callback=audio_callback):
        ui_queue.put({"type": "status", "data": f"Running in {current_mode} mode. Listening..."})
        current_state = State.WAITING_FOR_WAKE_WORD

        while True:
            audio_chunk = audio_queue.get()
            
            if current_state == State.WAITING_FOR_WAKE_WORD:
                prediction = owwModel.predict(audio_chunk.flatten())
                score = prediction.get(WAKEWORD_MODEL_NAME, 0)

                if score > 0.5:
                    ui_queue.put({"type": "status", "data": "Wake word detected!"})
                    ui_queue.put({"type": "speak", "data": "Yes?"})
                    tts_finished_event.wait(); tts_finished_event.clear()
                    
                    with audio_queue.mutex: audio_queue.queue.clear()
                    current_state = State.LISTENING_FOR_COMMAND
                    ui_queue.put({"type": "status", "data": f"Listening... (Mode: {current_mode})"})
                    command_audio, silent_chunks, has_spoken, chunks_since_prompt = [], 0, False, 0
            
            elif current_state == State.LISTENING_FOR_COMMAND:
                chunks_since_prompt += 1
                is_loud = np.sqrt(np.mean(audio_chunk.astype(np.float32)**2)) > SILENCE_THRESHOLD
                
                if not has_spoken and is_loud: has_spoken = True
                if has_spoken:
                    command_audio.append(audio_chunk)
                    if is_loud: silent_chunks = 0
                    else: silent_chunks += 1
                
                timeout = not has_spoken and chunks_since_prompt >= INITIAL_TIMEOUT_CHUNKS
                end_of_speech = has_spoken and silent_chunks > SILENCE_CHUNKS_NEEDED
                
                if end_of_speech or timeout:
                    response_to_speak = ""
                    if not has_spoken:
                        response_to_speak = "I didn't hear anything."
                    else:
                        full_command_audio = np.concatenate(command_audio)
                        user_input = transcribe_audio_chunk(full_command_audio)
                        ui_queue.put({"type": "user_chat", "data": user_input})

                        if user_input:
                            ui_queue.put({"type": "status", "data": "Thinking..."})
                            
                            # --- FULL COMMAND DISPATCHER LOGIC ---
                            if "switch to developer mode" in user_input.lower():
                                current_mode = "developer"
                                response_to_speak = "Developer mode activated."
                            elif "switch to normal mode" in user_input.lower():
                                current_mode = "normal"
                                response_to_speak = "Normal mode activated."
                            
                            elif current_mode == "developer":
                                command = parse_command_with_llm(user_input, session_id)
                                if command:
                                    function_name = command.get("function") or command.get("function_name")
                                    
                                    if function_name == "set_working_directory":
                                        response, path = actions.set_working_directory(command.get("path_query"))
                                        if path: 
                                            current_project_path = path
                                            if GITHUB_USERNAME:
                                                current_repo_name = f"{GITHUB_USERNAME}/{os.path.basename(path)}"
                                        response_to_speak = response
                                    
                                    elif function_name == "create_github_repo":
                                        response_to_speak = actions.create_github_repo(command.get("repo_name"), command.get("is_private", True))
                                    
                                    elif function_name == "suggest_commit_message":
                                        response_to_speak = actions.suggest_commit_message(current_project_path, session_id)
                                    
                                    elif function_name == "git_commit_and_push":
                                        response_to_speak = actions.git_commit_and_push(current_project_path, command.get("message"))

                                    elif function_name == "get_git_status":
                                        response_to_speak = actions.get_git_status(current_project_path)

                                    elif function_name == "git_pull_updates":
                                        response_to_speak = actions.git_pull_updates(current_project_path, command.get("branch", "main"))

                                    elif function_name == "git_revert_last_commit":
                                        response_to_speak = actions.git_revert_last_commit(current_project_path)

                                    elif function_name == "explain_clipboard_code":
                                        response_to_speak = actions.explain_clipboard_code(session_id)

                                    elif function_name == "comment_on_issue":
                                        response_to_speak = actions.comment_on_issue(current_repo_name, command.get("issue_num"), command.get("comment"))
                                        
                                    elif function_name == "clarify":
                                        response_to_speak = command.get("question")
                                    
                                    elif function_name == "chat":
                                        response_to_speak = get_gpt_response(user_input, session_id, mode="normal")
                                else:
                                    response_to_speak = "Sorry, I had trouble parsing that command."

                            else: # current_mode is "normal"
                                response_to_speak = get_gpt_response(user_input, session_id, mode="normal")
                        else:
                            response_to_speak = "I'm sorry, I couldn't understand that."
                    
                    if response_to_speak:
                        ui_queue.put({"type": "momo_chat", "data": response_to_speak})
                        ui_queue.put({"type": "speak", "data": response_to_speak})
                        tts_finished_event.wait(); tts_finished_event.clear()

                    current_state = State.WAITING_FOR_WAKE_WORD
                    ui_queue.put({"type": "status", "data": f"Waiting for wake word... (Mode: {current_mode})"})
                    with audio_queue.mutex:
                        audio_queue.queue.clear()

if __name__ == "__main__":
    print("This script is the AI logic thread and should be run by main_ui.py")