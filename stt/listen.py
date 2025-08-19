import numpy as np
from faster_whisper import WhisperModel

MODEL_SIZE = "tiny.en"
DEVICE = "cpu"
COMPUTE_TYPE = "int8"

print("Loading speech-to-text model...")
model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)

def transcribe_audio_chunk(audio_np: np.ndarray):
    if audio_np.size == 0:
        return ""
    
    print("--- Processing speech... ---")
    audio_np = audio_np.flatten()  # Flatten to mono
    audio_normalized = audio_np.astype(np.float32) / 32768.0

    segments, _ = model.transcribe(audio_normalized, beam_size=5)
    transcription = " ".join(segment.text for segment in segments)
    
    print(f"You said: {transcription.strip()}")
    return transcription.strip()
