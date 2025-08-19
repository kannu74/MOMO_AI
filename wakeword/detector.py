import openwakeword
import os

# --- Configuration ---
WAKEWORD_MODEL_NAME = "hey_momo copy"
MODEL_PATH = os.path.join("wakeword", "models", f"{WAKEWORD_MODEL_NAME}.onnx")

# --- Global State ---
# Create the model object to be imported by main.py
print("Loading wake word model...")
owwModel = openwakeword.Model(wakeword_models=[MODEL_PATH])