"""Find, download, and cache the music video for a recognized track.

Cache layout (~/Music/VinylVision):
    <video_id>.mp4       the video itself (served to the browser)
    <video_id>.feat.npy  precomputed mel-band onset features of the video's audio
    index.json           "artist|title" -> video_id
"""
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import yt_dlp

from .align import SR, features

CACHE = Path.home() / "Music" / "VinylVision"
CACHE.mkdir(parents=True, exist_ok=True)
INDEX = CACHE / "index.json"

BAD_WORDS = ("reaction", "cover", "karaoke", "tutorial", "lesson", "slowed",
             "sped up", "8d", "nightcore", "hour", "loop", "remix")

_STOP = {"the", "a", "an", "of", "and", "feat", "ft"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", s.lower())


def _title_match(track_title: str, video_title: str) -> bool:
    """The video's title must actually contain the song title (this is what
    stopped 'OutKast - Intro' from matching 'Roses (Official HD Video)')."""
    vt = _norm(video_title)
    words = [w for w in _norm(track_title).split() if w not in _STOP]
    if not words:
        return False
    hits = sum(1 for w in words if w in vt)
    return hits / len(words) >= 0.6


_AUDIO_ONLY = re.compile(r"\b(audio|lyric|lyrics|visuali[sz]er|art track)\b", re.I)


def _is_real_video(entry: dict) -> bool:
    """True only for actual music videos — never YouTube's auto-generated
    album-art uploads ('Artist - Topic') or '(Official Audio)' still images."""
    t = (entry.get("title") or "")
    ch = (entry.get("channel") or entry.get("uploader") or "")
    if _AUDIO_ONLY.search(t):
        return False
    if ch.strip().lower().endswith("- topic"):
        return False
    return "video" in t.lower()


def _load_index() -> dict:
    if INDEX.exists():
        try:
            return json.loads(INDEX.read_text())
        except Exception:
            return {}
    return {}


def _save_index(idx: dict):
    INDEX.write_text(json.dumps(idx, indent=1))


def _key(artist: str, title: str) -> str:
    return re.sub(r"\s+", " ", f"{artist}|{title}".lower()).strip()


def _score(entry: dict) -> float:
    t = (entry.get("title") or "").lower()
    ch = (entry.get("channel") or entry.get("uploader") or "").lower()
    dur = entry.get("duration") or 0
    s = 0.0
    if "official" in t:
        s += 3
    if "video" in t:
        s += 1.5
    if "official" in ch or "vevo" in ch:
        s += 1.5
    if entry.get("channel_is_verified"):
        s += 1
    for w in BAD_WORDS:
        if w in t:
            s -= 4
    if "live" in t and "live" not in (entry.get("track") or "").lower():
        s -= 2
    if dur and (dur < 60 or dur > 900):
        s -= 5
    return s


def _search(query: str, n: int = 6) -> list:
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True,
            "noplaylist": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    return list(info.get("entries") or [])


def _download(video_id: str) -> Path:
    out = CACHE / f"{video_id}.mp4"
    if out.exists():
        return out
    opts = {
        "format": "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[ext=mp4]/b",
        "outtmpl": str(CACHE / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True, "no_warnings": True, "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    if not out.exists():
        raise RuntimeError(f"download produced no mp4 for {video_id}")
    return out


def _features(video_id: str) -> np.ndarray:
    feat_path = CACHE / f"{video_id}.feat.npy"
    if feat_path.exists():
        return np.load(feat_path)
    mp4 = CACHE / f"{video_id}.mp4"
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(mp4), "-ac", "1",
         "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True, check=True)
    y = np.frombuffer(p.stdout, dtype=np.float32)
    feat = features(y)
    np.save(feat_path, feat)
    return feat


def ensure_video(artist: str, title: str):
    """Blocking (run in a thread). Returns (video_id, mp4_path, features, video_title)
    or raises RuntimeError if nothing suitable is found."""
    idx = _load_index()
    k = _key(artist, title)
    vid = idx.get(k)
    picked_title = ""
    if not vid:
        entries = _search(f"{artist} {title} official music video")
        if not entries:
            entries = _search(f"{artist} {title} official video")
        entries = [e for e in entries if e and e.get("id")
                   and _title_match(title, e.get("title") or "")
                   and _is_real_video(e)
                   and not ((e.get("duration") or 0) > 900)]
        if not entries:
            raise RuntimeError(f"no music video exists for “{title}”")
        best = max(entries, key=_score)
        if _score(best) < -2:
            raise RuntimeError(f"only junk results for {artist} - {title}")
        vid = best["id"]
        picked_title = best.get("title") or ""
        idx[k] = vid
        _save_index(idx)
    mp4 = _download(vid)
    feat = _features(vid)
    return vid, mp4, feat, picked_title
