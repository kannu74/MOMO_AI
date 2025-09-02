<h1>🤖 Momo</h1>

<h3>Description</h3>
<p>
Momo is a voice-activated, multimodal AI assistant designed to act as a hands-free "pair programmer" for developers. 
She lives on the user's desktop, listening for a wake word, and uses a powerful Large Language Model (LLM) to perform common development tasks, explain code, and provide conversational assistance. 
The entire interaction is handled through a natural voice interface and a 3D avatar, minimizing context switching and allowing developers to stay in their "flow state."
</p>

<h3>Features</h3>
<ul>
  <li><strong>Voice-Activated Core</strong>: Fully hands-free operation using a custom wake word ("Hey Momo"), real-time Speech-to-Text (STT), and Text-to-Speech (TTS).</li>
  <li><strong>Modular Architecture</strong>: Each component (Wake Word, STT, LLM, TTS, Avatar) is a separate, swappable module, making the project easy to debug and upgrade.</li>
  <li><strong>Hybrid AI Brain</strong>: Uses the powerful Gemini 1.5 Flash API for complex, creative tasks and a local, predefined response system for instant answers to common questions.</li>
  <li><strong>Custom Expressive Voice</strong>: Integrates with ElevenLabs to use a custom-cloned, expressive voice, capable of performing non-speech sounds like sighs and laughs.</li>
  <li><strong>Developer Copilot Toolkit</strong>: Automates common developer workflows like running Git commands, generating boilerplate code, suggesting commit messages, and explaining code snippets from the clipboard.</li>
  <li><strong>Interactive 3D Avatar (In Progress)</strong>: Features a 3D anime avatar created in VRoid Studio and rendered in VSeeFace, which can be controlled by the Python script to show expressions and reactions.</li>
</ul>

<h3>Technologies Used</h3>
<ul>
    <li><strong>Core Language</strong>: Python</li>
    <li><strong>3D Avatar Tools</strong>:
        <ul>
            <li><strong>VRoid Studio</strong>: Used for 3D model creation (.vrm format).</li>
            <li><strong>VSeeFace</strong>: Used for real-time rendering and animation of the avatar.</li>
        </ul>
    </li>
    <li><strong>Core Python Libraries</strong>:
        <ul>
            <li><strong><code>google-generativeai</code></strong>: Powers the AI's "brain" by connecting to the Gemini LLM.</li>
            <li><strong><code>elevenlabs</code></strong>: Provides high-quality, custom voice output (TTS).</li>
            <li><strong><code>faster-whisper</code></strong>: Handles high-performance, local Speech-to-Text (STT).</li>
            <li><strong><code>openwakeword</code></strong>: Detects the "Hey Momo" wake word locally.</li>
            <li><strong><code>sounddevice</code></strong>: Captures audio from the microphone for the STT and wake word.</li>
            <li><strong><code>python-osc</code></strong>: Sends commands from Python to VSeeFace to control the avatar.</li>
            <li><strong><code>playsound</code></strong>: A simple library for playing audio files like the TTS output.</li>
            <li><strong><code>pydub</code></strong>: A robust library for audio manipulation and playback.</li>
            <li><strong><code>numpy</code></strong>: Used for numerical audio data processing.</li>
            <li><strong><code>onnxruntime</code></strong>: Runs the optimized wake word model (.onnx file).</li>
            <li><strong><code>python-dotenv</code></strong>: Loads secret API keys from the <code>.env</code> file.</li>
            <li><strong><code>pyperclip</code></strong>: Allows Momo to read code from the user's clipboard for the "explain code" feature.</li>
            <li><strong><code>PyGithub</code></strong>: Enables Momo to interact with the GitHub API for features like creating repositories and issues.</li>
            <li><strong><code>requests</code></strong>: For making general HTTP requests to any web API (e.g., weather, news).</li>
            <li><strong><code>pyttsx3</code></strong>: An offline, fallback library for Text-to-Speech if APIs are unavailable.</li>
        </ul>
    </li>
</ul>


<h3>📁 File Structure</h3>
<pre><code>momo/
├── .env               # 🔑 Stores all your secret API keys.
├── main.py            # ▶️ The main script that runs the assistant's loop.
├── requirements.txt   # 📦 All Python library dependencies.
│
├── backend/
│   └── core.py        # 🧠 Handles communication with the LLM (Gemini).
│
├── gui/
│   └── avatar.py      # 🧑‍🎨 Controls the 3D avatar's animations.
│
├── stt/
│   └── listen.py      # 👂 Handles Speech-to-Text (STT).
│
├── tts/
│   └── speak.py       # 👄 Handles Text-to-Speech (TTS).
│
└── wakeword/
    ├── detector.py    # 🚨 Handles wake word detection.
    └── models/        # 📁 Stores the .onnx wake word models.
</code></pre>

<h3>Setup and Installation</h3>

<h4>Prerequisites (Additional Installations)</h4>
<p>Before installing Python libraries, you need one external tool:</p>
<ul>
  <li><strong>FFmpeg:</strong> Required by the <code>faster-whisper</code> (STT) library to process audio. 
  <a href="https://ffmpeg.org/download.html">Download FFmpeg</a> and add it to your system PATH.</li>
</ul>

<h4>1. Clone the Repository</h4>
<pre><code>git clone &lt;https://github.com/kannu74/MOMO_AI&gt;
cd momo-ai-assistant
</code></pre>

<h4>2. Create and Activate Virtual Environment</h4>
<pre><code># Windows
python -m venv venv
.\venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
</code></pre>

<h4>3. Install Dependencies</h4>
<pre><code>pip install -r requirements.txt
</code></pre>

<h4>4. API Key Configuration</h4>
<p>Create a file named <code>.env</code> in the root directory. This file is required for the assistant to function.</p>
<ul>
  <li><strong>Required Keys:</strong>
    <ol>
      <li><code>GOOGLE_API_KEY</code>: From Google AI Studio for the Gemini LLM.</li>
      <li><code>ELEVEN_API_KEY</code>: From ElevenLabs for the TTS.</li>
      <li><code>ELEVEN_VOICE_ID</code>: The specific ID of your custom Momo voice from ElevenLabs.</li>
    </ol>
  </li>
  <li><strong>Format:</strong> Your <code>.env</code> file must look exactly like this:</li>
</ul>
<pre><code># .env file
GOOGLE_API_KEY=your_gemini_api_key_here
ELEVEN_API_KEY=your_elevenlabs_api_key_here
ELEVEN_VOICE_ID=your_momo_voice_id_here
</code></pre>

<h3>▶️ How to Run</h3>
<pre><code>python main.py
</code></pre>

<h3>🧠 LLM Context Prompt for Teammates</h3>
<p>To get your own AI assistant (like Gemini or ChatGPT) up to speed on this project, copy and paste the entire prompt below:</p>
<pre><code>
You are an expert software developer reviewing my project, "Momo AI". Here is a complete summary.

Project Goal:
Momo is a voice-activated, multimodal AI assistant built in Python. Its primary purpose is to act as a "pair programmer" for developers, handling repetitive tasks through voice commands to minimize context switching and keep the developer in a state of flow.

Current Status:
The core audio pipeline is fully functional. It can detect a wake word, transcribe a spoken command, get a response from an LLM, and speak the response back using a custom voice. The next phase is to integrate a 3D avatar with computer vision.

Tech Stack:
- Wake Word: openwakeword using an .onnx model.
- Speech-to-Text (STT): faster-whisper (tiny.en model).
- AI Brain (LLM): Gemini 1.5 Flash API.
- Text-to-Speech (TTS): ElevenLabs API with a custom-cloned voice.
- System Interaction: Python's subprocess and pyperclip libraries for developer features.
- Required API Keys: GOOGLE_API_KEY, ELEVEN_API_KEY, ELEVEN_VOICE_ID.
- External Dependencies: FFmpeg is required for faster-whisper.

File Structure:
- main.py: The central script that runs the main application loop.
- backend/core.py: Manages all communication with the Gemini API.
- tts/speak.py: Manages all communication with the ElevenLabs API.
- stt/listen.py: Handles audio recording and transcription.
- wakeword/detector.py: Listens for the wake word.
- gui/avatar.py: This is where the future code to control the 3D avatar will go.

Next Steps:
The team's next goal is to implement the developer-focused features (e.g., voice-controlled Git commands, boilerplate code generation) and integrate the 3D avatar using VSeeFace and OpenCV.

Based on this information, please act as my expert assistant for this project.
</code></pre>
<h3>Project Workflow</h3>
<p>
Momo operates on a continuous loop, managed by <code>main.py</code>, that follows a clear, modular sequence. The architecture is designed to be fast and responsive by handling simple queries locally and deferring complex tasks to a powerful cloud-based LLM.
</p>
<ol>
    <li>
        <strong>Wake Word Detection</strong>: The assistant is always passively listening using <code>openwakeword</code>. When it detects the "Hey Momo" phrase, it activates the main interaction loop.
    </li>
    <li>
        <strong>Speech-to-Text (STT)</strong>: Once activated, the microphone actively records the user's command. This audio is processed locally by <code>faster-whisper</code>, which transcribes the speech into a text string.
    </li>
    <li>
        <strong>Intent Parsing</strong>: The main script (<code>main.py</code>) analyzes the transcribed text to decide what to do next. This acts as a "router" for the AI's brain.
    </li>
    <li>
        <strong>Hybrid Response Generation</strong>:
        <ul>
            <li><strong>Simple Intent</strong>: If the command is a basic, predefined query (e.g., "hello", "how are you?"), the system instantly retrieves a random response from a local library to be fast and efficient.</li>
            <li><strong>Developer/Complex Intent</strong>: For any other query, the text is sent to the <strong>Gemini 1.5 Flash API</strong>. The LLM then generates an intelligent, context-aware, and in-character response.</li>
        </ul>
    </li>
    <li>
        <strong>Multimodal Output</strong>: The final text response from the LLM is sent to two places simultaneously:
        <ul>
            <li>The <strong>ElevenLabs API</strong> converts the text into high-quality, expressive audio in Momo's custom voice.</li>
            <li>The <strong>Avatar Controller</strong> (<code>gui/avatar.py</code>) sends a command via OSC to <strong>VSeeFace</strong> to trigger a corresponding visual animation (e.g., a smile, a blush, or a thoughtful expression).</li>
        </ul>
    </li>
    <li>
        <strong>Loop Reset</strong>: After the audio is played and the avatar has animated, the system returns to its passive state, listening for the wake word to begin the next interaction.
    </li>
</ol>
