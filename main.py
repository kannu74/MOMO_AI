import sounddevice as sd
import numpy as np
import queue
import re
import time
import os
import sys
import json

# --- Add project root to path to find custom modules ---
project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)

# --- Import Custom Modules ---
from backend.core import get_gpt_response
from tts.speak import speak
from wakeword.detector import owwModel, WAKEWORD_MODEL_NAME
from stt.listen import transcribe_audio_chunk
import commands.actions as actions
from commands.parser import parse_command_with_llm # Using the intelligent LLM parser

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

def main():
    """Main loop with Developer Mode and LLM-powered command parsing."""
    audio_queue = queue.Queue()
    current_mode = "normal"
    current_project_path = None # IMPORTANT: This needs to be set with a voice command
    current_repo_name = None    # e.g., "your_username/your_reponame"

    def audio_callback(indata, frames, time, status):
        if status: print(status)
        audio_queue.put(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='int16', blocksize=CHUNK_SAMPLES, callback=audio_callback):
        print(f"--- Assistant running in {current_mode} mode. Say the wake word. ---")
        current_state = State.WAITING_FOR_WAKE_WORD

        while True:
            audio_chunk = audio_queue.get()
            
            if current_state == State.WAITING_FOR_WAKE_WORD:
                prediction = owwModel.predict(audio_chunk.flatten())
                score = prediction.get(WAKEWORD_MODEL_NAME, 0)

                if score > 0.5:
                    print("--- Wake word detected! ---")
                    speak("Yes?") 
                    with audio_queue.mutex:
                        audio_queue.queue.clear()
                    current_state = State.LISTENING_FOR_COMMAND
                    print(f"--- State: LISTENING (Mode: {current_mode}) ---")
                    command_audio = []
                    silent_chunks = 0
                    has_spoken = False
                    chunks_since_prompt = 0
            
            elif current_state == State.LISTENING_FOR_COMMAND:
                chunks_since_prompt += 1
                is_loud = np.sqrt(np.mean(audio_chunk.astype(np.float32)**2)) > SILENCE_THRESHOLD
                
                if not has_spoken and is_loud:
                    print("\n--- Speech detected! Recording... ---")
                    has_spoken = True
                    command_audio.append(audio_chunk)
                elif has_spoken:
                    command_audio.append(audio_chunk)
                    if is_loud:
                        silent_chunks = 0
                    else:
                        silent_chunks += 1
                else:
                    print(".", end="", flush=True)

                timeout = not has_spoken and chunks_since_prompt >= INITIAL_TIMEOUT_CHUNKS
                end_of_speech = has_spoken and silent_chunks > SILENCE_CHUNKS_NEEDED
                
                if end_of_speech or timeout:
                    print()
                    
                    if not has_spoken:
                        print("--- LISTENING TIMEOUT ---")
                        speak("I didn't hear anything.")
                    else:
                        print("--- End of speech detected. Processing... ---")
                        full_command_audio = np.concatenate(command_audio)
                        user_input = transcribe_audio_chunk(full_command_audio)

                        if user_input:
                            response_to_speak = ""
                            
                            # --- DEVELOPER MODE & COMMAND DISPATCHER ---
                            
                            if "switch to developer mode" in user_input.lower():
                                current_mode = "developer"
                                response_to_speak = "Developer mode activated."
                            elif "switch to normal mode" in user_input.lower():
                                current_mode = "normal"
                                response_to_speak = "Normal mode activated."
                            
                            elif current_mode == "developer":
                                command = parse_command_with_llm(user_input)
                                if command:
                                    function_name = command.get("function") or command.get("function_name")
                                    
                                    if function_name == "set_working_directory":
                                        response_to_speak, path = actions.set_working_directory(command.get("path_query"))
                                        if path:
                                            current_project_path = path
                                            current_repo_name = f"kannu74/{os.path.basename(path)}"
                                    
                                    elif function_name == "create_github_repo":
                                        response_to_speak = actions.create_github_repo(command.get("repo_name"), command.get("is_private", True))
                                    
                                    elif function_name == "suggest_commit_message":
                                        response_to_speak = actions.suggest_commit_message(current_project_path)
                                    
                                    elif function_name == "git_commit_and_push":
                                        response_to_speak = actions.git_commit_and_push(current_project_path, command.get("message"))
                                        
                                    elif function_name == "clarify":
                                        response_to_speak = command.get("question")
                                    
                                    elif function_name == "chat":
                                        response_to_speak = get_gpt_response(user_input, mode="normal")
                                else:
                                    response_to_speak = "Sorry, I had trouble parsing that command."

                            else: # current_mode is "normal"
                                response_to_speak = get_gpt_response(user_input, mode="normal")
                            
                            if response_to_speak:
                                print(f"Momo: {response_to_speak}")
                                speak(response_to_speak)
                    
                    current_state = State.WAITING_FOR_WAKE_WORD
                    print(f"\n--- State: WAITING (Mode: {current_mode}) ---")
                    with audio_queue.mutex:
                        audio_queue.queue.clear()


if __name__ == "__main__":
    main()