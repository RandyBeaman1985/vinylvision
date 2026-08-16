"""Song identification via Shazam (shazamio)."""
from shazamio import Shazam

_shazam = Shazam()


async def identify(wav_bytes: bytes):
    """Returns {"artist", "title", "art"} or None."""
    result = await _shazam.recognize(wav_bytes)
    track = (result or {}).get("track")
    if not track:
        return None
    title = track.get("title")
    artist = track.get("subtitle")
    if not title or not artist:
        return None
    art = (track.get("images") or {}).get("coverart")
    genre = (track.get("genres") or {}).get("primary")
    return {"artist": artist, "title": title, "art": art,
            "genre": genre, "albumadamid": track.get("albumadamid")}
