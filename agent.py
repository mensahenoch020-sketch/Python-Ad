#!/usr/bin/env python3
"""
agent.py — the managed endpoint of the educational Remote Administration Tool
=============================================================================

Run this program on the machine you want to administer (your own machine, a VM,
or a host you are explicitly authorised to manage). It does NOTHING until you
explicitly start it, and it prints a loud banner so the person at the keyboard
always knows the machine has become remotely reachable.

What it does once started:
    * Connects OUT to the console (server) you specify.
    * Proves its identity with the shared secret (mutual HMAC handshake).
    * Reports basic system information on request.
    * Executes administrative commands sent by the console.

Safety model (read this before using --allow-shell):
    * By default the agent runs in ALLOWLIST mode: it will only run a small set
      of read-only diagnostic commands. This is enough to demonstrate remote
      administration without handing over the whole machine.
    * Passing --allow-shell turns on ARBITRARY command execution. This is the
      full "remote control" capability and is genuinely dangerous: anyone with
      the shared secret can run any command as your user. The agent forces you
      to type an explicit confirmation before this mode activates, and every
      single command is written to the local audit log regardless of mode.

Educational / authorised use only.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import platform
import shlex
import socket
import subprocess
import sys
import time
from typing import Any

import protocol

# psutil gives us CPU and memory usage in a cross-platform way. It is the only
# third-party dependency; see requirements.txt.
try:
    import psutil
except ImportError:  # pragma: no cover - guidance for first-time users
    sys.exit(
        "This tool needs the 'psutil' package for CPU/memory stats.\n"
        "Install it with:  python -m pip install psutil"
    )


# The commands the agent is willing to run in the default (safe) mode. Each key
# is the name the console asks for; the value is the real argument list that we
# hand to subprocess WITHOUT a shell, so there is no shell-injection surface.
# Every entry here is read-only and non-destructive on purpose.
SAFE_COMMANDS: dict[str, list[str]] = {
    "uptime": ["uptime"] if platform.system() != "Windows" else ["cmd", "/c", "net statistics workstation"],
    "disk": ["df", "-h"] if platform.system() != "Windows" else ["cmd", "/c", "wmic logicaldisk get size,freespace,caption"],
    "processes": ["ps", "aux"] if platform.system() != "Windows" else ["cmd", "/c", "tasklist"],
    "whoami": ["whoami"],
    "date": ["date"] if platform.system() != "Windows" else ["cmd", "/c", "date /t"],
}


def collect_system_info() -> dict[str, Any]:
    """Gather the basic, non-sensitive system information the console displays."""
    # cpu_percent with a short interval gives a meaningful instantaneous figure
    # rather than 0.0 on the very first call.
    cpu_percent = psutil.cpu_percent(interval=0.3)
    mem = psutil.virtual_memory()
    return {
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "os_detail": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_percent": cpu_percent,
        "cpu_count": psutil.cpu_count(logical=True),
        "memory_percent": mem.percent,
        "memory_total_mb": round(mem.total / (1024 * 1024)),
        "memory_used_mb": round(mem.used / (1024 * 1024)),
        "current_user": getpass.getuser(),
    }


def run_exec(command: str, allow_shell: bool, log: logging.Logger) -> dict[str, Any]:
    """Execute an administrative command and return its result.

    `command` is the request from the console. In allowlist mode it must be one
    of SAFE_COMMANDS' keys. In --allow-shell mode it is run as an arbitrary
    shell command line.
    """
    # Audit EVERY command attempt before running it, so the local log is a
    # complete record even if the command later fails or the process is killed.
    log.warning("EXEC requested: %r (allow_shell=%s)", command, allow_shell)

    if allow_shell:
        # Arbitrary execution. We still avoid `shell=True` where we can by
        # splitting the command; but to honour genuinely arbitrary command
        # lines (pipes, redirects) we fall back to the shell. This is the
        # dangerous mode and is gated behind explicit operator consent at
        # startup.
        try:
            completed = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            log.error("EXEC timed out: %r", command)
            return {"ok": False, "error": "command timed out after 30s"}
        return {
            "ok": True,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-10000:],
            "stderr": completed.stderr[-10000:],
        }

    # Allowlist mode: only run pre-approved, read-only commands.
    key = command.strip().lower()
    if key not in SAFE_COMMANDS:
        log.warning("EXEC denied (not in allowlist): %r", command)
        return {
            "ok": False,
            "error": (
                f"command '{command}' is not allowed in safe mode. "
                f"Allowed: {', '.join(sorted(SAFE_COMMANDS))}. "
                "Start the agent with --allow-shell for arbitrary commands."
            ),
        }
    try:
        completed = subprocess.run(
            SAFE_COMMANDS[key],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.error("EXEC failed: %r (%s)", command, exc)
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-10000:],
        "stderr": completed.stderr[-10000:],
    }


def handle_request(request: Any, allow_shell: bool, log: logging.Logger) -> dict[str, Any]:
    """Dispatch a single request object from the console to the right handler."""
    if not isinstance(request, dict):
        return {"type": "error", "error": "malformed request"}

    action = request.get("action")
    if action == "ping":
        return {"type": "pong", "time": time.time()}
    if action == "sysinfo":
        return {"type": "sysinfo", "data": collect_system_info()}
    if action == "exec":
        command = request.get("command", "")
        return {"type": "exec_result", "command": command,
                "result": run_exec(command, allow_shell, log)}
    if action == "shutdown":
        # "shutdown" here means "disconnect the agent", not "power off the box".
        return {"type": "bye"}
    return {"type": "error", "error": f"unknown action: {action!r}"}


def confirm_remote_control() -> None:
    """Force the human at the keyboard to acknowledge arbitrary-control mode."""
    print("\n" + "!" * 70)
    print("  WARNING: --allow-shell enables ARBITRARY remote command execution.")
    print("  Anyone holding the shared secret can run any command as your user.")
    print("  Only continue on a machine you own or are authorised to manage,")
    print("  on a trusted/isolated network (ideally a VM).")
    print("!" * 70)
    answer = input("Type 'I CONSENT' to continue, anything else to abort: ").strip()
    if answer != "I CONSENT":
        sys.exit("Aborted: explicit consent not given.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Educational remote administration AGENT (the managed endpoint).",
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="Console (server) address to connect to. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=9009,
                        help="Console port. Default: 9009")
    parser.add_argument("--secret", default=None,
                        help="Shared secret (prefer the RAT_SHARED_SECRET env var instead).")
    parser.add_argument("--allow-shell", action="store_true",
                        help="DANGEROUS: permit arbitrary command execution (requires consent).")
    parser.add_argument("--reconnect", action="store_true",
                        help="Automatically reconnect if the console drops the connection.")
    parser.add_argument("--ca-cert", default=None,
                        help="Path to the console's certificate to enable/verify TLS.")
    parser.add_argument("--log-file", default="agent_audit.log",
                        help="Local audit log path. Default: agent_audit.log")
    args = parser.parse_args()

    # Configure audit logging: everything goes both to the console screen and to
    # a local file, so there is always a durable record of what happened.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [agent] %(levelname)s %(message)s",
        handlers=[logging.FileHandler(args.log_file), logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("agent")

    secret = protocol.load_shared_secret(args.secret)

    # Loud, explicit start banner. The machine is NOT reachable until this runs.
    print("=" * 70)
    print("  Remote Administration AGENT starting")
    print(f"  This machine will connect to console at {args.host}:{args.port}")
    print(f"  Mode: {'ARBITRARY SHELL (dangerous)' if args.allow_shell else 'SAFE allowlist'}")
    print(f"  Audit log: {args.log_file}")
    print("=" * 70)

    if args.allow_shell:
        confirm_remote_control()

    while True:
        try:
            run_session(args, secret, log)
        except (protocol.ProtocolError, OSError) as exc:
            log.error("session ended: %s", exc)
        if not args.reconnect:
            break
        log.info("reconnecting in 5s (Ctrl-C to stop)...")
        time.sleep(5)


def run_session(args: argparse.Namespace, secret: str, log: logging.Logger) -> None:
    """Open one connection to the console and service it until it closes."""
    with socket.create_connection((args.host, args.port), timeout=10) as raw_sock:
        sock = protocol.maybe_wrap_tls_client(raw_sock, args.ca_cert, args.host)
        log.info("connected to console %s:%s", args.host, args.port)

        # Prove identity in both directions before doing anything else.
        protocol.client_authenticate(sock, secret)
        log.info("mutual authentication succeeded")

        # Send an unsolicited hello with system info so the console can display
        # the endpoint immediately on connect.
        protocol.send_message(sock, {"type": "hello", "data": collect_system_info()})

        sock.settimeout(None)  # block waiting for console commands
        while True:
            request = protocol.recv_message(sock)
            log.info("received request: %s", request.get("action") if isinstance(request, dict) else request)
            response = handle_request(request, args.allow_shell, log)
            protocol.send_message(sock, response)
            if response.get("type") == "bye":
                log.info("console requested disconnect")
                return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAgent stopped by user.")
