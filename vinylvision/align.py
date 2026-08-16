"""Audio alignment: find where a live mic clip sits inside a video's audio track.

Method: per-mel-band onset flux (48 bands x ~43 fps), z-normalized per band,
then summed FFT cross-correlation across bands. Band structure disambiguates
repeated riffs that fool a single onset envelope; robust to room EQ and
vinyl surface noise because it keys on onsets, not raw waveform.
"""
import numpy as np
from scipy import signal

SR = 22050          # analysis sample rate
NFFT = 2048
HOP = 512
FPS = SR / HOP      # ~43.07 feature frames per second
N_MELS = 48
FMIN, FMAX = 60.0, 8000.0


def _hz_to_mel(f):
    return 2595.0 * np.log10(1.0 + np.asarray(f) / 700.0)


def _mel_to_hz(m):
    return 700.0 * (10.0 ** (np.asarray(m) / 2595.0) - 1.0)


def _mel_fb():
    n_bins = NFFT // 2 + 1
    fft_freqs = np.linspace(0, SR / 2, n_bins)
    mel_pts = _mel_to_hz(np.linspace(_hz_to_mel(FMIN), _hz_to_mel(FMAX), N_MELS + 2))
    fb = np.zeros((N_MELS, n_bins), dtype=np.float32)
    for i in range(N_MELS):
        lo, mid, hi = mel_pts[i], mel_pts[i + 1], mel_pts[i + 2]
        up = (fft_freqs - lo) / max(mid - lo, 1e-6)
        down = (hi - fft_freqs) / max(hi - mid, 1e-6)
        fb[i] = np.maximum(0, np.minimum(up, down))
    return fb


_MEL = _mel_fb()


def resample_48k(y: np.ndarray) -> np.ndarray:
    # 48000 -> 22050  (ratio 147/320)
    return signal.resample_poly(y, 147, 320).astype(np.float32)


def features(y: np.ndarray) -> np.ndarray:
    """y: mono float32 at SR. Returns (N_MELS, frames) z-normalized onset flux."""
    _, _, Z = signal.stft(y, fs=SR, nperseg=NFFT, noverlap=NFFT - HOP,
                          padded=False, boundary=None)
    mel = _MEL @ np.abs(Z)
    L = np.log1p(100.0 * mel)
    flux = np.diff(L, axis=1)
    np.maximum(flux, 0.0, out=flux)
    mu = flux.mean(axis=1, keepdims=True)
    sd = flux.std(axis=1, keepdims=True)
    return ((flux - mu) / (sd + 1e-6)).astype(np.float32)


def _xcorr(track: np.ndarray, clip: np.ndarray) -> np.ndarray:
    n = track.shape[1] - clip.shape[1] + 1
    total = np.zeros(n, dtype=np.float64)
    for b in range(track.shape[0]):
        total += signal.correlate(track[b], clip[b], mode="valid", method="fft")
    return total


def align(track_feat: np.ndarray, clip_feat: np.ndarray,
          center: float | None = None, radius: float = 12.0):
    """Slide clip along track. Returns (offset_seconds_of_clip_start, confidence).

    Confidence = z-score of the correlation peak (measured: right song 6.3-9.8,
    wrong song <=5.3, so lock threshold sits at 6.0).
    If `center` is given, only lags within +-radius seconds are considered.
    """
    if clip_feat.shape[1] >= track_feat.shape[1] or clip_feat.shape[1] < int(4 * FPS):
        return None, 0.0
    cc = _xcorr(track_feat, clip_feat)
    mu, sd = cc.mean(), cc.std() + 1e-9

    search = cc
    base = 0
    if center is not None:
        lo = max(0, int((center - radius) * FPS))
        hi = min(len(cc), int((center + radius) * FPS))
        if hi - lo < 2:
            return None, 0.0
        search = cc[lo:hi]
        base = lo

    i = base + int(np.argmax(search))
    conf = float((cc[i] - mu) / sd)
    return i * HOP / SR, conf
