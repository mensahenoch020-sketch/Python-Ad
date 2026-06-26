"""
protocol.py
===========

Shared networking helpers for the educational Remote Administration Tool (RAT).

This module is imported by BOTH the console (server) and the agent (client) so
that the two programs always speak exactly the same "language" on the wire.

It deliberately keeps three concerns separate and small, so each is easy to read
and reason about:

1. MESSAGE FRAMING
   TCP is a *stream* of bytes, not a sequence of messages. If one side sends
   two JSON objects back to back, the other side may receive them glued
   together (or split apart). To turn the stream back into discrete messages we
   prefix every payload with its length: a 4-byte big-endian unsigned integer
   followed by exactly that many bytes of UTF-8 JSON.

       +----------------+--------------------------------+
       | length (4 B)   | JSON payload (length bytes)    |
       +----------------+--------------------------------+

2. AUTHENTICATION
   We never send the shared secret across the network. Instead we use an
   HMAC-SHA256 challenge/response handshake. Each side proves it knows the
   secret by computing an HMAC over a random nonce chosen by the *other* side.
   Because the nonce is fresh every time, a captured handshake cannot be
   replayed later. The handshake is *mutual*: the agent proves itself to the
   console AND the console proves itself to the agent, so an agent will not
   talk to an impostor console.

3. (DOCUMENTED) CONFIDENTIALITY
   HMAC authentication protects against impersonation and tampering, but it
   does NOT encrypt the traffic. For anything beyond a trusted lab LAN you
   should wrap the socket in TLS. This module provides `maybe_wrap_tls()` to do
   exactly that when certificate files are supplied; see the README.

Educational use only. Run this against machines you own or are explicitly
authorised to administer.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import socket
import ssl
import struct
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Size of the length prefix in bytes (a 32-bit unsigned integer).
_LENGTH_PREFIX = struct.Struct("!I")

# Refuse to allocate a buffer larger than this for a single message. This is a
# simple denial-of-service guard: without it, a malicious or buggy peer could
# claim a message is gigabytes long and exhaust our memory.
MAX_MESSAGE_BYTES = 8 * 1024 * 1024  # 8 MiB

# Number of random bytes used for each authentication nonce. 32 bytes (256
# bits) is comfortably large enough that nonces never collide in practice.
NONCE_BYTES = 32


class ProtocolError(Exception):
    """Raised when the peer violates the wire protocol or the connection drops."""


class AuthenticationError(ProtocolError):
    """Raised when the challenge/response handshake fails (wrong secret or impostor)."""


# ---------------------------------------------------------------------------
# Message framing
# ---------------------------------------------------------------------------

def _recv_exactly(sock: socket.socket, num_bytes: int) -> bytes:
    """Read exactly `num_bytes` from `sock`, looping until satisfied.

    `socket.recv` may return fewer bytes than requested, so we keep reading
    until we have everything (or the peer closes the connection).
    """
    chunks: list[bytes] = []
    remaining = num_bytes
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            # An empty bytes object means the peer closed the connection.
            raise ProtocolError("connection closed while reading message")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def send_message(sock: socket.socket, obj: Any) -> None:
    """Serialise `obj` to JSON and send it as one length-prefixed frame."""
    payload = json.dumps(obj).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ProtocolError(
            f"message too large to send: {len(payload)} bytes "
            f"(limit {MAX_MESSAGE_BYTES})"
        )
    # Send the 4-byte length, then the payload itself.
    sock.sendall(_LENGTH_PREFIX.pack(len(payload)) + payload)


def recv_message(sock: socket.socket) -> Any:
    """Read one length-prefixed frame and return the decoded JSON object."""
    header = _recv_exactly(sock, _LENGTH_PREFIX.size)
    (length,) = _LENGTH_PREFIX.unpack(header)
    if length > MAX_MESSAGE_BYTES:
        raise ProtocolError(
            f"peer announced oversized message: {length} bytes "
            f"(limit {MAX_MESSAGE_BYTES})"
        )
    payload = _recv_exactly(sock, length)
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"received malformed JSON: {exc}") from exc


# ---------------------------------------------------------------------------
# Authentication (mutual HMAC challenge/response)
# ---------------------------------------------------------------------------

def _hmac_hex(secret: str, nonce: str) -> str:
    """Return the hex HMAC-SHA256 of `nonce` keyed by the shared `secret`."""
    return hmac.new(
        secret.encode("utf-8"),
        nonce.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _new_nonce() -> str:
    """Return a fresh, unpredictable nonce as a hex string."""
    return secrets.token_hex(NONCE_BYTES)


# -- public handshake primitives -------------------------------------------
# These three small functions are the building blocks of the handshake. They
# are transport-agnostic (no sockets, no JSON), so the raw-socket console, the
# WebSocket web console, and the agent can all share exactly the same crypto.

def new_challenge() -> str:
    """Return a fresh, unpredictable challenge nonce (hex string)."""
    return _new_nonce()


def proof_for(secret: str, nonce: str) -> str:
    """Return the HMAC proof that a holder of `secret` returns for `nonce`."""
    return _hmac_hex(secret, nonce)


def verify_proof(secret: str, nonce: str, proof: object) -> bool:
    """Constant-time check that `proof` is the correct HMAC for `nonce`.

    Uses hmac.compare_digest so the comparison does not leak, through timing,
    how many leading characters matched.
    """
    return isinstance(proof, str) and hmac.compare_digest(proof, _hmac_hex(secret, nonce))


# -- transport-agnostic mutual handshake -----------------------------------
# `send(obj)` transmits one JSON-serialisable message; `recv()` returns the
# next one. By accepting these callables instead of a socket, the same logic
# drives both TCP sockets and WebSockets.

def server_authenticate_io(send, recv, secret: str) -> None:
    """Console half of the mutual handshake over abstract send/recv callables.

    Steps (the console is the "server" here):
        1. Send a random challenge nonce to the agent.
        2. Receive the agent's response HMAC *and* the agent's own challenge.
        3. Verify the agent's HMAC. If wrong, abort.
        4. Prove ourselves by answering the agent's challenge.
    """
    server_nonce = new_challenge()
    send({"type": "auth_challenge", "nonce": server_nonce})

    reply = recv()
    if not isinstance(reply, dict) or reply.get("type") != "auth_response":
        raise AuthenticationError("expected auth_response from agent")
    if not verify_proof(secret, server_nonce, reply.get("proof", "")):
        raise AuthenticationError("agent failed authentication (bad secret)")
    agent_nonce = reply.get("nonce", "")
    if not isinstance(agent_nonce, str) or not agent_nonce:
        raise AuthenticationError("agent did not supply a challenge nonce")

    # The agent is genuine; now prove ourselves to it (mutual authentication).
    send({"type": "auth_confirm", "proof": proof_for(secret, agent_nonce)})


def client_authenticate_io(send, recv, secret: str) -> None:
    """Agent half of the mutual handshake over abstract send/recv callables.

    Mirror image of `server_authenticate_io`:
        1. Receive the console's challenge nonce.
        2. Answer it, and include our own fresh challenge nonce.
        3. Verify the console's answer to our challenge.
    """
    challenge = recv()
    if not isinstance(challenge, dict) or challenge.get("type") != "auth_challenge":
        raise AuthenticationError("expected auth_challenge from console")
    server_nonce = challenge.get("nonce", "")
    if not isinstance(server_nonce, str) or not server_nonce:
        raise AuthenticationError("console did not supply a challenge nonce")

    client_nonce = new_challenge()
    send({
        "type": "auth_response",
        "proof": proof_for(secret, server_nonce),
        "nonce": client_nonce,
    })

    confirm = recv()
    if not isinstance(confirm, dict) or confirm.get("type") != "auth_confirm":
        raise AuthenticationError("expected auth_confirm from console")
    if not verify_proof(secret, client_nonce, confirm.get("proof", "")):
        raise AuthenticationError("console failed authentication (possible impostor)")


# -- raw-socket convenience wrappers ---------------------------------------

def server_authenticate(sock: socket.socket, secret: str) -> None:
    """Console half of the handshake over a raw TCP socket."""
    server_authenticate_io(
        lambda obj: send_message(sock, obj),
        lambda: recv_message(sock),
        secret,
    )


def client_authenticate(sock: socket.socket, secret: str) -> None:
    """Agent half of the handshake over a raw TCP socket."""
    client_authenticate_io(
        lambda obj: send_message(sock, obj),
        lambda: recv_message(sock),
        secret,
    )


# ---------------------------------------------------------------------------
# Optional TLS confidentiality
# ---------------------------------------------------------------------------

def maybe_wrap_tls_server(
    sock: socket.socket,
    certfile: Optional[str],
    keyfile: Optional[str],
) -> socket.socket:
    """Wrap a console-side socket in TLS if a certificate was supplied.

    If `certfile` is None the socket is returned unchanged (plaintext), which
    is acceptable only on a trusted, isolated lab network. See the README for
    how to generate a self-signed certificate with one openssl command.
    """
    if not certfile:
        return sock
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=certfile, keyfile=keyfile or certfile)
    return context.wrap_socket(sock, server_side=True)


def maybe_wrap_tls_client(
    sock: socket.socket,
    cafile: Optional[str],
    server_hostname: Optional[str],
) -> socket.socket:
    """Wrap an agent-side socket in TLS if a CA certificate was supplied.

    When `cafile` points at the console's self-signed certificate the agent
    verifies it, which (together with HMAC mutual auth) protects against
    man-in-the-middle interception.
    """
    if not cafile:
        return sock
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=cafile)
    return context.wrap_socket(sock, server_hostname=server_hostname or "localhost")


# ---------------------------------------------------------------------------
# Shared-secret loading
# ---------------------------------------------------------------------------

def load_shared_secret(explicit: Optional[str] = None) -> str:
    """Resolve the shared secret, preferring the most secure source available.

    Order of precedence:
        1. An explicit value passed on the command line (handy for demos, but
           visible in the process list — avoid for anything real).
        2. The RAT_SHARED_SECRET environment variable (the recommended source).

    Hardcoding a secret in source code is intentionally NOT supported: secrets
    do not belong in version control.
    """
    if explicit:
        return explicit
    env_secret = os.environ.get("RAT_SHARED_SECRET")
    if env_secret:
        return env_secret
    raise SystemExit(
        "No shared secret configured.\n"
        "Set one with:  export RAT_SHARED_SECRET='your-strong-passphrase'\n"
        "or pass --secret on the command line (less secure)."
    )
