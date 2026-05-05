#!/usr/bin/env python3
"""Test dotenv loading to verify bridge environment setup."""

import os
import sys

print("Initial DEMO_PC_AUDIO:", os.getenv("DEMO_PC_AUDIO", "NOT SET"))

try:
    from dotenv import load_dotenv
    print("✓ dotenv imported successfully")
    
    # Try absolute path first, then relative
    _env_path = r"d:\ChirpyV2\localenv"
    if os.path.exists(_env_path):
        print(f"Loading from absolute path: {_env_path}")
        result = load_dotenv(_env_path, verbose=True, override=True)
        print(f"load_dotenv result: {result}")
    else:
        _env_path = os.path.join(os.path.dirname(__file__), "..", "localenv")
        if os.path.exists(_env_path):
            print(f"Loading from relative path: {_env_path}")
            result = load_dotenv(_env_path, verbose=True, override=True)
            print(f"load_dotenv result: {result}")
        else:
            print("No localenv file found, loading from current directory")
            result = load_dotenv(verbose=True, override=True)
            print(f"load_dotenv result: {result}")
except ImportError:
    print("✗ dotenv not available")

print("\nAfter dotenv load:")
print("DEMO_PC_AUDIO:", os.getenv("DEMO_PC_AUDIO", "NOT SET"))
print("AUDIO_PLAYER:", os.getenv("AUDIO_PLAYER", "NOT SET"))
print("AUDIO_OUTPUT_BACKEND:", os.getenv("AUDIO_OUTPUT_BACKEND", "NOT SET"))
