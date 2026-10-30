import os
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / 'data'
LOG_DIR = PROJECT_ROOT / 'logs'
CUDA_LIBS_DIR = PROJECT_ROOT / 'cuda_libs'
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
LLM_MODEL = os.environ.get('JUPITER_MODEL', 'qwen3.5:4b')
WHISPER_MODEL = os.environ.get('JUPITER_WHISPER', 'small')
OLLAMA_URL = os.environ.get('JUPITER_OLLAMA_URL', 'http://localhost:11434/api/chat')
DEFAULT_SAMPLE_RATE = 16000
# Where "take a screenshot" saves its PNGs (override with JUPITER_SCREENSHOT_DIR).
SCREENSHOT_DIR = os.environ.get('JUPITER_SCREENSHOT_DIR', r'C:\Users\VICTUS\OneDrive\Pictures\Screenshots')
