#!/usr/bin/env python3
import os
import sys
import json
import time
import queue
import logging
import threading
import asyncio
import aiohttp

# --- Configuration ---
# You need to install: pip install vosk sounddevice
try:
    import sounddevice as sd
    from vosk import Model, KaldiRecognizer
except ImportError:
    sd = None
    Model = None
    KaldiRecognizer = None
    logging.warning("Missing vosk/sounddevice; speech features disabled")

# Voice synthesis (very lightweight for Pi 4)
# Option A: espeak-ng (robotic but fast)
# Option B: gTTS (needs internet)
# Option C: pyttsx3 (can use espeak/sapi5)
import subprocess

from survivor_audio_flow import SurvivorAudioFlow

def speak(text):
    print(f"TTS: {text}")
    try:
        # Using espeak-ng for instant offline feedback on Pi
        subprocess.run(["espeak-ng", "-s140", "-v", "en-us", text], check=False)
    except Exception as e:
        print(f"Speak error: {e}")

# --- Constants ---
MODEL_PATH = "model" # Place a small Vosk model here: https://alphacephei.com/vosk/models
SAMPLERATE = 16000
BACKEND_URL = os.getenv("BACKEND_HTTP_URL", "http://localhost:8000")

class SurvivorModule:
    def __init__(self, model_path=None):
        if model_path is None:
            # Try to find the model directory relative to this script
            script_dir = os.path.dirname(os.path.realpath(__file__))
            model_path = os.path.join(script_dir, "model")
            
        if not os.path.exists(model_path) or Model is None:
            logging.warning(
                "Speech model not available; download a Vosk model into '%s'",
                model_path,
            )
            self.model = None
        else:
            self.model = Model(model_path)

        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        audio_root = os.path.join(repo_root, "Audio Files")

        self.running = True
        self.responses = {}
        self._interaction_lock = threading.Lock()
        self.audio_flow = SurvivorAudioFlow(
            audio_root=audio_root,
            model_path=model_path,
            samplerate=SAMPLERATE,
        )

    async def report_to_backend(self, transcript, question=None, answer=None, key=None):
        url = f"{BACKEND_URL}/api/survivors/interaction"
        payload = {
            "transcript": transcript,
            "responses": self.responses
        }
        if question is not None:
            payload["question"] = question
        if answer is not None:
            payload["answer"] = answer
        if key is not None:
            payload["key"] = key
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        reply = data.get("llm_reply")
                        if reply:
                            speak(reply)
        except Exception as e:
            print(f"Backend sync error: {e}")

    def run(self):
        # Keep the module alive for future extensions. The scripted flow is started
        # by ask_questions when a victim is detected.
        while self.running:
            time.sleep(0.5)

    def ask_questions(self):
        """Run the scripted Q&A flow with recorded audio prompts."""
        if not self.model:
            logging.warning("Speech model not available; skipping Q&A flow")
            return
        if not self._interaction_lock.acquire(blocking=False):
            return

        def report_cb(question, answer, key):
            question_text = question
            answer_text = answer or ""
            self.responses[f"{key}:{question_text}"] = answer_text
            transcript = f"Q: {question_text} | A: {answer_text}"
            asyncio.run(self.report_to_backend(transcript, question_text, answer_text, key))

        try:
            self.audio_flow.run_interaction(report_cb)
        finally:
            self._interaction_lock.release()

if __name__ == "__main__":
    module = SurvivorModule()
    # In a real scenario, this would be triggered by person detection
    # For now, it runs as a standalone service
    try:
        module.run()
    except KeyboardInterrupt:
        pass
