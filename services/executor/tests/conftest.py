"""Make the executor package importable and point the storage at a temp dir.

Only pure functions are tested here: no MongoDB, Redis or Socket.IO is needed.
"""

import os
import sys
from pathlib import Path

EXECUTOR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EXECUTOR_DIR))
sys.path.insert(0, str(EXECUTOR_DIR / "python"))

os.environ.setdefault("STORAGE", str(EXECUTOR_DIR / "tests" / "_storage"))
