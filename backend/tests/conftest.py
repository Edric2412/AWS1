import pytest
import os
import sys
from pathlib import Path

# Add the parent directory of 'backend' to sys.path to allow absolute imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Sets up test environment variables."""
    os.environ["VLLM_API_URL"] = "http://localhost:8000/v1"
    os.environ["OLLAMA_API_URL"] = "http://localhost:11434"
    os.environ["OLLAMA_MODEL"] = "qwen3.5:1.5b"
    os.environ["VLLM_MODEL"] = "Qwen/Qwen3.5-8B-Instruct"
