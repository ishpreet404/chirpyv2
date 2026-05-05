#!/usr/bin/env python3
"""Direct test of SurvivorAudioFlow to verify audio playback."""

import os
import sys
import logging

# Add pi_bridge to path FIRST
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "pi_bridge"))

# Load localenv BEFORE importing survivor_audio_flow
os.chdir("d:\\ChirpyV2")
if os.path.exists("localenv"):
    print("Loading localenv BEFORE imports...")
    with open("localenv") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()
                print(f"  {key.strip()}={val.strip()}")

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

def test_audio_flow():
    """Direct test of audio playback."""
    from survivor_audio_flow import SurvivorAudioFlow
    
    # Initialize audio flow
    audio_root = os.path.join(os.getcwd(), "Audio Files")
    logger.info("Audio root: %s (exists: %s)", audio_root, os.path.isdir(audio_root))
    
    # Use a dummy model path
    model_path = os.path.join(os.getcwd(), "pi_bridge", "model")
    
    flow = SurvivorAudioFlow(
        audio_root=audio_root,
        model_path=model_path,
        samplerate=16000,
    )
    
    # Try to play a single audio file
    test_file = os.path.join(audio_root, "Are you Ok", "QUES.mp3")
    logger.info("\n=== Testing audio playback ===")
    logger.info("Playing: %s", test_file)
    
    success = flow._play_audio(test_file)
    logger.info("Playback result: %s", success)
    
    if success:
        logger.info("✓ Audio playback succeeded!")
    else:
        logger.error("✗ Audio playback failed!")
        return False
    
    # Try YES response
    logger.info("\n=== Testing YES response ===")
    test_file = os.path.join(audio_root, "Are you Ok", "YES.mp3")
    logger.info("Playing: %s", test_file)
    success = flow._play_audio(test_file)
    if success:
        logger.info("✓ Audio playback succeeded!")
    else:
        logger.error("✗ Audio playback failed!")
        return False
    
    return True

if __name__ == "__main__":
    logger.info("Working directory: %s", os.getcwd())
    
    try:
        result = test_audio_flow()
        if result:
            logger.info("\n✓ All audio tests passed!")
        else:
            logger.error("\n✗ Audio tests failed!")
    except Exception as e:
        logger.error("Test crashed: %s", e, exc_info=True)
