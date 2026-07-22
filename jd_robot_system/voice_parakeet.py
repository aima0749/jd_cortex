"""
Live microphone speech-to-text using local NVIDIA Parakeet TDT (via sherpa-onnx).
Records from whatever Windows has set as the default input device (laptop mic
or headphone mic - switch it in Windows Sound settings, no code change needed).
Records until silence, then transcribes the whole clip - low hallucination,
fast, and runs fully offline.

PUSH-TO-TALK: listen_for_command() waits for an Enter keypress before
recording, rather than listening continuously. This is deliberate - a
continuously-open mic picks up JD's own spoken TTS replies (self-feedback)
or nearby bystanders talking, and misfires commands from either. Requiring
an explicit trigger each time eliminates both problems entirely.
"""
import numpy as np
import sounddevice as sd
import sherpa_onnx

MODEL_DIR = "../voice_model/parakeet"
SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 0.01    # raise if it cuts off too early in a noisy room
SILENCE_DURATION = 1.2      # seconds of quiet before we stop recording
MAX_RECORD_SECONDS = 15

_recognizer = None


def _get_recognizer():
    global _recognizer
    if _recognizer is None:
        print("Loading Parakeet model...")
        _recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=f"{MODEL_DIR}/encoder.int8.onnx",
            decoder=f"{MODEL_DIR}/decoder.int8.onnx",
            joiner=f"{MODEL_DIR}/joiner.int8.onnx",
            tokens=f"{MODEL_DIR}/tokens.txt",
            num_threads=2,
            sample_rate=SAMPLE_RATE,
            feature_dim=80,
            decoding_method="greedy_search",
            model_type="nemo_transducer",
        )
        print("Parakeet loaded.")
    return _recognizer


def _record_until_silence():
    print("Listening... (speak now)")
    chunks = []
    silence_chunks_needed = int(SILENCE_DURATION * SAMPLE_RATE / 1024)
    silent_count = 0
    max_chunks = int(MAX_RECORD_SECONDS * SAMPLE_RATE / 1024)

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32") as stream:
        started_talking = False
        for _ in range(max_chunks):
            data, _ = stream.read(1024)
            volume = np.abs(data).mean()
            chunks.append(data.copy())

            if volume > SILENCE_THRESHOLD:
                started_talking = True
                silent_count = 0
            elif started_talking:
                silent_count += 1
                if silent_count > silence_chunks_needed:
                    break

    print("Done recording, transcribing...")
    return np.concatenate(chunks, axis=0).flatten()


def listen_for_command():
    """Push-to-talk: waits for you to press Enter, THEN records until
    silence and transcribes. Returns '' if only silence was heard."""
    input("Press Enter, then speak your command...")
    audio = _record_until_silence()
    if np.abs(audio).max() < SILENCE_THRESHOLD:
        return ""

    recognizer = _get_recognizer()
    stream = recognizer.create_stream()
    stream.accept_waveform(SAMPLE_RATE, audio)
    recognizer.decode_stream(stream)
    return stream.result.text.strip()


if __name__ == "__main__":
    # Quick manual test - just run this file directly to check mic + transcription
    while True:
        text = listen_for_command()
        if text:
            print("You said:", text)
        else:
            print("(heard silence, try again)")