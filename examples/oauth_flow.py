#!/usr/bin/env python3
"""Compatibility entry point for the secure OAuth flow."""

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))
    runpy.run_path(str(project_root / "oauth_flow.py"), run_name="__main__")
