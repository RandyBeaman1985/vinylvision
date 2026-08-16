"""Figure out what's playing next on the record via the album tracklist.

Shazam gives us an Apple album id (albumadamid); the free iTunes lookup API
turns that into an ordered tracklist. We walk forward from the current track,
skipping skits/interludes, so the downtime during a no-video song can be used
to pre-fetch (or pre-generate) the NEXT song's visuals.
"""
import logging
import re

import aiohttp

log = logging.getLogger("vinylvision")

SKIT_RE = re.compile(r"\b(intro|outro|interlude|skit|intermission|prelude)\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


async def album_tracks(albumadamid: str) -> list[dict]:
    """Ordered [{'title', 'artist'}] for the album, or []."""
    url = f"https://itunes.apple.com/lookup?id={albumadamid}&entity=song&limit=200"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                data = await r.json(content_type=None)
    except Exception as e:
        log.info("itunes lookup failed for %s: %s", albumadamid, e)
        return []
    songs = [x for x in data.get("results", []) if x.get("wrapperType") == "track"]
    songs.sort(key=lambda x: (x.get("discNumber", 1), x.get("trackNumber", 0)))
    return [{"title": x.get("trackName", ""), "artist": x.get("artistName", "")}
            for x in songs]


async def next_real_track(albumadamid: str, current_title: str):
    """The next non-skit track after current_title, or None."""
    tracks = await album_tracks(albumadamid)
    cur = _norm(current_title)
    idx = None
    for i, t in enumerate(tracks):
        tn = _norm(t["title"])
        if tn == cur or cur in tn or tn in cur:
            idx = i
            break
    if idx is None:
        return None
    for t in tracks[idx + 1:]:
        if not SKIT_RE.search(t["title"]):
            return t
    return None
