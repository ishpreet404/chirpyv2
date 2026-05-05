#!/usr/bin/env python3
"""Test audio file resolution for bridge running on Windows."""

import os
import sys
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

def _resolve_audio_root() -> str:
    """Replicate the logic from survivor_module.py"""
    explicit = os.getenv("AUDIO_ROOT", "").strip()
    if explicit and os.path.isdir(explicit):
        logger.info("Using explicit AUDIO_ROOT: %s", explicit)
        return explicit
    else:
        logger.info("Explicit AUDIO_ROOT not available or doesn't exist: %r", explicit)

    script_dir = os.path.dirname(os.path.realpath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, ".."))
    logger.info("Script dir: %s", script_dir)
    logger.info("Repo root: %s", repo_root)
    
    candidates = [
        os.path.join(repo_root, "Audio Files"),
        os.path.join(repo_root, "audio files"),
        os.path.join(script_dir, "Audio Files"),
        os.path.join(script_dir, "audio files"),
    ]
    
    for candidate in candidates:
        logger.info("Checking candidate: %s (exists: %s)", candidate, os.path.isdir(candidate))
        if os.path.isdir(candidate):
            logger.info("✓ Found audio root: %s", candidate)
            return candidate

    logger.warning("No audio root found; returning fallback: %s", os.path.join(repo_root, "Audio Files"))
    return os.path.join(repo_root, "Audio Files")

def main():
    os.chdir("d:\\ChirpyV2\\pi_bridge")  # Simulate running from pi_bridge dir
    logger.info("Working directory: %s", os.getcwd())
    
    # Load localenv to set AUDIO_ROOT
    if os.path.exists("../localenv"):
        logger.info("Loading ../localenv...")
        with open("../localenv") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()
        logger.info("Loaded environment variables")
    
    # Try to resolve audio root
    audio_root = _resolve_audio_root()
    logger.info("Resolved audio root: %s", audio_root)
    logger.info("Exists: %s", os.path.isdir(audio_root))
    
    # Try to access key audio files
    key_files = [
        os.path.join(audio_root, "Are you Ok", "QUES.mp3"),
        os.path.join(audio_root, "Are you Ok", "YES.mp3"),
        os.path.join(audio_root, "Are you Ok", "NO.mp3"),
    ]
    
    logger.info("Checking key audio files:")
    all_exist = True
    for fpath in key_files:
        exists = os.path.exists(fpath)
        logger.info("  %s: %s", fpath, "✓" if exists else "✗")
        all_exist = all_exist and exists
    
    if all_exist:
        logger.info("\n✓ All key audio files found!")
    else:
        logger.error("\n✗ Some audio files missing!")
    
    # List the Audio Files directory structure
    logger.info("\nDirectory structure:")
    for root, dirs, files in os.walk(audio_root):
        level = root.replace(audio_root, "").count(os.sep)
        indent = " " * 2 * level
        logger.info("%s%s/", indent, os.path.basename(root))
        subindent = " " * 2 * (level + 1)
        for file in files[:3]:  # Show first 3 files per dir
            logger.info("%s%s", subindent, file)
        if len(files) > 3:
            logger.info("%s... and %d more files", subindent, len(files) - 3)

if __name__ == "__main__":
    main()
