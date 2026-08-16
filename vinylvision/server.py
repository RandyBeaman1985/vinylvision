"""Local web server: serves the viewer page, cached videos (with Range
support), and a websocket that pushes sync/state messages to the browser."""
import json
import weakref
from pathlib import Path

from aiohttp import WSMsgType, web

from .fetch import CACHE

STATIC = Path(__file__).resolve().parent.parent / "static"
PORT = 8642


class Hub:
    """Tracks connected websockets; remembers the last messages so a browser
    opened late immediately catches up."""

    def __init__(self):
        self.sockets = weakref.WeakSet()
        self.last_status = None
        self.last_sync = None
        self.listen_now = None  # asyncio.Event, set by the UI's Listen button

    async def broadcast(self, msg: dict):
        if msg.get("type") == "status":
            self.last_status = msg
        elif msg.get("type") == "sync":
            self.last_sync = msg
        elif msg.get("type") == "pause":
            self.last_sync = None
        data = json.dumps(msg)
        for ws in set(self.sockets):
            try:
                await ws.send_str(data)
            except Exception:
                pass


def build_app(hub: Hub) -> web.Application:
    async def index(_req):
        return web.FileResponse(STATIC / "index.html")

    async def ws_handler(req):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(req)
        hub.sockets.add(ws)
        if hub.last_status:
            await ws.send_str(json.dumps(hub.last_status))
        if hub.last_sync:
            await ws.send_str(json.dumps(hub.last_sync))
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    cmd = json.loads(msg.data).get("cmd")
                except Exception:
                    continue
                if cmd == "listen" and hub.listen_now is not None:
                    hub.listen_now.set()
            elif msg.type == WSMsgType.ERROR:
                break
        return ws

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_static("/media/", CACHE)
    app.router.add_static("/static/", STATIC)
    return app
