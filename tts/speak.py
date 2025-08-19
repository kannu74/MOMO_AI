# tts/speak.py
from elevenlabs.client import ElevenLabs
from elevenlabs import play
import os
from dotenv import load_dotenv

# --- Explicitly find and load the .env file from the project root ---
# This constructs a path like C:/Users/aksha/.../MOMO/.env
project_dir = os.path.join(os.path.dirname(__file__), '..')
dotenv_path = os.path.join(project_dir, '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Configuration and Diagnostic Check ---
API_KEY = os.getenv("ELEVEN_API_KEY")
MOMO_VOICE_ID = os.getenv("ELEVEN_VOICE_ID") 

# This will print True if the key was found, and False if it was not.
print(f"--- Is API Key loaded successfully? ---  {API_KEY is not None}")

# --- Initialization ---
if not API_KEY:
    print("FATAL ERROR: ELEVEN_API_KEY not found. Please check your .env file.")
    client = None
else:
    try:
        client = ElevenLabs(api_key=API_KEY)
        print("ElevenLabs client initialized successfully.")
    except Exception as e:
        print(f"Failed to initialize ElevenLabs client: {e}")
        client = None

def speak(text: str):
    """
    Generates and plays audio using the correct client.text_to_speech.convert() method.
    """
    if not client:
        print("ElevenLabs client not initialized. Cannot speak.")
        print(f"Momo (text): {text}")
        return

    # Wrap text inside SSML-style <voice> tags for expressive cues
    # ssml_text = f"<voice>{text}</voice>"

    print("Generating audio with ElevenLabs...")
    try:
        audio = client.text_to_speech.convert(
            voice_id=MOMO_VOICE_ID,
            text=text,
            model_id="eleven_multilingual_v2",
            
        )
        
        if audio:
            print("Playing audio...")
            play(audio)

    except Exception as e:
        print(f"ElevenLabs API call failed: {e}")
        print(f"Momo (text): {text}")
