"""Whisper-Transkriptions-Worker: Modell einmal im RAM, Jobs seriell."""

import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from faster_whisper import WhisperModel

MODEL_NAME = os.environ.get("WHISPER_MODEL", "large-v3-turbo")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE", "int8")
CPU_THREADS = int(os.environ.get("WHISPER_CPU_THREADS", "4"))
LANGUAGE = os.environ.get("WHISPER_LANG", "de")

_model = WhisperModel(
    MODEL_NAME,
    device="cpu",
    compute_type=COMPUTE_TYPE,
    cpu_threads=CPU_THREADS,
)

# Genau 1 Worker: Inferenz laeuft streng seriell (Queue = Reihenfolge)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")


def transcribe_sync(pcm_f32: np.ndarray, language: str | None,
                    vad: bool) -> dict:
    """Transkribiert und liefert Text + Wort-Konfidenzen.

    Rueckgabe: {"text": str, "words": [{"w": str, "p": float}],
                "conf": float|None}  (conf = mittlere Wort-Wahrscheinlichkeit)
    """
    lang = None if language in (None, "auto") else language
    segments, _info = _model.transcribe(
        pcm_f32,
        language=lang or LANGUAGE,
        vad_filter=vad,
        vad_parameters=dict(min_silence_duration_ms=500),
        beam_size=5,
        word_timestamps=True,
    )
    words, parts, probs = [], [], []
    for seg in segments:
        parts.append(seg.text.strip())
        for w in seg.words or []:
            words.append({"w": w.word.strip(), "p": round(w.probability, 2)})
            probs.append(w.probability)
    conf = round(sum(probs) / len(probs), 2) if probs else None
    return {"text": " ".join(parts).strip(), "words": words, "conf": conf}


def submit(pcm_f32: np.ndarray, language: str | None, vad: bool):
    """Job in die serielle Queue legen -> concurrent.futures.Future[str]."""
    return _executor.submit(transcribe_sync, pcm_f32, language, vad)
