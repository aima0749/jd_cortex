# test_parakeet.py
import sherpa_onnx
import soundfile as sf

MODEL_DIR = "../voice_model/parakeet"

recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
    encoder=f"{MODEL_DIR}/encoder.int8.onnx",
    decoder=f"{MODEL_DIR}/decoder.int8.onnx",
    joiner=f"{MODEL_DIR}/joiner.int8.onnx",
    tokens=f"{MODEL_DIR}/tokens.txt",
    num_threads=2,
    sample_rate=16000,
    feature_dim=80,
    decoding_method="greedy_search",
    model_type="nemo_transducer",   # <-- the fix: tells sherpa-onnx this is a NeMo TDT export
)

stream = recognizer.create_stream()
samples, sample_rate = sf.read(f"{MODEL_DIR}/test_wavs/0.wav", dtype="float32")
stream.accept_waveform(sample_rate, samples)
recognizer.decode_stream(stream)

print("Transcription:", stream.result.text)