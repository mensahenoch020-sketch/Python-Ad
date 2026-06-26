# Educational Remote Administration Tool (RAT)

A small, heavily commented Python project that demonstrates how a **secure
remote system administration tool** works: an *agent* runs on a managed machine
and connects to an operator's *console*, authenticates with a shared secret,
reports system information, and executes administrative commands.

It is built to **teach the concepts** behind tools like SSH, Ansible, Salt, and
commercial endpoint-management agents — authentication, message framing, audit
logging, and the trade-off between convenience and the danger of arbitrary
remote command execution.

> ⚠️ **Authorised, educational use only.** Run this only on machines you own or
> are explicitly authorised to administer, ideally inside virtual machines on an
> isolated network. A tool that runs commands sent over a network is, by its
> nature, dual-use. Deploying software like this on a computer without the
> owner's knowledge and consent is unethical and, in most jurisdictions,
> illegal. This project intentionally favours transparency over stealth: it
> announces itself loudly, logs everything, and requires explicit consent for
> its dangerous mode.

---

## 1. What it does

| Capability | Detail |
|---|---|
| **Explicit start** | The agent does nothing until *you* run it, and it prints a loud start banner. |
| **System reporting** | Hostname, OS, Python version, CPU usage, memory usage, core count, current user. |
| **Authentication** | Mutual HMAC-SHA256 challenge/response using a pre-shared secret. The secret never crosses the network. |
| **Connection logging** | Both programs write timestamped audit logs (screen + file) for connects, auth results, disconnects, and every command. |
| **Command execution** | *Safe mode* (default): a small allowlist of read-only diagnostics. *Shell mode* (`--allow-shell`): arbitrary commands, gated behind an explicit `I CONSENT` prompt. |
| **Optional TLS** | Supply a certificate to encrypt all traffic. Without it, use only on a trusted/isolated LAN. |

---

## 2. Networking architecture

```
   Operator's machine                         Managed machine (yours / a VM)
  ┌───────────────────┐                       ┌───────────────────┐
  │     console.py    │                       │      agent.py     │
  │  (the "server")   │                       │  (the "client")   │
  │                   │   1. TCP connect      │                   │
  │  listen :9009  ◄──┼───────────────────────┤  connect out      │
  │                   │                       │                   │
  │                   │   2. Mutual HMAC       │                   │
  │  challenge ──────►│      handshake        │                   │
  │  ◄──── response + new challenge            │                   │
  │  confirm ────────►│                       │                   │
  │                   │                       │                   │
  │                   │   3. hello + sysinfo  │                   │
  │  ◄────────────────┼───────────────────────┤                   │
  │                   │                       │                   │
  │                   │   4. request/response │                   │
  │  {action:exec} ──►│      (length-prefixed │                   │
  │  ◄──── {result}   │       JSON frames)    │                   │
  └───────────────────┘                       └───────────────────┘
```

**Key design choices and *why*:**

1. **The agent connects *out* to the console.** This mirrors how real fleet
   agents work and is friendlier to firewalls/NAT (only the console needs an
   open inbound port). It also means the console never has to scan or reach into
   networks looking for hosts.

2. **Length-prefixed JSON frames** (`protocol.py`). TCP is a byte *stream* with
   no message boundaries. Every message is sent as a 4-byte big-endian length
   followed by that many bytes of UTF-8 JSON, so the receiver can always
   reassemble exact messages. A maximum size cap guards against memory-exhaustion.

3. **Mutual HMAC-SHA256 challenge/response** (`protocol.py`). The secret is
   never transmitted. Each side sends the other a random *nonce*; each proves it
   knows the secret by returning `HMAC(secret, nonce)`. Fresh nonces make
   captured handshakes useless for replay. Mutual proof means an agent will
   refuse to talk to an impostor console. Comparisons use
   `hmac.compare_digest` (constant-time) to avoid timing leaks.

4. **Authentication ≠ encryption.** HMAC proves *who* you are talking to and that
   messages were not tampered with, but the JSON itself is readable on the wire.
   For confidentiality, enable **TLS** (section 5). On a closed lab network or
   between VMs on one host, plaintext is acceptable for learning.

5. **Audit logging everywhere.** The console logs connection events and every
   operator command; the agent logs every command it is asked to run *before*
   running it. Transparency is the opposite of how malware behaves, and it is
   what makes this a *defensible* administration tool.

---

## 3. Files

| File | Role |
|---|---|
| `protocol.py` | Shared wire protocol: framing, mutual HMAC auth, optional TLS, secret loading. |
| `agent.py` | The managed endpoint. Reports info and runs commands. Run on the target/VM. |
| `console.py` | The operator's control server. Run on your admin machine. |
| `requirements.txt` | The single dependency (`psutil`). |

---

## 4. Setup

```bash
# 1. (Recommended) create a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. install the one dependency
python -m pip install -r requirements.txt

# 3. choose a strong shared secret and export it on BOTH machines
export RAT_SHARED_SECRET='correct-horse-battery-staple-change-me'
#   (Windows PowerShell:  $env:RAT_SHARED_SECRET = '...')
```

The secret is read from the `RAT_SHARED_SECRET` environment variable so it never
appears in source code or the process list. (`--secret` exists for quick demos
but is less secure because it is visible in `ps`.)

---

## 5. Running it

### Quick local test (one machine, two terminals)

**Terminal A — start the console (server):**
```bash
python console.py --host 127.0.0.1 --port 9009
```

**Terminal B — start the agent (client) in safe mode:**
```bash
python agent.py --host 127.0.0.1 --port 9009
```

On connect, the console prints the agent's system information. Then drive it from
the console prompt:

```
> list
> use 1
> info
> ping
> exec uptime
> exec disk
> disconnect
> quit
```

### Enabling arbitrary command execution (the full "remote control")

Start the agent with `--allow-shell`. It will refuse to proceed until you type
`I CONSENT` at the keyboard, and it logs every command:

```bash
python agent.py --host 127.0.0.1 --port 9009 --allow-shell
```

Now `exec` on the console can run any command line on the agent, e.g.
`exec ls -la /tmp`. **Use this only on a machine you control.**

### On a local network or between virtual machines

1. Run `console.py` on the operator host; note its LAN IP (e.g. `192.168.1.50`).
2. Make sure the console's port (default `9009`) is allowed through its firewall.
3. On the managed host/VM, point the agent at that IP:
   ```bash
   python agent.py --host 192.168.1.50 --port 9009
   ```
4. Set the **same** `RAT_SHARED_SECRET` on both machines.

A typical safe lab setup: two VMs on a host-only / internal network so the
traffic never leaves your computer.

### Adding TLS encryption (recommended beyond a closed lab)

Generate a self-signed certificate for the console:

```bash
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout console_key.pem -out console_cert.pem \
  -days 365 -subj "/CN=localhost"
```

Start the console with TLS, and point the agent at the certificate so it can
verify (and thus resist man-in-the-middle attacks):

```bash
# console
python console.py --port 9009 --tls-cert console_cert.pem --tls-key console_key.pem

# agent (copy console_cert.pem to the agent machine first)
python agent.py --host <console-ip> --port 9009 --ca-cert console_cert.pem
```

> The self-signed certificate's `CN` must match the `--host` the agent dials
> (use `localhost`/`127.0.0.1` for local tests, or the console's hostname/IP on
> a LAN). For real deployments use a certificate from a trusted CA.

---

## 6. Security model & limitations (read this)

This is a **teaching tool**, not production software. It deliberately keeps the
code small and readable, which means it omits things a real agent would need:

- **No authorisation tiers.** Anyone with the shared secret has full access.
  Real systems use per-user keys, roles, and revocation.
- **Shared secret, not per-agent keys.** A leaked secret compromises everything.
  Production tools use unique per-agent credentials (e.g. mutual-TLS client
  certs).
- **No sandboxing of `--allow-shell`.** Commands run with the agent user's full
  privileges. That is exactly why it is off by default and consent-gated.
- **Plaintext unless you enable TLS.** Always enable TLS off a closed network.
- **No persistence / auto-start, by design.** The agent only runs when you start
  it. This tool will never install itself, hide, or survive a reboot — those are
  hallmarks of malware, not administration software.

### What makes this *administration* and not *malware*

| Administration tool (this) | Malware / backdoor |
|---|---|
| Runs only when explicitly started | Persists & auto-starts covertly |
| Loud banner; logs everything | Hides; avoids logging |
| Consent required for shell mode | No consent, ever |
| Run on machines you own/are authorised for | Deployed without owner knowledge |
| Mutual auth so the *agent* trusts the console | One-way control |

Keep your use on the left side of that table.

---

## 7. Ideas for further learning

- Replace the shared secret with per-agent mutual-TLS client certificates.
- Add an operator allow/deny audit trail signed so logs cannot be altered.
- Add a rate limiter / lockout after repeated auth failures.
- Stream long-running command output instead of buffering it.
- Add a command allowlist *policy file* the agent loads at start.
