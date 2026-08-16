"""AI fill videos via the Higgsfield CLI, for tracks with no music video.

Generated clips cache in ~/Music/VinylVision/gen/<artist>-<title>.mp4 and are
served at /media/gen/... They loop in the browser (ambient fill, not
timeline-synced — there is no timeline to sync to).
"""
import asyncio
import logging
import re
import urllib.request
from pathlib import Path

from .fetch import CACHE

log = logging.getLogger("vinylvision")

GEN_DIR = CACHE / "gen"
GEN_DIR.mkdir(parents=True, exist_ok=True)

MODEL = "kling3_0"
MODE = "pro"          # "std" is 15 credits/10s, "pro" 17.5, "4k" more
DURATION = 10

_URL_RE = re.compile(r"https://[^\s\"'\\]+?\.mp4[^\s\"'\\]*")

GENRE_SCENES = {
    "hip-hop/rap": "night city streets, lowriders and candy-paint cars rolling in slow motion, gold light spilling from storefronts, smoke curling under streetlights, chains and chrome catching flashes",
    "rock": "a storm-lit stadium of fire and dust, guitars silhouetted against walls of amps, sparks raining, slow-motion crowd surge, lightning splitting the sky",
    "alternative": "surreal desert at dusk, floating debris and slow shockwaves, a lone figure walking into wind, dust devils glowing from within",
    "pop": "liquid neon and mirror rooms, confetti suspended mid-air, prismatic light refracting through glass dancers, saturated color bursts",
    "electronic": "an infinite server-cathedral of lasers and fog, geometric light structures assembling and shattering to a pulse, chrome surfaces rippling like water",
    "dance": "strobe-lit warehouse, silhouettes moving through fog and laser planes, light trails smearing, sweat and glitter in the air",
    "r&b/soul": "velvet night interiors, candlelight and silk in slow motion, rain on windows with city bokeh, warm skin tones and amber glow",
    "country": "golden-hour backroads, dust behind a pickup, neon roadhouse signs flickering on, fireflies over a field, a storm rolling in far away",
    "jazz": "smoky midnight club, brass instruments gleaming under a single spotlight, slow curls of cigarette smoke, rain-slicked street outside the window",
}
DEFAULT_SCENE = ("abstract cinematic dreamscape, waves of light and particle "
                 "storms breaking like surf, vast scale, slow powerful motion")


def slug(artist: str, title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", f"{artist}-{title}".lower()).strip("-")
    return s[:80] or "track"


def gen_path(artist: str, title: str) -> Path:
    return GEN_DIR / f"{slug(artist, title)}.mp4"


def build_prompt(artist: str, title: str, genre: str | None) -> str:
    scene = GENRE_SCENES.get((genre or "").lower(), DEFAULT_SCENE)
    return (f"Cinematic music-video mood film inspired by the song "
            f"\u201c{title}\u201d by {artist}: {scene}. Rhythmic motion that "
            f"pulses like a beat, anamorphic lens flares, film grain, rich "
            f"color grade, epic and kinetic, no text, no captions, no lyrics, "
            f"no people's faces in closeup, seamless looping motion")


async def generate(artist: str, title: str, genre: str | None) -> Path | None:
    """Run a Higgsfield job (several minutes). Returns the cached mp4 path,
    or None on failure. Safe to call repeatedly — cached results short-circuit."""
    out = gen_path(artist, title)
    if out.exists():
        return out
    prompt = build_prompt(artist, title, genre)
    log.info("higgsfield gen start: %s - %s (%s %s %ss)", artist, title, MODEL, MODE, DURATION)
    proc = await asyncio.create_subprocess_exec(
        "higgsfield", "generate", "create", MODEL,
        "--prompt", prompt, "--mode", MODE, "--duration", str(DURATION),
        "--sound", "off", "--wait", "--wait-timeout", "20m",
        "--wait-interval", "10s", "--json",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    raw, _ = await proc.communicate()
    text = raw.decode(errors="replace")
    m = _URL_RE.search(text)
    if proc.returncode != 0 or not m:
        log.error("higgsfield gen failed (rc=%s): %s", proc.returncode, text[-400:])
        return None
    url = m.group(0)
    tmp = out.with_suffix(".part")
    await asyncio.to_thread(urllib.request.urlretrieve, url, tmp)
    tmp.rename(out)
    log.info("higgsfield gen done: %s (%d KB)", out.name, out.stat().st_size // 1024)
    return out
