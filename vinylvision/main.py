"""VinylVision — hear the vinyl, watch the video.

Listens to the room through the Mac's microphone, Shazams what's spinning,
fetches the official music video, then cross-correlates the live audio
against the video's own soundtrack so the (muted) video plays in perfect
sync with the record — drift-corrected continuously.

Tracks with no music video enter VIBE mode: an audio-reactive visualizer
runs instantly, a Higgsfield AI mood film generates in the background (and
is cached forever), and the downtime is used to look up the album's NEXT
track and pre-fetch or pre-generate its visuals.
"""
import asyncio
import logging
import os
import subprocess
import time
from pathlib import Path

import numpy as np
from aiohttp import web

from .align import align, features, resample_48k
from .audio_io import MicListener, to_wav_bytes
from .fetch import ensure_video
from .gen import gen_path, generate
from .nextup import SKIT_RE, next_real_track
from .recognize import identify
from .server import PORT, Hub, build_app

SILENCE_RMS = 0.0035     # below this the room is considered quiet
CONF_LOCK = 6.0          # correlation confidence needed to (re)lock
CLIP_ID_SEC = 8.0        # clip length sent to Shazam
CLIP_LOCK_SEC = 18.0     # clip length for the initial (unconstrained) lock
CLIP_ALIGN_SEC = 10.0    # clip length for drift re-alignment while locked
LOOP_SEC = 5.0           # main loop cadence
FETCH_COOLDOWN = 120.0   # seconds before retrying a track that failed to fetch
VIBE_RECHECK_TICKS = 2   # re-Shazam every N ticks while vibing (~10s)
GEN_ENABLED = True       # Higgsfield fill videos for no-video tracks
GEN_PREFETCH = True      # also pre-generate for the album's next track

log = logging.getLogger("vinylvision")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler(Path(__file__).resolve().parent.parent / "vv.log")],
)


def track_key(artist: str, title: str) -> str:
    return f"{artist}|{title}".lower()


class State:
    def __init__(self):
        self.locked = False
        self.artist = self.title = self.video_id = None
        self.art = self.genre = self.albumadamid = None
        self.feat = None
        self.expect = None   # (video_pos, wall_time) of last good sync
        self.misses = 0
        self.failed = {}     # track_key -> wall time of last fetch failure
        self.vibe_key = None
        self.vibe_ticks = 0
        self.gen_task = None
        self.prefetch_task = None


async def status(hub, state_name, st: State, **extra):
    log.info("status=%s %s %s", state_name,
             f"{st.artist} - {st.title}" if st.title else "", extra or "")
    await hub.broadcast({"type": "status", "state": state_name,
                         "artist": st.artist, "title": st.title,
                         "art": st.art, **extra})


def _gen_url(artist, title):
    p = gen_path(artist, title)
    return f"/media/gen/{p.name}" if p.exists() else None


async def enter_vibe(hub, st: State, reason: str):
    """No video for this track: visualizer now, AI film when ready,
    and use the downtime to prep the album's next track."""
    st.vibe_key = track_key(st.artist, st.title)
    st.vibe_ticks = 0
    url = _gen_url(st.artist, st.title)
    await status(hub, "vibe", st, gen=url, reason=reason)
    if url is None and GEN_ENABLED:
        st.gen_task = asyncio.create_task(
            run_gen(hub, st, st.vibe_key, st.artist, st.title, st.genre))
    if st.albumadamid:
        st.prefetch_task = asyncio.create_task(
            prefetch_next(st, st.albumadamid, st.title, st.genre))


async def run_gen(hub, st: State, key, artist, title, genre):
    try:
        path = await generate(artist, title, genre)
    except Exception as e:
        log.error("gen error for %s: %s", key, e)
        return
    if path and st.vibe_key == key:   # still on this song -> switch the screen
        await status(hub, "vibe", st, gen=f"/media/gen/{path.name}",
                     reason="generated")


async def prefetch_next(st: State, albumadamid, current_title, genre):
    """During downtime, get the NEXT album track's visuals ready."""
    try:
        nxt = await next_real_track(albumadamid, current_title)
        if not nxt:
            return
        log.info("next up on album: %s - %s", nxt["artist"], nxt["title"])
        try:
            await asyncio.to_thread(ensure_video, nxt["artist"], nxt["title"])
            log.info("prefetched video for %s", nxt["title"])
        except RuntimeError:
            if GEN_PREFETCH and not gen_path(nxt["artist"], nxt["title"]).exists():
                log.info("no video for next track %s -> pre-generating", nxt["title"])
                await generate(nxt["artist"], nxt["title"], genre)
    except Exception as e:
        log.info("prefetch failed: %s", e)


async def try_lock(hub, mic, st: State) -> bool:
    y, t_end = mic.snapshot(CLIP_LOCK_SEC)
    if y is None:
        return False
    off, conf = align(st.feat, features(resample_48k(y)))
    log.info("lock attempt: off=%s conf=%.1f",
             None if off is None else round(off, 2), conf)
    if off is None or conf < CONF_LOCK:
        return False
    pos_at_end = off + CLIP_LOCK_SEC
    await hub.broadcast({
        "type": "sync", "hard": True,
        "url": f"/media/{st.video_id}.mp4",
        "pos": pos_at_end, "at": t_end,
        "artist": st.artist, "title": st.title, "conf": round(conf, 1),
    })
    st.locked = True
    st.misses = 0
    st.expect = (pos_at_end, t_end)
    return True


async def handle_hit(hub, mic, st: State, hit: dict):
    """A newly recognized track (not the one we're already vibing on)."""
    st.artist, st.title = hit["artist"], hit["title"]
    st.art, st.genre = hit.get("art"), hit.get("genre")
    st.albumadamid = hit.get("albumadamid") or st.albumadamid
    st.vibe_key = None
    key = track_key(st.artist, st.title)

    if SKIT_RE.search(st.title):
        await enter_vibe(hub, st, "album cut")
        return
    if time.time() - st.failed.get(key, 0) < FETCH_COOLDOWN:
        await enter_vibe(hub, st, "no video")
        return
    await status(hub, "fetching", st)
    try:
        vid, _mp4, feat, _ = await asyncio.to_thread(ensure_video, st.artist, st.title)
    except Exception as e:
        log.info("fetch failed: %s", e)
        st.failed[key] = time.time()
        await enter_vibe(hub, st, str(e))
        return
    st.video_id, st.feat = vid, feat
    await status(hub, "locking", st)
    if not await try_lock(hub, mic, st):
        await asyncio.sleep(3)
        if not await try_lock(hub, mic, st):
            st.failed[key] = time.time()
            await enter_vibe(hub, st, "couldn't align the video — vibing instead")


async def loop(hub: Hub, mic: MicListener):
    st = State()
    await status(hub, "listening", st)
    while True:
        try:
            await asyncio.wait_for(hub.listen_now.wait(), timeout=LOOP_SEC)
            hub.listen_now.clear()
            log.info("listen-now pressed: clearing cooldowns")
            st.failed.clear()
            st.vibe_key = None
            st.locked = False
        except asyncio.TimeoutError:
            pass

        rms = mic.rms(3.0)
        if rms < SILENCE_RMS:
            if st.locked or st.vibe_key:
                await hub.broadcast({"type": "pause"})
                st.locked = False
                st.vibe_key = None
                st.expect = None
            await status(hub, "silent", st, rms=round(rms, 5))
            continue

        if st.locked:
            y, t_end = mic.snapshot(CLIP_ALIGN_SEC)
            if y is None:
                continue
            center = None
            if st.expect:
                center = st.expect[0] + (t_end - st.expect[1]) - CLIP_ALIGN_SEC
            off, conf = align(st.feat, features(resample_48k(y)), center=center)
            log.info("realign: off=%s conf=%.1f",
                     None if off is None else round(off, 2), conf)
            if off is not None and conf >= CONF_LOCK:
                st.misses = 0
                st.expect = (off + CLIP_ALIGN_SEC, t_end)
                await hub.broadcast({
                    "type": "sync", "hard": False,
                    "url": f"/media/{st.video_id}.mp4",
                    "pos": off + CLIP_ALIGN_SEC, "at": t_end,
                    "artist": st.artist, "title": st.title,
                    "conf": round(conf, 1),
                })
            else:
                st.misses += 1
                if st.misses >= 2:      # song changed or ended
                    st.locked = False
                    st.expect = None
                    await hub.broadcast({"type": "pause"})
                    await status(hub, "listening", st)
            continue

        # --- not locked: identify what's playing ---
        if st.vibe_key:
            st.vibe_ticks += 1
            if st.vibe_ticks % VIBE_RECHECK_TICKS:
                continue        # stay in the vibe, re-check every ~10s
        y, _ = mic.snapshot(CLIP_ID_SEC)
        if y is None:
            continue
        if not st.vibe_key:
            await status(hub, "listening", st, rms=round(rms, 5))
        try:
            hit = await identify(to_wav_bytes(y))
        except Exception as e:
            log.info("shazam error: %s", e)
            continue
        if not hit:
            log.info("shazam: no match (rms=%.4f)", rms)
            continue
        log.info("shazam: %s - %s [%s]", hit["artist"], hit["title"], hit.get("genre"))
        if st.vibe_key and track_key(hit["artist"], hit["title"]) == st.vibe_key:
            continue            # same song still playing, keep vibing
        await handle_hit(hub, mic, st, hit)


async def feature_pump(hub: Hub, mic: MicListener):
    """Stream band energies to the browser ~15x/s for the visualizer."""
    n = 4096
    win = np.hanning(n).astype(np.float32)
    while True:
        await asyncio.sleep(0.066)
        if not len(hub.sockets):
            continue
        y, _ = mic.snapshot(n / mic.sr)
        if y is None:
            continue
        sp = np.abs(np.fft.rfft(y * win))
        # bin width = 48000/4096 ~= 11.7 Hz
        msg = {
            "type": "audio",
            "rms": float(np.sqrt(np.mean(y ** 2))),
            "bass": float(sp[2:22].mean()),      # ~23-260 Hz
            "mid": float(sp[22:171].mean()),     # ~260 Hz-2 kHz
            "treb": float(sp[171:683].mean()),   # 2-8 kHz
        }
        await hub.broadcast(msg)


async def amain():
    hub = Hub()
    hub.listen_now = asyncio.Event()
    runner = web.AppRunner(build_app(hub))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()
    print(f"VinylVision up at http://localhost:{PORT}")
    if not os.environ.get("VV_NO_BROWSER"):
        subprocess.Popen(["open", f"http://localhost:{PORT}"])

    hub.last_status = {"type": "status", "state": "mic",
                       "artist": None, "title": None, "art": None}
    mic = MicListener(seconds=20.0)
    try:
        await asyncio.to_thread(mic.start)
    except Exception as e:
        await hub.broadcast({"type": "status", "state": "mic",
                             "artist": None, "title": None, "art": None,
                             "detail": f"microphone failed: {e}"})
        while True:
            await asyncio.sleep(3600)
    asyncio.create_task(feature_pump(hub, mic))
    await loop(hub, mic)


def main():
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
