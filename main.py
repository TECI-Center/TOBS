#!/usr/bin/env python3
"""Entry point for the TOBS dual-camera recorder."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from tobs.app import run  # noqa: E402

if __name__ == "__main__":
    run()
