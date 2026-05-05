#!/usr/bin/env python3
import json
import logging
import os
import queue
import shutil
import subprocess
import time
from typing import Callable

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

AUDIO_PLAYER = os.getenv("AUDIO_PLAYER", "mpg123").strip().lower()
AUDIO_OUTPUT_BACKEND = os.getenv("AUDIO_OUTPUT_BACKEND", "alsa").strip().lower()
AUDIO_OUTPUT_DEVICE = os.getenv("AUDIO_OUTPUT_DEVICE", "").strip()
DEMO_PC_AUDIO = os.getenv("DEMO_PC_AUDIO", "").strip().lower() in ("1", "true", "yes")


def _which(name: str) -> str | None:
    return shutil.which(name) or (f"/usr/bin/{name}" if os.path.exists(f"/usr/bin/{name}") else None)

def _safe_basename(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _is_mp3(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == ".mp3"


def _play_via_sounddevice(path: str) -> bool:
    """Decode and play audio via sounddevice for PC demo environments.

    Uses ffmpeg to decode MP3 into raw PCM if necessary, or falls back to
    pysoundfile if available. This avoids spawning ALSA/JACK-bound players.
    """
    if sd is None:
        logging.warning("sounddevice not available; cannot play via PC backend")
        return False

    ffmpeg = _which("ffmpeg")
    try:
        if _is_mp3(path) and ffmpeg:
            try:
                import numpy as np
            except Exception:
                logging.warning("numpy required for ffmpeg->sounddevice playback")
                return False

            cmd = [
                ffmpeg,
                "-i",
                path,
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-",
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode != 0 or not proc.stdout:
                logging.warning("ffmpeg decode failed rc=%s stderr=%s", proc.returncode, (proc.stderr or b"").decode(errors="ignore")[:300])
                return False

            data = np.frombuffer(proc.stdout, dtype=np.int16)
            try:
                frames = data.reshape(-1, 2)
            except Exception:
                # If mono, reshape may fail; play raw buffer
                try:
                    sd.play(data, samplerate=44100)
                    sd.wait()
                    return True
                except Exception as e:
                    logging.warning("sounddevice playback failed: %s", e)
                    return False

            try:
                sd.play(frames, samplerate=44100)
                sd.wait()
                return True
            except Exception as e:
                logging.warning("sounddevice playback failed: %s", e)
                return False

        # Try soundfile-based playback for other formats
        try:
            import soundfile as sf
            data, sr = sf.read(path, dtype="float32")
            sd.play(data, sr)
            sd.wait()
            return True
        except Exception:
            logging.debug("soundfile playback unavailable or failed; falling back")
            return False
    except Exception as e:
        logging.warning("Exception during sounddevice playback: %s", e)
        return False


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

        # If running a PC demo, prefer direct playback via sounddevice
        if DEMO_PC_AUDIO and sd is not None:
            try:
                ok = _play_via_sounddevice(path)
                if ok:
                    return True
            except Exception as e:
                logging.warning("PC demo sounddevice playback failed: %s", e)

        commands = []
        mpg123 = _which("mpg123")
        ffplay = _which("ffplay")
        aplay = _which("aplay")

        if _is_mp3(path) and AUDIO_PLAYER in ("auto", "mpg123") and mpg123:
            # If demoing on PC, avoid ALSA-specific flags which can trigger JACK.
            if DEMO_PC_AUDIO or AUDIO_OUTPUT_BACKEND in ("pc", "none"):
                commands.append([mpg123, "-q", path])
            else:
                # Prefer ALSA with the known-working default device first.
                device = AUDIO_OUTPUT_DEVICE or "default"
                commands.append([mpg123, "-o", AUDIO_OUTPUT_BACKEND, "-a", device, "-q", path])

                # Some builds accept the device directly once ALSA is selected.
                commands.append([mpg123, "-a", device, "-q", path])

                # Keep a small fallback set in case the named device is unavailable.
                commands.append([mpg123, "-q", path])
        if _is_mp3(path) and AUDIO_PLAYER in ("auto", "ffplay") and ffplay:
            # ffplay is generally safe cross-platform and doesn't require ALSA flags
            commands.append([ffplay, "-nodisp", "-autoexit", "-loglevel", "error", path])
        if not _is_mp3(path) and AUDIO_PLAYER in ("auto", "aplay") and aplay:
            cmd = [aplay]
            if AUDIO_OUTPUT_DEVICE:
                cmd.extend(["-D", AUDIO_OUTPUT_DEVICE])
            cmd.append(path)
            commands.append(cmd)
            if AUDIO_OUTPUT_DEVICE:
                commands.append([aplay, path])

        if not commands:
            logging.warning(
                "No audio player command available. AUDIO_PLAYER=%r AUDIO_OUTPUT_BACKEND=%r PATH=%r mpg123=%r ffplay=%r aplay=%r",
                AUDIO_PLAYER,
                AUDIO_OUTPUT_BACKEND,
                os.getenv("PATH", ""),
                mpg123,
                ffplay,
                aplay,
            )
            return False

        for cmd in commands:
            logging.info("Playing audio: %s", " ".join(cmd))
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                return True
            logging.warning(
                "Audio player failed rc=%s stderr=%s",
                result.returncode,
                (result.stderr or result.stdout or "").strip()[:300],
            )

        logging.warning(
            "No audio output worked for %s. Install mpg123 and set AUDIO_OUTPUT_DEVICE if Bluetooth is not default.",
            path,
        )
        return False

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
        logging.info("No prerecorded fallback for response reason=%s text=%r", reason, text)

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
            logging.warning("Vosk model missing; prompts will play but responses will not be transcribed")

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
