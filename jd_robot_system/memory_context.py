"""
Bridges the witness diary into the Gemini prompt. main.py treats this
exactly like scene_context: optional, read fresh per command, and an
empty or missing diary just means the prompt goes out without a memory
section. Current scene (scene_context) and past sightings (this module)
stay separate blocks so the model can't confuse "seeing now" with
"saw earlier".
"""
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from memory.witness_store import diary_context


def get_memory_block():
    """Formatted diary block for the prompt, or None if nothing has been
    recorded yet."""
    return diary_context() or None
