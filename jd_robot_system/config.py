"""
Central configuration for the JD robot system.
Edit values here - nothing else in the project should normally need
editing for basic setup.
"""

# --- ARC connection ---
import os


ARC_HOST = "127.0.0.1"
ARC_PORT = 6666
CONNECT_TIMEOUT = 5.0

# --- Gemini ---
# Get a free key at https://aistudio.google.com/apikey
# MUST be a real key - the placeholder below will fail every Gemini call.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "PUT_YOUR_KEY_HERE")

# Tried in order - if one gets deprecated/restricted (HTTP 404), the next
# is tried automatically. If ALL of them ever fail, run:
#   python -c "from gemini_brain import list_available_models; list_available_models()"
# to see what your key currently has access to, and update this list.
GEMINI_MODEL_CANDIDATES = [
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-flash-latest",
]
GEMINI_TIMEOUT = 20.0       # seconds per attempt
GEMINI_MAX_RETRIES = 2      # attempts per model before moving to the next one
GEMINI_RETRY_DELAY = 1.5    # seconds paused between retries

# --- Speech input ---
# Voice commands come from ARC's own Speech Recognition skill (listening
# through your laptop's microphone, configured inside ARC itself via its
# "Setup Microphone" button) - NOT a separate Python microphone library.
# This just polls the $SpeechPhrase variable ARC updates when it hears
# something.
SPEECH_POLL_INTERVAL = 0.3  # seconds between polls of $SpeechPhrase
