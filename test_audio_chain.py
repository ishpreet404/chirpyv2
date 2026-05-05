#!/usr/bin/env python3
"""Test audio playback chain for PC demo mode debugging."""

import logging
import os
import subprocess
import sys
import time

# Set up debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

def test_sounddevice_import():
    """Test if sounddevice is available."""
    logger.info("=== Testing sounddevice import ===")
    try:
        import sounddevice as sd
        logger.info("✓ sounddevice imported successfully")
        logger.info("  Version: %s", sd.__version__)
        return True
    except ImportError as e:
        logger.error("✗ sounddevice import failed: %s", e)
        return False

def test_sounddevice_devices():
    """List available audio devices."""
    logger.info("=== Testing sounddevice device enumeration ===")
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        default = sd.default.device
        logger.info("✓ Found %d audio devices", len(devices) if isinstance(devices, list) else 1)
        logger.info("  Default device: %s", default)
        for i, dev in enumerate(devices if isinstance(devices, list) else [devices]):
            logger.info("    [%d] %s", i, dev)
        return True
    except Exception as e:
        logger.error("✗ Device enumeration failed: %s", e, exc_info=True)
        return False

def test_sounddevice_sine_wave():
    """Test playback with a simple sine wave (no file needed)."""
    logger.info("=== Testing sounddevice sine wave playback ===")
    try:
        import sounddevice as sd
        import numpy as np
        
        # Generate 1 second of 440 Hz sine wave
        sr = 44100
        duration = 1.0
        freq = 440
        t = np.arange(int(sr * duration)) / sr
        wave = (np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
        
        logger.info("Generated %d samples at %d Hz", len(wave), sr)
        logger.info("Playing 1-second 440 Hz sine wave...")
        
        start = time.time()
        sd.play(wave, samplerate=sr)
        sd.wait()
        elapsed = time.time() - start
        
        logger.info("✓ Playback completed in %.2f seconds", elapsed)
        return True
    except Exception as e:
        logger.error("✗ Sine wave playback failed: %s", e, exc_info=True)
        return False

def test_ffmpeg_available():
    """Check if ffmpeg is available."""
    logger.info("=== Testing ffmpeg availability ===")
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0]
            logger.info("✓ ffmpeg available: %s", version_line)
            return True
    except FileNotFoundError:
        logger.error("✗ ffmpeg not found in PATH")
        return False
    except Exception as e:
        logger.error("✗ ffmpeg check failed: %s", e)
        return False

def test_ffmpeg_decode(mp3_path):
    """Test ffmpeg MP3 decoding."""
    logger.info("=== Testing ffmpeg MP3 decode ===")
    if not os.path.exists(mp3_path):
        logger.error("✗ Test MP3 file not found: %s", mp3_path)
        return False
    
    try:
        cmd = [
            "ffmpeg",
            "-i", mp3_path,
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "2",
            "-"
        ]
        logger.info("Running: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        
        if result.returncode != 0:
            logger.error("✗ ffmpeg decode failed rc=%s", result.returncode)
            logger.error("  stderr: %s", result.stderr.decode(errors='ignore')[:500])
            return False
        
        if not result.stdout:
            logger.error("✗ ffmpeg produced no output")
            return False
        
        logger.info("✓ ffmpeg decode successful: %d bytes of PCM output", len(result.stdout))
        return True
    except Exception as e:
        logger.error("✗ ffmpeg decode failed: %s", e, exc_info=True)
        return False

def test_numpy_available():
    """Test if numpy is available."""
    logger.info("=== Testing numpy availability ===")
    try:
        import numpy as np
        logger.info("✓ numpy available: %s", np.__version__)
        return True
    except ImportError as e:
        logger.error("✗ numpy not available: %s", e)
        return False

def test_ffmpeg_to_sounddevice(mp3_path):
    """Test the full ffmpeg decode + sounddevice playback chain."""
    logger.info("=== Testing full ffmpeg + sounddevice chain ===")
    if not os.path.exists(mp3_path):
        logger.error("✗ Test MP3 file not found: %s", mp3_path)
        return False
    
    try:
        import sounddevice as sd
        import numpy as np
        
        cmd = [
            "ffmpeg",
            "-i", mp3_path,
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "2",
            "-"
        ]
        logger.info("Decoding: %s", mp3_path)
        proc = subprocess.run(cmd, capture_output=True, timeout=10)
        
        if proc.returncode != 0:
            logger.error("✗ ffmpeg failed: %s", proc.stderr.decode(errors='ignore')[:300])
            return False
        
        logger.info("Loaded %d bytes from ffmpeg", len(proc.stdout))
        
        data = np.frombuffer(proc.stdout, dtype=np.int16)
        logger.info("Converted to %d int16 samples", len(data))
        
        frames = data.reshape(-1, 2)
        logger.info("Reshaped to %s (stereo frames)", frames.shape)
        
        logger.info("Playing audio via sounddevice...")
        start = time.time()
        sd.play(frames, samplerate=44100)
        sd.wait()
        elapsed = time.time() - start
        
        logger.info("✓ Playback completed in %.2f seconds", elapsed)
        return True
    except Exception as e:
        logger.error("✗ Chain test failed: %s", e, exc_info=True)
        return False

def main():
    logger.info("Starting audio chain diagnostic tests...")
    logger.info("Python: %s", sys.version.split('\n')[0])
    logger.info("Working directory: %s", os.getcwd())
    
    tests_passed = 0
    tests_total = 0
    
    # Run tests
    tests = [
        ("sounddevice import", test_sounddevice_import, ()),
        ("sounddevice devices", test_sounddevice_devices, ()),
        ("sounddevice sine wave", test_sounddevice_sine_wave, ()),
        ("ffmpeg available", test_ffmpeg_available, ()),
        ("numpy available", test_numpy_available, ()),
    ]
    
    for name, func, args in tests:
        tests_total += 1
        try:
            if func(*args):
                tests_passed += 1
            logger.info("")
        except Exception as e:
            logger.error("Test crashed: %s", e, exc_info=True)
            logger.info("")
    
    # Look for test MP3 files
    audio_paths = [
        r"D:\ChirpyV2\Audio Files\Are you Ok\QUES.mp3",
        r"D:\ChirpyV2\Audio Files\Are you Ok\YES.mp3",
    ]
    
    for mp3_path in audio_paths:
        if os.path.exists(mp3_path):
            logger.info("Found test MP3: %s", mp3_path)
            tests_total += 1
            if test_ffmpeg_decode(mp3_path):
                tests_passed += 1
            logger.info("")
            
            tests_total += 1
            if test_ffmpeg_to_sounddevice(mp3_path):
                tests_passed += 1
            logger.info("")
            break
    
    logger.info("=== Summary ===")
    logger.info("Passed: %d / %d", tests_passed, tests_total)
    if tests_passed == tests_total:
        logger.info("✓ All tests passed! Audio chain should work.")
    else:
        logger.error("✗ Some tests failed. Check the output above.")

if __name__ == "__main__":
    main()
