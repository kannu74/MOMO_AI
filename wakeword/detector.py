import os

import openwakeword
from openwakeword.utils import download_models

import config

WAKEWORD_MODEL_NAME = config.WAKEWORD_MODEL_NAME
WAKEWORD_THRESHOLD = config.WAKEWORD_THRESHOLD

# openWakeWord's shared feature models (melspectrogram + embedding) aren't shipped with pip; fetch once.
_res = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
if not os.path.exists(os.path.join(_res, "embedding_model.onnx")):
    print("Downloading openWakeWord feature models (one time)...")
    download_models(model_names=["hey_jarvis_v0.1"])

print(f"Loading wake word model '{WAKEWORD_MODEL_NAME}' (threshold {WAKEWORD_THRESHOLD})...")
owwModel = openwakeword.Model(wakeword_models=[config.WAKEWORD_MODEL_PATH], inference_framework="onnx")
