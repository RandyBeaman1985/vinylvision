# VinylVision

Hear the vinyl. Watch the video.

Put the needle down in the garage; the Mac listens through its microphone,
Shazams the track, grabs the official music video, and plays it **muted** in
your browser in perfect sync with the record — continuously drift-corrected
against your turntable.

## Install

```bash
git clone https://github.com/RandyBeaman1985/vinylvision.git
cd vinylvision
uv venv --python 3.12
uv pip install -r requirements.txt
./scripts/install-app.sh        # builds /Applications/VinylVision.app
```

Prereqs: macOS 12+, [uv](https://docs.astral.sh/uv/), `ffmpeg`
(`brew install ffmpeg`). Optional: the `higgsfield` CLI (logged in) for AI
fill videos — without it, no-video tracks just get the visualizer.

## Run

**As the Mac app:** launch **VinylVision** from /Applications (drag it to the
Dock). One click — it opens a native window and starts listening. First launch:
approve the microphone prompt.

**From a terminal (dev mode, opens a browser tab instead):**

```
./run.sh
```

Then just play a record. ~15–40s later (first play of a song downloads the
video; replays are instant from cache) the video appears, locked to the groove.

## Controls (in the browser)

- `←` / `→` or the −0.1s/+0.1s buttons — nudge video timing (remembered)
- `f` or ⛶ or double-click — fullscreen
- `l` or 👂 Listen — force an immediate re-identify (clears cooldowns)
- Green dot = strong lock, amber = weaker lock

## When no music video exists (VIBE mode)

1. Instantly: an audio-reactive visualizer — dual energy sabers that sway with
   the mids, flare with bass, crackle with treble, and clash with spark showers
   on every beat, under a loudness-driven starfield warp, with the album art
   floating as a flickering hologram (live band energies stream from the mic
   over the websocket at ~15 Hz).
2. Meanwhile: a Higgsfield AI mood film generates in the background (Kling 3.0
   pro, 10s, ~17.5 credits, genre-flavored prompt from the Shazam metadata).
   When it lands (~2-4 min) the screen switches to it, looping. Cached forever
   in `~/Music/VinylVision/gen/`, so each track only ever costs once.
3. Also meanwhile: the album's tracklist is looked up (iTunes, free) and the
   NEXT real track's video is pre-fetched — or pre-generated if it has none —
   so the following song starts ready.

Cost knobs at the top of `vinylvision/main.py`: `GEN_ENABLED`, `GEN_PREFETCH`
(set either to False to stop spending Higgsfield credits).

## How the sync works

1. Mic keeps a rolling 20s buffer. An 8s clip goes to Shazam → artist + title.
2. yt-dlp finds and downloads the official music video to `~/Music/VinylVision`.
3. **The clever bit:** Shazam's offset is useless for videos (intros, edits),
   so instead the live room audio is cross-correlated against the *video's own
   soundtrack* using 48 mel-band onset-flux features (~43 fps). That yields the
   exact position in the actual video file, to ~±25 ms.
4. Initial lock uses an 18s window (defeats repeated riffs); every 5s a 10s
   window re-aligns (search constrained ±12s around the expected position).
   Small drift is corrected invisibly via playbackRate glides; big jumps seek.
5. Confidence = correlation-peak z-score. Measured: right song 6.3–9.8, wrong
   song ≤5.3 → lock threshold 6.0. Two consecutive misses = song changed →
   back to listening.

## Knobs (top of `vinylvision/main.py`)

- `SILENCE_RMS` — quiet-room gate (raise if it "hears" music in silence)
- `CONF_LOCK` — lock threshold (6.0)
- `LOOP_SEC` — re-align cadence (5s)

## Layout

- `vinylvision/audio_io.py` — mic ring buffer (48 kHz)
- `vinylvision/recognize.py` — Shazam (shazamio, no API key needed)
- `vinylvision/fetch.py` — YouTube search/download/cache + feature precompute
- `vinylvision/align.py` — mel-band onset features + FFT cross-correlation
- `vinylvision/server.py` — aiohttp: page, Range-capable video serving, websocket
- `vinylvision/main.py` — the state machine (listen → identify → fetch → lock → ride)
- `static/index.html` — the screen: muted video, status disc, nudge chip

- `vinylvision/app.py` + `scripts/install-app.sh` — the native macOS app
  (compiled launcher → venv python → pywebview WKWebView window)
- `vinylvision/gen.py` / `nextup.py` — Higgsfield fill films + album-aware
  next-track prefetch

Cache lives in `~/Music/VinylVision` (mp4s + `.feat.npy` + `index.json`).
Delete a song's entry in `index.json` to force a different video pick.

## Notes

- Personal use on your own machine: it downloads videos via yt-dlp for
  private playback next to music you already own. Don't redistribute the
  cache.
- MIT licensed. Built by Clever Fox AI Labs.
