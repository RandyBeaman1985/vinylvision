"""Microphone capture: a rolling ring buffer of the last N seconds."""
import io
import threading
import time
import wave

import numpy as np
import sounddevice as sd

MIC_SR = 48000


class MicListener:
    def __init__(self, seconds: float = 15.0, device=None):
        self.sr = MIC_SR
        self.n = int(self.sr * seconds)
        self.buf = np.zeros(self.n, dtype=np.float32)
        self.lock = threading.Lock()
        self.t_last = 0.0  # wall time of the newest sample in buf
        self.filled = 0
        self.device = device
        self.stream = None

    def _cb(self, indata, frames, time_info, status):
        x = indata[:, 0]
        with self.lock:
            if frames >= self.n:
                self.buf[:] = x[-self.n:]
            else:
                self.buf = np.roll(self.buf, -frames)
                self.buf[-frames:] = x
            self.filled = min(self.n, self.filled + frames)
            self.t_last = time.time()

    def start(self):
        """Blocking: opening the input stream waits on the macOS microphone
        permission prompt the first time. Call from a thread."""
        self.stream = sd.InputStream(
            samplerate=self.sr, channels=1, dtype="float32",
            device=self.device, blocksize=4096, callback=self._cb,
        )
        self.stream.start()

    def snapshot(self, seconds: float):
        """Return (mono float32 @48k of the trailing `seconds`, wall time of last sample)."""
        k = int(self.sr * seconds)
        with self.lock:
            if self.filled < k:
                return None, None
            return self.buf[-k:].copy(), self.t_last

    def rms(self, seconds: float = 3.0) -> float:
        y, _ = self.snapshot(seconds)
        if y is None:
            return 0.0
        return float(np.sqrt(np.mean(y ** 2)))


def to_wav_bytes(y: np.ndarray, sr: int = MIC_SR) -> bytes:
    """float32 mono -> 16-bit PCM WAV bytes."""
    pcm = np.clip(y * 32767.0, -32768, 32767).astype(np.int16)
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return bio.getvalue()
