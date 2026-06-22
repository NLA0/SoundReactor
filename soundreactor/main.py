#!/usr/bin/env python3
"""
SoundReactor - Audio fingerprint-based sound detection and action automation
Listens to ambient audio and triggers configurable actions when known sounds are detected.
"""

import sys
import os
import argparse
import logging
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from core.config import Config
from core.detector import SoundDetector
from ui.app import SoundReactorApp


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("soundreactor.log"),
        ],
    )


def main():
    parser = argparse.ArgumentParser(
        description="SoundReactor - Detect sounds and trigger actions automatically"
    )
    parser.add_argument("--headless", action="store_true", help="Run without GUI (daemon mode)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    parser.add_argument("--config", default="config.json", help="Path to config file")
    args = parser.parse_args()

    setup_logging(args.verbose)
    log = logging.getLogger("main")
    log.info("Starting SoundReactor...")

    config = Config(args.config)

    if args.headless:
        log.info("Running in headless/daemon mode. Press Ctrl+C to stop.")
        detector = SoundDetector(config)
        try:
            detector.start()
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("Shutting down...")
            detector.stop()
    else:
        app = SoundReactorApp(config)
        app.run()


if __name__ == "__main__":
    main()