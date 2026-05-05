#!/usr/bin/env python3
import json
import logging
import os
import queue
import shutil
import subprocess
import time
from typing import Callable, Optional

try:
    import sounddevice as sd
    from vosk import KaldiRecognizer, Model
except ImportError:
    sd = None
    KaldiRecognizer = None
    Model = None
    logging.warning("Missing vosk/sounddevice; survivor audio flow disabled")

YES_WORDS = {
    "yes", "yeah", "yep", "yup", "ok", "okay", "affirmative", "sure"
}
NO_WORDS = {"no", "nope", "negative", "nah"}

HELP_WORDS = {"help", "save", "emergency", "danger"}
PANIC_WORDS = {"panic", "scared", "afraid", "terrified", "please"}

FALLBACK_UNCLEAR = (
    "Sorry, I could not understand clearly. Please answer with yes or no if possible."
)
FALLBACK_NO_RESPONSE = (
    "No response detected. I will keep your location marked and notify the rescue team."
)
FALLBACK_HELP = (
    "Help has been notified. Please stay calm. I will remain nearby and continue sharing your location."
)
FALLBACK_PANIC = (
    "Please try to stay calm. You are not alone. Rescue support is on the way."
)


def _safe_basename(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _is_mp3(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == ".mp3"


class SurvivorAudioFlow:
    def __init__(
        self,
        audio_root: str,
        model_path: str,
        samplerate: int = 16000,
        response_timeout_s: float = 8.0,
    ):
        self.audio_root = audio_root
        self.samplerate = samplerate
        self.response_timeout_s = response_timeout_s
        self._queue: queue.Queue[bytes] = queue.Queue()

        if Model is not None and os.path.exists(model_path):
            self.model = Model(model_path)
        else:
            self.model = None

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logging.warning("Audio input status: %s", status)
        self._queue.put(bytes(indata))

    def _play_audio(self, path: str) -> bool:
        if not os.path.exists(path):
            logging.warning("Missing audio file: %s", path)
            return False

        if _is_mp3(path):
            if shutil.which("mpg123"):
                subprocess.run(["mpg123", "-q", path], check=False)
                return True
            if shutil.which("ffplay"):
                subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path], check=False)
                return True

        if shutil.which("aplay"):
            subprocess.run(["aplay", path], check=False)
            return True

        logging.warning("No suitable audio player found for %s", path)
        return False

    def _speak_fallback(self, text: str):
        espeak = shutil.which("espeak-ng") or shutil.which("espeak")
        if espeak:
            subprocess.run([espeak, "-s140", "-v", "en-us", text], check=False)
        else:
            logging.warning("No TTS engine found. Install espeak-ng for fallback speech.")

    def _listen_for_text(self) -> str:
        if not self.model or sd is None or KaldiRecognizer is None:
            return ""

        rec = KaldiRecognizer(self.model, self.samplerate)
        start = time.time()
        text = ""

        with sd.RawInputStream(
            samplerate=self.samplerate,
            blocksize=8000,
            dtype="int16",
            channels=1,
            callback=self._audio_callback,
        ):
            while time.time() - start < self.response_timeout_s:
                try:
                    data = self._queue.get(timeout=0.25)
                except queue.Empty:
                    continue

                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    text = result.get("text", "").strip()
                    if text:
                        break

        return text

    def _detect_yes_no(self, text: str) -> str:
        if not text:
            return "no_response"
        words = set(text.lower().split())
        if words & YES_WORDS:
            return "yes"
        if words & NO_WORDS:
            return "no"
        return "unclear"

    def _maybe_play_fallback(self, text: str, reason: str):
        if reason == "no_response":
            self._speak_fallback(FALLBACK_NO_RESPONSE)
            return
        if reason == "unclear":
            self._speak_fallback(FALLBACK_UNCLEAR)
            return

        words = set(text.lower().split())
        if words & HELP_WORDS:
            self._speak_fallback(FALLBACK_HELP)
        elif words & PANIC_WORDS:
            self._speak_fallback(FALLBACK_PANIC)

    def _ordered_questions_after(self) -> list[str]:
        folder = os.path.join(self.audio_root, "Questions after")
        if not os.path.isdir(folder):
            return []

        desired = [
            "Are you hurt or injured anywhere.mp3",
            "Can you move your hands or legs.mp3",
            "Are you having difficulty breathing.mp3",
            "Can you stay where you are until the rescue team arrives.mp3",
        ]

        available = set(os.listdir(folder))
        ordered = [os.path.join(folder, name) for name in desired if name in available]
        remaining = [
            os.path.join(folder, name)
            for name in sorted(available)
            if name not in desired and name.lower().endswith(".mp3")
        ]

        # Avoid repeating the initial question if it exists in this folder.
        filtered = [p for p in ordered + remaining if "are you okay" not in p.lower()]
        return filtered

    def run_interaction(self, report_cb: Callable[[str, str, str], None]):
        if not self.model:
            logging.warning("Vosk model missing; speech-to-text disabled")
            return

        ok_folder = os.path.join(self.audio_root, "Are you Ok")
        ok_question = os.path.join(ok_folder, "QUES.mp3")
        ok_yes = os.path.join(ok_folder, "YES.mp3")
        ok_no = os.path.join(ok_folder, "NO.mp3")

        # 1) Are you ok?
        self._play_audio(ok_question)
        text = self._listen_for_text()
        report_cb("Are you ok", text, "are_you_ok")
        yn = self._detect_yes_no(text)
        if yn == "yes":
            self._play_audio(ok_yes)
        elif yn == "no":
            self._play_audio(ok_no)
        else:
            self._maybe_play_fallback(text, yn)

        # 2) Follow-up questions (record only)
        for q_path in self._ordered_questions_after():
            self._play_audio(q_path)
            answer = self._listen_for_text()
            report_cb(_safe_basename(q_path), answer, "follow_up")
            if not answer:
                self._maybe_play_fallback(answer, "no_response")

        # 3) Ask name
        name_folder = os.path.join(self.audio_root, "Asking name")
        name_path = os.path.join(name_folder, "Can you tell me your name.mp3")
        self._play_audio(name_path)
        name_answer = self._listen_for_text()
        report_cb("name", name_answer, "name")
        if not name_answer:
            self._maybe_play_fallback(name_answer, "no_response")

        # 4) Last question
        last_folder = os.path.join(self.audio_root, "Last Ques")
        last_path = os.path.join(last_folder, "Is there anyone else near you who needs help.mp3")
        self._play_audio(last_path)
        last_answer = self._listen_for_text()
        report_cb("anyone_else", last_answer, "anyone_else")

        # 5) Final response
        final_path = os.path.join(
            self.audio_root,
            "Do not panic. I have marked your location and alerted the rescue team. Help is on the way.mp3",
        )
        self._play_audio(final_path)
