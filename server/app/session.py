"""Session-Zustand pro WebSocket-Verbindung. Alles nur im RAM."""

import numpy as np

RATE = 16000            # Hz, int16 mono
MAX_SECONDS = 60        # hartes Diktat-Limit
MAX_SAMPLES = MAX_SECONDS * RATE
WINDOW_SECONDS = 4      # Groesse der Live-Teilfenster
MIN_PEAK = 0.003        # unter diesem Pegel gilt ein Fenster als Stille


class Session:
    def __init__(self) -> None:
        self.gen = 0
        self.reset()

    def reset(self) -> None:
        self.buf = bytearray()
        self.committed: list[str] = []
        self.done_samples = 0
        self.recording = False
        self.final_text: str | None = None
        self.language: str | None = None
        self.gen += 1               # verwaiste Jobs werden so erkannt

    @property
    def state(self) -> str:
        if self.recording:
            return "recording"
        return "locked" if self.final_text is not None else "ready"

    @property
    def samples(self) -> int:
        return len(self.buf) // 2

    def start(self, language: str | None) -> None:
        self.reset()
        self.recording = True
        self.language = language

    def add_audio(self, data: bytes) -> bool:
        """PCM16 anhaengen. False = 60s-Limit erreicht (Rest verworfen)."""
        room = MAX_SAMPLES * 2 - len(self.buf)
        if room <= 0:
            return False
        self.buf += data[:room]
        return len(data) <= room

    def pending_window(self):
        """Neues volles Teilfenster als float32, sonst None.
        Stille-Fenster werden uebersprungen (kein Whisper-Job, kein
        Halluzinations-Output auf Rauschen)."""
        done = self.done_samples
        if self.samples - done < WINDOW_SECONDS * RATE:
            return None
        end = done + WINDOW_SECONDS * RATE
        self.done_samples = end
        seg = np.frombuffer(bytes(self.buf[done * 2:end * 2]), dtype=np.int16)
        seg = seg.astype(np.float32) / 32768.0
        if float(np.abs(seg).max()) < MIN_PEAK:
            return None
        return seg

    def full_audio(self):
        return np.frombuffer(
            bytes(self.buf), dtype=np.int16).astype(np.float32) / 32768.0

    def finish(self, text: str) -> None:
        self.final_text = text
        self.recording = False
        self.buf.clear()            # Audio nach Transkription vernichten
        self.committed.clear()

    def committed_text(self) -> str:
        return " ".join(t for t in self.committed if t).strip()
