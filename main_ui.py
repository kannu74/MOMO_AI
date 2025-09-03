import tkinter as tk
from tkinter import scrolledtext
from PIL import ImageTk, Image
import threading
import queue
import os
import sys
import signal

# --- Add project root to path ---
project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)
assets_path = os.path.join(project_root, "assets")

from main import main as momo_main
from tts.speak import speak


# -------------------------------
# AnimatedGif class
# -------------------------------
class AnimatedGif:
    def __init__(self, canvas, gif_path, x, y):
        self.canvas = canvas
        self.frames = []
        self.load_frames(gif_path)
        self.current_frame = 0
        self.image_on_canvas = self.canvas.create_image(
            x, y, anchor=tk.NW, image=self.frames[0]
        )

    def load_frames(self, gif_path):
        gif = Image.open(gif_path)
        try:
            while True:
                frame = gif.copy().convert("RGBA")
                self.frames.append(ImageTk.PhotoImage(frame))
                gif.seek(len(self.frames))
        except EOFError:
            pass

    def update(self):
        self.current_frame = (self.current_frame + 1) % len(self.frames)
        self.canvas.itemconfig(
            self.image_on_canvas, image=self.frames[self.current_frame]
        )
        self.canvas.after(100, self.update)


# -------------------------------
# MomoApp class
# -------------------------------
class MomoApp:
    def __init__(self, root, ui_queue, tts_finished_event):
        self.root = root
        self.ui_queue = ui_queue
        self.tts_finished_event = tts_finished_event

        self.root.title("Momo")
        self.root.geometry("400x500")

        # Canvas for animation
        self.canvas = tk.Canvas(self.root, width=300, height=300, bg="black")
        self.canvas.pack(pady=10)

        # Status label
        self.status_label = tk.Label(
            self.root, text="Waiting...", fg="white", bg="black"
        )
        self.status_label.pack()

        # Chat log
        self.chat_log = scrolledtext.ScrolledText(
            self.root, wrap=tk.WORD, height=10, state=tk.DISABLED
        )
        self.chat_log.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # Load animations
        self.animations = {}
        self.current_animation = None
        self.load_animations()

        # Start queue processing
        self.root.after(100, self.process_queue)

    def load_animations(self):
        self.animations["idle"] = AnimatedGif(
            self.canvas, os.path.join(assets_path, "idle.gif"), 0, 0
        )
        self.animations["speaking"] = AnimatedGif(
            self.canvas, os.path.join(assets_path, "speaking.gif"), 0, 0
        )
        self.animations["listening"] = AnimatedGif(
            self.canvas, os.path.join(assets_path, "listening.gif"), 0, 0
        )
        self.set_animation("idle")

    def set_animation(self, name):
        if self.current_animation:
            self.canvas.delete(self.current_animation.image_on_canvas)
        self.current_animation = self.animations[name]
        self.current_animation.update()

    def add_chat_message(self, message):
        self.chat_log.config(state=tk.NORMAL)
        self.chat_log.insert(tk.END, message + "\n")
        self.chat_log.config(state=tk.DISABLED)
        self.chat_log.see(tk.END)

    def process_queue(self):
        try:
            message = self.ui_queue.get_nowait()
            msg_type = message.get("type")
            data = message.get("data")

            if msg_type == "speak":
                self.set_animation("speaking")
                speak(data)
                self.set_animation("listening")
                # ✅ Signal AI thread that TTS finished
                self.tts_finished_event.set()

            elif msg_type == "status":
                self.status_label.config(text=data)
            elif msg_type == "user_chat":
                self.add_chat_message(f"You: {data}")
            elif msg_type == "momo_chat":
                self.add_chat_message(f"Momo: {data}")

        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.process_queue)


# -------------------------------
# Entry point
# -------------------------------
if __name__ == "__main__":
    comm_queue = queue.Queue()
    tts_finished_event = threading.Event()

    ai_thread = threading.Thread(
        target=momo_main, args=(comm_queue, tts_finished_event), daemon=True
    )
    ai_thread.start()

    app_root = tk.Tk()
    signal.signal(signal.SIGINT, lambda sig, frame: app_root.destroy())

    app = MomoApp(app_root, comm_queue, tts_finished_event)
    app_root.mainloop()
