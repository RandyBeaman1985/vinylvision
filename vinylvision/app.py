"""Native macOS app entry point: run the VinylVision server in a background
thread and show the UI in a native WKWebView window (no browser chrome).

Launched by VinylVision.app (see scripts/install-app.sh). Hit the Dock icon
and it's listening — that's the whole UX.
"""
import asyncio
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# When launched from the Dock, PATH is minimal — ffmpeg / higgsfield live here.
os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")

from .server import PORT


def _port_busy() -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def _clear_previous_instance():
    if _port_busy():
        subprocess.run(["pkill", "-f", "vinylvision"], capture_output=True)
        for _ in range(20):
            if not _port_busy():
                break
            time.sleep(0.25)


def _run_server():
    from .main import amain

    async def serve():
        await amain()

    asyncio.run(serve())


def main():
    _clear_previous_instance()
    # amain() normally opens a browser tab; suppress that in app mode
    os.environ["VV_NO_BROWSER"] = "1"
    t = threading.Thread(target=_run_server, daemon=True)
    t.start()
    for _ in range(60):
        if _port_busy():
            break
        time.sleep(0.25)
    else:
        print("server failed to start", file=sys.stderr)
        sys.exit(1)

    # cosmetic: make the running process present as VinylVision, not Python
    try:
        from AppKit import NSApplication, NSImage
        icon = Path(__file__).resolve().parent.parent / "assets" / "icon-src.png"
        img = NSImage.alloc().initWithContentsOfFile_(str(icon))
        if img:
            NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception:
        pass

    import webview
    webview.create_window(
        "VinylVision", f"http://127.0.0.1:{PORT}",
        width=1280, height=800, background_color="#000000")
    webview.start()      # blocks until the window closes
    os._exit(0)          # take the server thread down with us


if __name__ == "__main__":
    main()
