#!/usr/bin/env python3
"""
webconsole.py — web UI + WebSocket console for the Remote Administration Tool
=============================================================================

This is the cloud-deployable face of the project (e.g. on Railway). A single
FastAPI application serves three things on one HTTPS port:

    1. The operator dashboard (HTML/CSS/JS in ./static), behind an OPERATOR
       LOGIN. The login is separate from, and additional to, the agent shared
       secret — because once this is on the public internet, the password is
       what stops a stranger from driving your agents.

    2. A JSON API the dashboard calls to list agents and send commands.

    3. A WebSocket endpoint (/ws/agent) where agents connect IN. Agents prove
       themselves with the same mutual HMAC handshake used by the TCP console,
       reusing protocol.py's primitives. TLS is provided by the platform
       (wss://), so the shared secret is never sent and traffic is encrypted.

Required environment variables (the app refuses to start without them):
    RAT_SHARED_SECRET     — secret agents authenticate with.
    RAT_OPERATOR_PASSWORD — password the human operator logs in with.

Run locally:
    uvicorn webconsole:app --host 0.0.0.0 --port 9090
On Railway the Procfile runs uvicorn bound to $PORT.

Authorised / educational use only. Hosting this publicly means you are running
an internet-reachable administration panel: use a strong, unique operator
password and shared secret, and only connect agents you own/are authorised for.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from fastapi import Cookie, FastAPI, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import protocol

# ---------------------------------------------------------------------------
# Configuration & logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [webconsole] %(levelname)s %(message)s",
    handlers=[logging.FileHandler("console_audit.log"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("webconsole")

SHARED_SECRET = protocol.load_shared_secret()  # from RAT_SHARED_SECRET

OPERATOR_PASSWORD = os.environ.get("RAT_OPERATOR_PASSWORD")
if not OPERATOR_PASSWORD:
    raise SystemExit(
        "Set RAT_OPERATOR_PASSWORD to a strong password before starting the "
        "web console.\n  export RAT_OPERATOR_PASSWORD='...'"
    )

STATIC_DIR = Path(__file__).parent / "static"

# Per-request command timeout (seconds). Long enough for slow commands, short
# enough that a stuck agent does not hang an operator's browser forever.
COMMAND_TIMEOUT = 35


# ---------------------------------------------------------------------------
# In-memory state: operator sessions and connected agents
# ---------------------------------------------------------------------------

# Operator session tokens. In-memory means logins reset when the app restarts,
# which is fine for a teaching tool. A real app would use a signed/expiring
# token store.
_SESSIONS: set[str] = set()


@dataclass
class WebAgent:
    """One authenticated agent connected over WebSocket."""
    id: int
    ws: WebSocket
    address: str
    info: dict[str, Any] = field(default_factory=dict)
    connected_at: float = field(default_factory=time.time)
    # Serialise commands so only one request is outstanding at a time; this lets
    # us match each reply on the receive loop to the right waiting caller.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _pending: Optional[asyncio.Future] = None

    async def request(self, payload: dict[str, Any]) -> Any:
        """Send a request to this agent and await its single reply."""
        async with self.lock:
            loop = asyncio.get_running_loop()
            self._pending = loop.create_future()
            await self.ws.send_json(payload)
            try:
                return await asyncio.wait_for(self._pending, COMMAND_TIMEOUT)
            finally:
                self._pending = None

    def deliver(self, message: Any) -> None:
        """Hand a received message to whoever is awaiting a reply."""
        if self._pending is not None and not self._pending.done():
            self._pending.set_result(message)

    def public_view(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "address": self.address,
            "connected_at": self.connected_at,
            "info": self.info,
        }


class Registry:
    """Thread/task-safe-ish registry of connected agents (single event loop)."""

    def __init__(self) -> None:
        self._agents: dict[int, WebAgent] = {}
        self._next_id = 1

    def add(self, ws: WebSocket, address: str) -> WebAgent:
        agent = WebAgent(id=self._next_id, ws=ws, address=address)
        self._agents[self._next_id] = agent
        self._next_id += 1
        return agent

    def remove(self, agent_id: int) -> None:
        self._agents.pop(agent_id, None)

    def get(self, agent_id: int) -> Optional[WebAgent]:
        return self._agents.get(agent_id)

    def all(self) -> list[WebAgent]:
        return list(self._agents.values())


registry = Registry()
app = FastAPI(title="Educational Remote Administration Console")


# ---------------------------------------------------------------------------
# Operator authentication helpers
# ---------------------------------------------------------------------------

def _new_session() -> str:
    token = secrets.token_urlsafe(32)
    _SESSIONS.add(token)
    return token


def _require_operator(session: Optional[str]) -> None:
    """Raise 401 unless the session cookie identifies a logged-in operator."""
    if not session or session not in _SESSIONS:
        raise HTTPException(status_code=401, detail="login required")


# ---------------------------------------------------------------------------
# Operator-facing HTTP routes
# ---------------------------------------------------------------------------

@app.get("/")
def index(session: Optional[str] = Cookie(default=None)):
    """Serve the dashboard if logged in, otherwise the login page."""
    if session and session in _SESSIONS:
        return FileResponse(STATIC_DIR / "index.html")
    return FileResponse(STATIC_DIR / "login.html")


@app.post("/login")
def login(password: str = Form(...)):
    """Check the operator password and start a session."""
    # Constant-time comparison so the password length/prefix is not leaked.
    if not secrets.compare_digest(password, OPERATOR_PASSWORD):
        log.warning("operator LOGIN FAILED")
        return RedirectResponse("/?error=1", status_code=303)
    token = _new_session()
    log.info("operator LOGIN OK")
    response = RedirectResponse("/", status_code=303)
    # httponly stops page JS from reading the cookie; samesite=strict limits CSRF.
    response.set_cookie("session", token, httponly=True, samesite="strict")
    return response


@app.post("/logout")
def logout(session: Optional[str] = Cookie(default=None)):
    if session:
        _SESSIONS.discard(session)
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("session")
    return response


@app.get("/api/agents")
def list_agents(session: Optional[str] = Cookie(default=None)):
    _require_operator(session)
    return JSONResponse([a.public_view() for a in registry.all()])


@app.post("/api/agents/{agent_id}/command")
async def send_command(
    agent_id: int,
    payload: dict,
    session: Optional[str] = Cookie(default=None),
):
    """Forward an operator command to an agent and return the agent's result."""
    _require_operator(session)
    agent = registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="no such agent")

    action = payload.get("action")
    if action not in {"sysinfo", "ping", "exec"}:
        raise HTTPException(status_code=400, detail="unsupported action")

    if action == "exec":
        command = payload.get("command", "")
        log.warning("operator -> agent #%d EXEC: %r", agent_id, command)
        request = {"action": "exec", "command": command}
    else:
        log.info("operator -> agent #%d %s", agent_id, action)
        request = {"action": action}

    try:
        result = await agent.request(request)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="agent timed out")
    except (WebSocketDisconnect, RuntimeError):
        raise HTTPException(status_code=410, detail="agent disconnected")

    # Refresh cached sysinfo so the dashboard card stays current.
    if action == "sysinfo" and isinstance(result, dict) and result.get("type") == "sysinfo":
        agent.info = result.get("data", {})
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Agent-facing WebSocket endpoint
# ---------------------------------------------------------------------------

async def _ws_server_authenticate(ws: WebSocket) -> None:
    """Run the console half of the mutual handshake over a WebSocket.

    Mirrors protocol.server_authenticate_io, but with awaited WebSocket I/O.
    Reuses the same crypto primitives so agents speak one handshake everywhere.
    """
    server_nonce = protocol.new_challenge()
    await ws.send_json({"type": "auth_challenge", "nonce": server_nonce})

    reply = await ws.receive_json()
    if not isinstance(reply, dict) or reply.get("type") != "auth_response":
        raise protocol.AuthenticationError("expected auth_response")
    if not protocol.verify_proof(SHARED_SECRET, server_nonce, reply.get("proof", "")):
        raise protocol.AuthenticationError("bad secret")
    agent_nonce = reply.get("nonce", "")
    if not isinstance(agent_nonce, str) or not agent_nonce:
        raise protocol.AuthenticationError("missing agent nonce")

    await ws.send_json({"type": "auth_confirm",
                        "proof": protocol.proof_for(SHARED_SECRET, agent_nonce)})


@app.websocket("/ws/agent")
async def agent_endpoint(ws: WebSocket):
    address = f"{ws.client.host}:{ws.client.port}" if ws.client else "unknown"
    await ws.accept()
    log.info("incoming agent connection from %s", address)

    # Authenticate before trusting anything the peer says.
    try:
        await _ws_server_authenticate(ws)
    except (protocol.AuthenticationError, WebSocketDisconnect, ValueError) as exc:
        log.warning("AUTH FAILED from %s — %s", address, exc)
        await ws.close(code=4401)
        return

    # First message after auth must be the agent's hello with system info.
    try:
        hello = await ws.receive_json()
    except (WebSocketDisconnect, ValueError):
        return
    agent = registry.add(ws, address)
    if isinstance(hello, dict) and hello.get("type") == "hello":
        agent.info = hello.get("data", {})
    log.info("AUTH OK: agent #%d is %s (%s)",
             agent.id, agent.info.get("hostname", "?"), address)

    # Receive loop: every message is a reply to an operator-issued request.
    try:
        while True:
            message = await ws.receive_json()
            agent.deliver(message)
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        registry.remove(agent.id)
        log.info("agent #%d disconnected (%s)", agent.id, address)


# Static assets (CSS/JS). Mounted last so it does not shadow the routes above.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    # Convenience launcher for local runs: `python webconsole.py`.
    import uvicorn

    port = int(os.environ.get("PORT", "9090"))
    log.info("starting web console on 0.0.0.0:%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
