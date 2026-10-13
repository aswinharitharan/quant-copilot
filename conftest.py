import sys
from pathlib import Path

# Add project root to sys.path so tests can import from 'src' without PYTHONPATH hacks
ROOT_DIR = Path(__file__).parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
