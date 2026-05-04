#!/usr/bin/env python3
import os
import sys
import json
import time
import queue
import logging
import threading
import requests
import asyncio
import aiohttp

# --- Configuration ---
# You need to install: pip install vosk sounddevice
try:
    import sounddevice as sd
    from vosk import Model, KaldiRecognizer
except ImportError:
    print("Please install dependencies: pip install vosk sounddevice")
    sys.exit(1)

# Voice synthesis (very lightweight for Pi 4)
# Option A: espeak-ng (robotic but fast)
# Option B: gTTS (needs internet)
# Option C: pyttsx3 (can use espeak/sapi5)
import subprocess

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

# --- State ---
q = queue.Queue()

def audio_callback(indata, frames, time, status):
    if status:
        print(status, file=sys.stderr)
    q.put(bytes(indata))

class SurvivorModule:
    def __init__(self, model_path="model"):
        if not os.path.exists(model_path):
            print(f"Please download a small model from https://alphacephei.com/vosk/models and unpack as '{model_path}'")
            # We will continue but speech recognition won't work
            self.model = None
        else:
            self.model = Model(model_path)
        self.running = True
        self.responses = {"can_move": None, "conscious": True}

    async def report_to_backend(self, transcript):
        url = f"{BACKEND_URL}/api/survivors/interaction"
        payload = {
            "transcript": transcript,
            "responses": self.responses
        }
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
        if not self.model:
            return

        with sd.RawInputStream(samplerate=SAMPLERATE, blocksize=8000, device=None,
                               dtype='int16', channels=1, callback=audio_callback):
            rec = KaldiRecognizer(self.model, SAMPLERATE)
            print("Survivor Module Active. Listening for 'help' or questions...")
            
            while self.running:
                data = q.get()
                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    text = result.get("text", "")
                    if text:
                        print(f"Detected: {text}")
                        
                        # Expanded Keyword detection logic
                        words = set(text.lower().split())
                        
                        # Emergency / Immediate Action
                        if any(w in words for w in ["help", "save", "emergency", "danger"]):
                            speak("I am ChirpyV2, the rescue rover. I have detected your emergency signal. My location and your status are being relayed to command. Stay calm.")
                            asyncio.run(self.report_to_backend(text))
                            
                        # Mobility Triage
                        elif any(w in words for w in ["move", "stuck", "trapped", "cannot"]):
                            if "no" in words or "cannot" in words or "stuck" in words:
                                self.responses["can_move"] = False
                            speak("I have logged that you are restricted. Do not attempt to move if it causes pain. Help is on the way.")
                            asyncio.run(self.report_to_backend(text))
                            
                        # Injury Triage
                        elif any(w in words for w in ["injured", "hurt", "bleeding", "pain"]):
                            speak("I am logging your injury status for the medical response team. Reassurance: Professionals are coming.")
                            asyncio.run(self.report_to_backend(text))

                        # Identity / Capability Query
                        elif any(w in words for w in ["who", "what", "robot"]):
                            speak("I am ChirpyV2, a disaster rescue rover. I am here to find survivors and coordinate with human rescue teams.")
                            asyncio.run(self.report_to_backend(text))

                        # General / AI Handover
                        else:
                            # Use OpenRouter for general interaction
                            asyncio.run(self.report_to_backend(text))

    def ask_questions(self):
        """Pre-programmed triage sequence"""
        speak("I am ChirpyV2, the rescue rover. I have detected you. Help is on the way.")
        time.sleep(1.5)
        speak("I need to check your status for the rescue teams.")
        time.sleep(1)
        speak("Are you injured?")
        asyncio.run(self.report_to_backend("SYSTEM TRIGGER: ARE YOU INJURED?"))
        time.sleep(4)
        speak("Can you move?")
        asyncio.run(self.report_to_backend("SYSTEM TRIGGER: CAN YOU MOVE?"))
        time.sleep(2)
        speak("Understood. I am staying online to monitor you. Please remain calm.")

if __name__ == "__main__":
    module = SurvivorModule()
    # In a real scenario, this would be triggered by person detection
    # For now, it runs as a standalone service
    try:
        module.run()
    except KeyboardInterrupt:
        pass
