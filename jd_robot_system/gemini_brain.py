"""
Gemini integration: understands natural language commands, returns a
spoken reply and (optionally) a matched action. Handles Google retiring
model names via a fallback list, and transient network errors via
retry-with-backoff, so a single deprecated model or network blip doesn't
take down the whole system.
"""
import time
import requests
from config import (
    GEMINI_API_KEY, GEMINI_MODEL_CANDIDATES, GEMINI_TIMEOUT,
    GEMINI_MAX_RETRIES, GEMINI_RETRY_DELAY,
)


def list_available_models():
    """Diagnostic: prints every model this API key can actually use for
    generateContent right now, instead of guessing model names one by one.
    Run with:
        python -c "from gemini_brain import list_available_models; list_available_models()"
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        if not response.ok:
            print(f"ListModels failed: HTTP {response.status_code}\n{response.text}")
            return
        data = response.json()
        for model in data.get("models", []):
            name = model.get("name", "")
            methods = model.get("supportedGenerationMethods", [])
            if "generateContent" in methods:
                print(name)
    except Exception as e:
        print(f"ListModels failed: {e}")


def _call_once(model_name, prompt):
    """Single attempt at one model. Returns (result_text, error_kind) where
    error_kind is None (success), 'not_found' (try next model), or
    'other' (network/timeout/etc - worth retrying same model)."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        response = requests.post(url, json=payload, timeout=GEMINI_TIMEOUT)
    except requests.exceptions.RequestException as e:
        print(f"  [Gemini] network error on {model_name}: {e}")
        return None, "other"

    if response.status_code == 404:
        print(f"  [Gemini] {model_name} unavailable (404) - trying next model...")
        return None, "not_found"
    if not response.ok:
        print(f"  [Gemini] HTTP {response.status_code} on {model_name}: {response.text}")
        return None, "other"

    try:
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip(), None
    except (KeyError, IndexError, ValueError) as e:
        print(f"  [Gemini] couldn't parse response from {model_name}: {e}")
        return None, "other"


def _call_gemini(prompt):
    for model_name in GEMINI_MODEL_CANDIDATES:
        for attempt in range(1, GEMINI_MAX_RETRIES + 1):
            result_text, error_kind = _call_once(model_name, prompt)
            if error_kind is None:
                return result_text
            if error_kind == "not_found":
                break  # no point retrying a model that doesn't exist - move to next model
            print(f"  [Gemini] retrying {model_name} (attempt {attempt}/{GEMINI_MAX_RETRIES})...")
            time.sleep(GEMINI_RETRY_DELAY)
    return None


def assess_alert(situation_description):
    """
    Given a short description of a triggered surveillance condition (who,
    what, time of day), asks Gemini to judge how concerning it actually is
    and produce an appropriate spoken alert line - or decide it's not
    worth alerting about at all. Reuses the same model fallback/retry
    infrastructure as understand().

    Returns (should_alert: bool, spoken_line: str_or_None).
    """
    prompt = f"""You are JD, a home security-aware robot. A monitoring system just detected this situation:

{situation_description}

Judge how concerning this actually is, considering context like time of
day and whether the person is known. Respond in EXACTLY this two-line
format, nothing else:
ALERT: <yes or no>
LINE: <a short, natural spoken alert matching the urgency, or NONE if ALERT is no>

Use judgment - a known person calmly holding a knife in a kitchen at a
normal hour is NOT concerning and should not alert. An unknown person, or
anyone holding something sharp late at night, IS concerning and should
alert with appropriately urgent wording."""

    result_text = _call_gemini(prompt)

    if result_text is None:
        # Gemini unavailable - default to alerting plainly rather than
        # staying silent on a potentially real security event.
        return True, "I detected something you should check on."

    should_alert = False
    spoken_line = None
    for line in result_text.splitlines():
        line = line.strip()
        if line.startswith("ALERT:"):
            should_alert = line[len("ALERT:"):].strip().lower().startswith("y")
        elif line.startswith("LINE:"):
            value = line[len("LINE:"):].strip()
            spoken_line = None if value.upper() == "NONE" else value

    return should_alert, spoken_line


def ambient_comment(event_description, scene_summary=None):
    """
    Given a description of something that just changed in the scene, asks
    Gemini whether a natural, non-annoying companion robot would say
    something right now - or nothing, which should be the common case.
    NOT safety-critical, so this fails silently (returns None) if
    Gemini/network is unavailable, rather than forcing any fallback.

    Returns a comment string, or None (meaning: say nothing this time).
    """
    scene_block = f"\nFull current scene: {scene_summary}\n" if scene_summary else ""

    prompt = f"""You are JD, a friendly companion robot that notices things but
does NOT narrate constantly - most of the time you should say NOTHING,
only commenting when it's genuinely natural, the way a person in the
room would occasionally remark on something without narrating every
moment.

Something just changed: {event_description}
{scene_block}
Respond in EXACTLY this format, nothing else:
COMMENT: <a short, natural spoken remark, or exactly NONE if nothing is worth saying>

Be conservative - routine, expected, or minor changes should get NONE.
Only produce a real comment for things a normal person would actually
remark on out loud."""

    result_text = _call_gemini(prompt)
    if result_text is None:
        return None  # network/Gemini unavailable - just skip silently

    for line in result_text.splitlines():
        line = line.strip()
        if line.startswith("COMMENT:"):
            value = line[len("COMMENT:"):].strip()
            return None if value.upper() == "NONE" else value
    return None


def understand(text, describe_all_known, scene_summary=None, history_block=None):
    """
    Single Gemini call that returns BOTH:
      - a short natural spoken reply (JD 'answering intelligently')
      - an optional action match, ONLY if the request reasonably maps to a
        real known action - never invented. The caller must still validate
        any match against the real known-safe lists before executing it.

    scene_summary: optional plain-English description of what JD's vision
    pipeline currently sees.
    history_block: optional recent-conversation text from
    conversation_memory.get_history_block(), giving Gemini short-term
    memory of the last few exchanges this session.

    Returns (reply_text_or_None, (category, name)_or_None).
    """
    vision_block = f'\nWhat JD currently sees: {scene_summary}\n' if scene_summary else ""
    memory_block = f'\n{history_block}\n' if history_block else ""

    prompt = f"""You are JD, a friendly robot. A person just said to you: "{text}"
{vision_block}{memory_block}

{describe_all_known()}

Respond in EXACTLY this two-line format, nothing else:
REPLY: <a short, natural, spoken-style reply from JD, 1-2 sentences>
MATCH: <category>|<name>

The category MUST be exactly one of these three words, lowercase, nothing
else: movement, sound, light. Do not use any other label (not "Movements",
not "Light effects", not capitalized) - it must match one of those three
words exactly or validation will reject an otherwise-correct match.

For the MATCH line: pick the CLOSEST real action from the lists above that
reasonably represents what the person asked for - it does not need to be a
literal name match (e.g. someone asking JD to act like a bee or bird could
reasonably match "Fly"). Use your judgment for creative or descriptive
requests, but only pick something if there's a genuinely reasonable
connection - don't force a match onto something unrelated.

If nothing on the list reasonably fits, put exactly:
MATCH: NONE

Never invent an action name that isn't on the list above - only ever pick
from the real categories and names given."""

    result_text = _call_gemini(prompt)

    if result_text is None:
        # Every model/attempt failed - still give a graceful spoken fallback
        # instead of going silent, so JD never looks "broken" to whoever's
        # watching.
        return "Sorry, I'm having trouble thinking right now. Try again in a moment.", None

    print(f"  [debug] raw Gemini output: {result_text!r}")

    reply = None
    action = None
    for line in result_text.splitlines():
        line = line.strip()
        if line.startswith("REPLY:"):
            reply = line[len("REPLY:"):].strip()
        elif line.startswith("MATCH:"):
            match_val = line[len("MATCH:"):].strip()
            if match_val and match_val != "NONE":
                try:
                    category, name = match_val.split("|", 1)
                    name = name.strip().strip('"').strip("'")
                    category = category.strip().strip('"').strip("'").lower()
                    if category == "sound":
                        name = int(name)
                    action = (category, name)
                except (ValueError, IndexError):
                    action = None

    return reply, action