#!/usr/bin/env python3
"""Trigger person detection in the bridge to test audio playback."""

import requests
import json
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

BRIDGE_URL = "http://localhost:8081"

def trigger_victim_detection():
    """Send a command to trigger victim detection."""
    logger.info("Triggering victim detection...")
    try:
        # Try to fetch camera feed to keep the bridge active
        resp = requests.get(f"{BRIDGE_URL}/camera.mjpeg", timeout=2)
        logger.info("Camera stream status: %s", resp.status_code)
    except Exception as e:
        logger.debug("Camera stream check: %s", e)
    
    # The detector runs automatically on camera frames, but let's wait
    # and check the status to see if anything was detected
    for i in range(20):
        try:
            resp = requests.get(f"{BRIDGE_URL}/status", timeout=2)
            if resp.status_code == 200:
                status = resp.json()
                logger.info("Bridge status: victims=%d, active_survivors=%s", 
                           len(status.get('victims', [])), 
                           status.get('survivor_active'))
                if status.get('survivor_active'):
                    logger.info("✓ Survivor interaction active!")
                    return True
        except Exception as e:
            logger.debug("Status check failed: %s", e)
        
        logger.info("Waiting for person detection... (%d/20)", i+1)
        time.sleep(1)
    
    logger.warning("No person detected after 20 seconds")
    return False

if __name__ == "__main__":
    logger.info("Connecting to bridge at %s", BRIDGE_URL)
    trigger_victim_detection()
    
    logger.info("\nWaiting for interaction to complete...")
    for i in range(30):
        try:
            resp = requests.get(f"{BRIDGE_URL}/status", timeout=2)
            if resp.status_code == 200:
                status = resp.json()
                if not status.get('survivor_active'):
                    logger.info("Interaction complete")
                    break
        except:
            pass
        time.sleep(1)
