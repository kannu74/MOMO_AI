import sounddevice as sd
import numpy as np
import queue
import re
import time
from backend.core import get_gpt_response
from tts.speak import speak
from wakeword.detector import owwModel, WAKEWORD_MODEL_NAME
from stt.listen import transcribe_audio_chunk

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
    """Main loop with corrected timeout and control flow logic."""
    audio_queue = queue.Queue()

    def audio_callback(indata, frames, time, status):
        if status: print(status)
        audio_queue.put(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='int16', blocksize=CHUNK_SAMPLES, callback=audio_callback):
        print("--- Assistant running. Say the wake word. ---")
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
                    print("--- State: LISTENING_FOR_COMMAND (Speak now...) ---")
                    command_audio = []
                    silent_chunks = 0
                    has_spoken = False
                    # FIX: New counter for a reliable timeout
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

                # FIX: Corrected timeout condition
                timeout = not has_spoken and chunks_since_prompt >= INITIAL_TIMEOUT_CHUNKS
                end_of_speech = has_spoken and silent_chunks > SILENCE_CHUNKS_NEEDED
                
                if end_of_speech or timeout:
                    print()
                    
                    # --- REFACTORED RESPONSE LOGIC ---
                    
                    final_response = ""
                    if not has_spoken:
                        print("--- LISTENING TIMEOUT ---")
                        final_response = "I didn't hear anything."
                    else:
                        print("--- End of speech detected. Processing... ---")
                        full_command_audio = np.concatenate(command_audio)
                        user_input = transcribe_audio_chunk(full_command_audio)

                        if user_input:
                            if any(word in user_input.lower() for word in ["goodbye", "quit", "exit"]):
                                final_response = "Bye bye, see you later!"
                            else:
                                llm_response = get_gpt_response(user_input)
                                print(f"Momo: {llm_response}")
                                final_response = re.sub(r'\[.*?\]', '', llm_response).strip()
                        else:
                            final_response = "I'm sorry, I couldn't understand that."
                    
                    if final_response:
                        speak(final_response)

                    current_state = State.WAITING_FOR_WAKE_WORD
                    print("\n--- State: WAITING_FOR_WAKE_WORD ---")
                    # Clear the queue after the turn is fully complete
                    with audio_queue.mutex:
                        audio_queue.queue.clear()


if __name__ == "__main__":
    main()