#!/usr/bin/env python3
"""
console.py — the operator's control console of the Remote Administration Tool
=============================================================================

Run this program on the machine you administer FROM. It:
    * Listens for incoming agent connections.
    * Authenticates each agent with the shared secret (mutual HMAC handshake).
    * Logs every connection event to screen and to a file.
    * Displays the system information each agent reports.
    * Lets you, the operator, issue commands to a connected agent.

Concurrency model:
    Each accepted agent is handled on its own thread so that authentication or a
    slow agent never blocks the listener. For this educational tool you drive
    ONE agent interactively at a time from the main thread's prompt; additional
    agents are accepted, logged, and parked until you switch to them.

Educational / authorised use only.
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

import protocol


@dataclass
class AgentConnection:
    """Bookkeeping for one connected, authenticated agent."""
    sock: socket.socket
    address: tuple[str, int]
    info: dict[str, Any] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    alive: bool = True

    @property
    def label(self) -> str:
        host = self.info.get("hostname", "?")
        return f"{host} ({self.address[0]}:{self.address[1]})"


class Console:
    """Holds shared state: the registry of connected agents and the audit log."""

    def __init__(self, secret: str, log: logging.Logger) -> None:
        self.secret = secret
        self.log = log
        self._agents: dict[int, AgentConnection] = {}
        self._next_id = 1
        self._registry_lock = threading.Lock()

    # -- agent registry ----------------------------------------------------

    def register(self, conn: AgentConnection) -> int:
        with self._registry_lock:
            agent_id = self._next_id
            self._next_id += 1
            self._agents[agent_id] = conn
            return agent_id

    def unregister(self, agent_id: int) -> None:
        with self._registry_lock:
            self._agents.pop(agent_id, None)

    def get(self, agent_id: int) -> Optional[AgentConnection]:
        with self._registry_lock:
            return self._agents.get(agent_id)

    def snapshot(self) -> list[tuple[int, AgentConnection]]:
        with self._registry_lock:
            return sorted(self._agents.items())

    # -- per-agent handling ------------------------------------------------

    def handle_agent(self, raw_sock: socket.socket, address: tuple[str, int],
                     certfile: Optional[str], keyfile: Optional[str]) -> None:
        """Authenticate a newly accepted agent and read its initial hello."""
        self.log.info("incoming connection from %s:%s", *address)
        try:
            sock = protocol.maybe_wrap_tls_server(raw_sock, certfile, keyfile)
            # The console plays the "server" role in the mutual handshake.
            protocol.server_authenticate(sock, self.secret)
        except protocol.AuthenticationError as exc:
            self.log.warning("AUTH FAILED from %s:%s — %s", address[0], address[1], exc)
            raw_sock.close()
            return
        except (protocol.ProtocolError, OSError) as exc:
            self.log.warning("handshake error from %s:%s — %s", address[0], address[1], exc)
            raw_sock.close()
            return

        conn = AgentConnection(sock=sock, address=address)

        # Expect the agent's unsolicited hello carrying its system info.
        try:
            hello = protocol.recv_message(sock)
            if isinstance(hello, dict) and hello.get("type") == "hello":
                conn.info = hello.get("data", {})
        except protocol.ProtocolError as exc:
            self.log.warning("no hello from %s:%s — %s", address[0], address[1], exc)
            sock.close()
            return

        agent_id = self.register(conn)
        self.log.info("AUTH OK: agent #%d is %s", agent_id, conn.label)
        self._print_sysinfo(agent_id, conn.info)
        print(f"\n[console] Agent #{agent_id} connected: {conn.label}. "
              f"Type 'use {agent_id}' to control it.\n> ", end="", flush=True)

        # Keep the connection open. The interactive thread does the talking;
        # here we just detect when the socket drops.
        try:
            # Block on the socket; the request/response traffic is driven from
            # the interactive prompt under the connection lock, so here we only
            # wait for the peer to close (recv returns empty).
            sock.settimeout(1.0)
            while conn.alive:
                try:
                    # Peek without consuming: if the agent closed, recv returns b"".
                    data = sock.recv(1, socket.MSG_PEEK)
                    if not data:
                        break
                except socket.timeout:
                    continue
                except OSError:
                    break
        finally:
            conn.alive = False
            self.unregister(agent_id)
            try:
                sock.close()
            except OSError:
                pass
            self.log.info("agent #%d disconnected (%s)", agent_id, conn.label)

    # -- request/response over a connection --------------------------------

    def request(self, conn: AgentConnection, payload: dict[str, Any]) -> Any:
        """Send a request to one agent and wait for its single response.

        The per-connection lock serialises access so the background liveness
        loop and the interactive prompt never read/write the socket at once.
        """
        with conn.lock:
            protocol.send_message(conn.sock, payload)
            return protocol.recv_message(conn.sock)

    # -- pretty printing ---------------------------------------------------

    def _print_sysinfo(self, agent_id: int, info: dict[str, Any]) -> None:
        print("\n" + "-" * 60)
        print(f"  System information — agent #{agent_id}")
        print("-" * 60)
        rows = [
            ("Hostname", info.get("hostname")),
            ("Operating system", info.get("os")),
            ("OS detail", info.get("os_detail")),
            ("Python version", info.get("python_version")),
            ("Current user", info.get("current_user")),
            ("CPU cores", info.get("cpu_count")),
            ("CPU usage", f"{info.get('cpu_percent')}%"),
            ("Memory usage", f"{info.get('memory_percent')}% "
                             f"({info.get('memory_used_mb')} / {info.get('memory_total_mb')} MB)"),
        ]
        for label, value in rows:
            print(f"  {label:<18}: {value}")
        print("-" * 60)


# ---------------------------------------------------------------------------
# Interactive operator prompt
# ---------------------------------------------------------------------------

HELP_TEXT = """\
Commands:
  list                 List connected agents.
  use <id>             Select an agent to control.
  info                 Re-fetch and show the selected agent's system info.
  ping                 Latency check against the selected agent.
  exec <command...>    Run a command on the selected agent.
                       (Allowed commands depend on the agent's safety mode.)
  disconnect           Tell the selected agent to disconnect.
  help                 Show this help.
  quit                 Shut the console down.
"""


def interactive_loop(console: Console) -> None:
    """The operator's REPL. Runs on the main thread."""
    selected: Optional[int] = None
    print(HELP_TEXT)
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            continue
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("quit", "exit"):
            break
        if cmd == "help":
            print(HELP_TEXT)
            continue
        if cmd == "list":
            agents = console.snapshot()
            if not agents:
                print("  (no agents connected)")
            for aid, conn in agents:
                marker = "*" if aid == selected else " "
                print(f" {marker} #{aid}: {conn.label}")
            continue
        if cmd == "use":
            if not arg.isdigit() or console.get(int(arg)) is None:
                print("  No such agent. Try 'list'.")
                continue
            selected = int(arg)
            print(f"  Now controlling agent #{selected}: {console.get(selected).label}")
            continue

        # Everything below needs a selected, still-connected agent.
        conn = console.get(selected) if selected is not None else None
        if conn is None:
            print("  Select an agent first with 'use <id>'.")
            continue

        try:
            if cmd == "info":
                resp = console.request(conn, {"action": "sysinfo"})
                if resp.get("type") == "sysinfo":
                    conn.info = resp["data"]
                    console._print_sysinfo(selected, conn.info)
            elif cmd == "ping":
                resp = console.request(conn, {"action": "ping"})
                print(f"  pong: {resp}")
            elif cmd == "exec":
                if not arg:
                    print("  usage: exec <command>")
                    continue
                console.log.warning("operator -> agent #%d EXEC: %r", selected, arg)
                resp = console.request(conn, {"action": "exec", "command": arg})
                _print_exec_result(resp)
            elif cmd == "disconnect":
                console.request(conn, {"action": "shutdown"})
                print(f"  asked agent #{selected} to disconnect")
                selected = None
            else:
                print("  Unknown command. Type 'help'.")
        except protocol.ProtocolError as exc:
            print(f"  agent #{selected} error/disconnected: {exc}")
            selected = None


def _print_exec_result(resp: Any) -> None:
    if not isinstance(resp, dict) or resp.get("type") != "exec_result":
        print(f"  unexpected response: {resp}")
        return
    result = resp.get("result", {})
    if not result.get("ok"):
        print(f"  [denied/error] {result.get('error')}")
        return
    print(f"  returncode: {result.get('returncode')}")
    if result.get("stdout"):
        print("  --- stdout ---")
        print(result["stdout"].rstrip())
    if result.get("stderr"):
        print("  --- stderr ---")
        print(result["stderr"].rstrip())


# ---------------------------------------------------------------------------
# Server bootstrap
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Educational remote administration CONSOLE (the operator's server).",
    )
    parser.add_argument("--host", default="0.0.0.0",
                        help="Address to bind. Default: 0.0.0.0 (all interfaces).")
    parser.add_argument("--port", type=int, default=9009,
                        help="Port to listen on. Default: 9009")
    parser.add_argument("--secret", default=None,
                        help="Shared secret (prefer the RAT_SHARED_SECRET env var instead).")
    parser.add_argument("--tls-cert", default=None,
                        help="Path to TLS certificate (enables encryption).")
    parser.add_argument("--tls-key", default=None,
                        help="Path to TLS private key (defaults to --tls-cert).")
    parser.add_argument("--log-file", default="console_audit.log",
                        help="Audit log path. Default: console_audit.log")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [console] %(levelname)s %(message)s",
        handlers=[logging.FileHandler(args.log_file), logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("console")

    secret = protocol.load_shared_secret(args.secret)
    console = Console(secret, log)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((args.host, args.port))
    listener.listen(16)

    print("=" * 70)
    print("  Remote Administration CONSOLE")
    print(f"  Listening on {args.host}:{args.port}")
    print(f"  TLS: {'ON' if args.tls_cert else 'OFF (trusted LAN/VM only)'}")
    print(f"  Audit log: {args.log_file}")
    print("=" * 70)
    log.info("console listening on %s:%s", args.host, args.port)

    # Accept connections on a background thread so the operator prompt is free.
    def accept_loop() -> None:
        while True:
            try:
                raw_sock, address = listener.accept()
            except OSError:
                break
            threading.Thread(
                target=console.handle_agent,
                args=(raw_sock, address, args.tls_cert, args.tls_key),
                daemon=True,
            ).start()

    threading.Thread(target=accept_loop, daemon=True).start()

    try:
        interactive_loop(console)
    except KeyboardInterrupt:
        pass
    finally:
        log.info("console shutting down")
        listener.close()
        print("\nConsole stopped.")


if __name__ == "__main__":
    main()
