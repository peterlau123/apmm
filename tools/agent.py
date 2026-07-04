#!/usr/bin/env python3
"""
agent.py - Daemon-based SSH agent for Qizhi (Shterm) bastion

Architecture:
  connect.bat    -> python agent.py serve    (prompts passwords ONCE, holds SSH session)
  run/upload/download -> JSON over TCP to daemon  (no re-auth)
  shell.bat      -> python agent.py shell
  check.bat      -> python agent.py ping
  disconnect.bat -> python agent.py stop
"""

import paramiko
import argparse
import select
import time
import sys
import os
import getpass
import json
import socket
import threading
import socketserver
import uuid
import re

_ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]|\x1b[()][AB012]|\r')

CREDS_FILE        = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bastion_creds")
DAEMON_HOST       = "127.0.0.1"
DAEMON_PORT       = 19922
SECOND_PWD_PROMPT = "2nd Password:"
SHELL_PROMPTS     = ["$ ", "# "]
DEFAULT_PROFILE   = "default"

# Defaults (overridden by .bastion_creds at runtime)
_DEFAULT_BASTION_HOST = "10.10.192.55"
_DEFAULT_BASTION_PORT = 22
_DEFAULT_BASTION_USER = "zhaokaihang/10.102.234.45/infra"


# ── Credential helpers ────────────────────────────────────────────────────────

def load_creds():
    """Return raw credentials/config JSON."""
    if os.path.exists(CREDS_FILE):
        with open(CREDS_FILE) as f:
            return json.load(f)
    return {}


def save_creds(data: dict):
    existing = load_creds()
    existing.update(data)
    write_creds(existing)


def write_creds(data: dict):
    with open(CREDS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    try:
        os.chmod(CREDS_FILE, 0o600)
    except Exception:
        pass


def _legacy_profile(data: dict):
    keys = ("host", "port", "user", "p1", "daemon_port")
    return {k: data[k] for k in keys if k in data}


def _profiles_from_creds(data: dict):
    profiles = data.get("profiles")
    if isinstance(profiles, dict):
        result = dict(profiles)
    else:
        result = {}

    legacy = _legacy_profile(data)
    if legacy and DEFAULT_PROFILE not in result:
        result[DEFAULT_PROFILE] = legacy
    return result


def list_profiles():
    return _profiles_from_creds(load_creds())


def get_profile(profile=DEFAULT_PROFILE):
    profiles = list_profiles()
    if profile in profiles:
        return dict(profiles[profile])
    if profile == DEFAULT_PROFILE:
        return {}
    raise KeyError(f"Profile not found: {profile}. Run: python agent.py setcreds {profile}")


def save_profile(profile: str, data: dict):
    existing = load_creds()
    profiles = _profiles_from_creds(existing)
    current = dict(profiles.get(profile, {}))
    current.update(data)
    profiles[profile] = current

    migrated = {
        k: v for k, v in existing.items()
        if k not in ("host", "port", "user", "p1", "daemon_port", "profiles")
    }
    migrated["profiles"] = profiles
    write_creds(migrated)


def daemon_port_for(creds: dict):
    return int(creds.get("daemon_port") or DAEMON_PORT)



def _prompt(label, default=None, secret=False):
    """Prompt user for a value; show default in brackets; use getpass for secrets."""
    prompt_str = f"{label}"
    if default:
        prompt_str += f" [{default}]"
    prompt_str += ": "
    if secret:
        val = getpass.getpass(prompt_str)
    else:
        val = input(prompt_str).strip()
    return val if val else default


# ── Channel I/O ────────────────────────────────────────────────────────────────

def _make_sentinel():
    """Return a per-call unique sentinel that cannot appear in normal command output."""
    return f"AGENT_{uuid.uuid4().hex}"


def recv_until(channel, patterns, timeout=20):
    chunks = []
    max_pat_len = max((len(p) for p in patterns), default=1)
    overlap = ""
    deadline = time.time() + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        ready, _, _ = select.select([channel], [], [], min(remaining, 1.0))
        if ready:
            chunk = channel.recv(65535).decode("utf-8", errors="replace")
            if not chunk:
                break
            chunks.append(chunk)
            check_area = overlap + chunk
            for pat in patterns:
                if pat in check_area:
                    return "".join(chunks)
            overlap = check_area[-max_pat_len:] if len(check_area) > max_pat_len else check_area
        if channel.exit_status_ready():
            break
    return "".join(chunks)


def _extract_command_output(raw, start, end):
    cleaned = _ANSI_ESCAPE.sub('', raw).replace("\r\n", "\n").replace("\r", "\n")

    idx1 = cleaned.find(start)
    if idx1 == -1:
        return cleaned.strip()
    idx2 = cleaned.find(start, idx1 + len(start))
    if idx2 == -1:
        return cleaned.strip()
    end_idx = cleaned.find(end, idx2 + len(start))
    if end_idx == -1:
        return cleaned[idx2 + len(start):].strip("\n")

    return cleaned[idx2 + len(start):end_idx].strip("\n")


# ── SSH session ────────────────────────────────────────────────────────────────

class BastionSession:
    def __init__(self, p1, p2, host=None, port=None, user=None):
        self.p1   = p1
        self.p2   = p2
        self.host = host or _DEFAULT_BASTION_HOST
        self.port = int(port or _DEFAULT_BASTION_PORT)
        self.user = user or _DEFAULT_BASTION_USER
        self.transport = None
        self.channel = None
        self.lock = threading.Lock()
        self._sftp = None
        self._sftp_unavailable = False

    def connect(self):
        self.transport = paramiko.Transport((self.host, self.port))
        self.transport.connect()
        self.transport.set_keepalive(15)

        def handler(title, instructions, fields):
            return [self.p1 for _ in fields]

        self.transport.auth_interactive(self.user, handler)
        if not self.transport.is_authenticated():
            raise Exception("1st password authentication failed")

        self.channel = self.transport.open_session()
        self.channel.get_pty(term="xterm", width=220, height=50)
        self.channel.invoke_shell()

        buf = ""
        second_sent = False
        deadline = time.time() + 50
        while time.time() < deadline:
            if self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode("utf-8", errors="replace")
                buf += chunk
                if not second_sent and SECOND_PWD_PROMPT in buf:
                    time.sleep(0.15)
                    self.channel.send(self.p2 + "\n")
                    second_sent = True
                    buf = ""
                if second_sent and any(p in buf for p in SHELL_PROMPTS):
                    break
            elif self.channel.exit_status_ready():
                break
            time.sleep(0.05)

        if not second_sent:
            raise Exception(f"Never got '2nd Password:' prompt.\nReceived: {buf[-300:]}")
        if not any(p in buf for p in SHELL_PROMPTS):
            raise Exception(f"No shell prompt after 2nd password.\nReceived: {buf[-300:]}")

        # Flush remaining banner/motd output and wait for a clean prompt.
        # Two-step: first confirm the echo was processed, then drain until
        # the shell prompt appears — same approach that was confirmed working.
        self.channel.send("echo __READY__\n")
        recv_until(self.channel, ["__READY__"], timeout=8)
        recv_until(self.channel, SHELL_PROMPTS, timeout=8)

    def _recover_channel(self):
        """Send Ctrl+C then confirm shell is responsive via sentinel.
        Returns True if channel is alive, False if it is dead."""
        try:
            self.channel.send("\x03")
            time.sleep(0.3)
            tok = _make_sentinel()
            self.channel.send(f"echo {tok}\n")
            recv_until(self.channel, [tok], timeout=8)
            return True
        except Exception:
            return False

    def run(self, cmd, timeout=120):
        start    = _make_sentinel() + "_START"
        end      = _make_sentinel() + "_END"
        end_line = "\n" + end
        
        # Base64 encode the command to protect ALL special characters (brackets, quotes, etc.)
        # This bypasses ALL shell interpretation layers, ensuring the command reaches the
        # remote shell exactly as intended.
        import base64
        cmd_b64 = base64.b64encode(cmd.encode('utf-8')).decode('ascii')
        
        with self.lock:
            # Execute via: eval $(base64 -d <<< '<encoded>')
            # The <<< here-string is POSIX-compliant and works in all modern bash versions.
            # This guarantees the command is decoded and executed verbatim.
            self.channel.send(f"echo {start}; eval $(base64 -d <<< '{cmd_b64}'); echo ''; echo {end}\n")
            raw = recv_until(self.channel, [end_line], timeout=timeout)

        if end_line not in raw:
            with self.lock:
                self._recover_channel()
            output = _extract_command_output(raw, start, end)
            return output, True

        return _extract_command_output(raw, start, end), False

    def send_input(self, text):
        """Send raw text to the channel (unblock a waiting prompt)."""
        with self.lock:
            self.channel.send(text if text.endswith("\n") else text + "\n")
            time.sleep(0.3)
            tok = _make_sentinel()
            self.channel.send(f"echo {tok}\n")
            buf = recv_until(self.channel, [tok], timeout=10)
        return buf.replace("\r", "").strip()

    def cancel(self):
        """Send Ctrl+C to interrupt the running command and restore shell prompt."""
        with self.lock:
            self._recover_channel()

    def _get_sftp(self):
        """Return a cached SFTPClient, opening one if needed.
        Raises RuntimeError if the bastion does not support the SFTP subsystem."""
        if self._sftp_unavailable:
            raise RuntimeError("SFTP subsystem is not available on this bastion")
        if self._sftp is None:
            try:
                self._sftp = paramiko.SFTPClient.from_transport(self.transport)
            except Exception as e:
                self._sftp_unavailable = True
                raise RuntimeError(
                    f"SFTP subsystem is not available on this bastion ({e}). "
                    "Falling back to shell-based transfer."
                ) from e
        return self._sftp

    # ── SFTP transfer ──────────────────────────────────────────────────────────

    def _invalidate_sftp(self):
        """Close and discard the cached SFTP client so it will be reopened on next use."""
        try:
            if self._sftp:
                self._sftp.close()
        except Exception:
            pass
        self._sftp = None
        self._sftp_unavailable = False

    def _upload_sftp(self, local_path, remote_path):
        file_size = os.path.getsize(local_path)
        try:
            sftp = self._get_sftp()

            def _progress(transferred, total):
                pct = transferred * 100 // total if total else 100
                print(f"\r  [sftp] uploading {transferred}/{total} bytes ({pct}%)  ", end="", flush=True)

            sftp.put(local_path, remote_path, callback=_progress if file_size > 0 else None)
            print(flush=True)
        except Exception:
            self._invalidate_sftp()
            raise

        # Verify via shell (independent of SFTP session state)
        # Use python3 to avoid shell redirection stderr noise on missing files
        size_out, _ = self.run(
            f"python3 -c \"import os; print(os.path.getsize('{remote_path}') "
            f"if os.path.isfile('{remote_path}') else -1)\"",
            timeout=15,
        )
        remote_size = int(size_out.strip()) if size_out.strip().lstrip('-').isdigit() else -2
        if remote_size != file_size:
            # -1 means file doesn't exist at all — SFTP is completely non-functional
            # on this bastion (silently accepts put() but writes nothing).
            # Mark unavailable immediately so _sftp_op won't retry.
            if remote_size == -1:
                self._sftp_unavailable = True
            raise Exception(
                f"Upload size mismatch after sftp.put: sent {file_size} bytes, "
                f"shell reports {remote_size} bytes on remote"
            )

    def _download_sftp(self, remote_path, local_path):
        # Check file exists via shell first (independent, reliable)
        stat_out, _ = self.run(
            f'test -f {remote_path} && wc -c < {remote_path} || echo "__NOT_FOUND__"',
            timeout=15,
        )
        stat_out = stat_out.strip()
        if stat_out == "__NOT_FOUND__" or not stat_out.isdigit():
            raise Exception(f"Remote file not found: {remote_path}")
        remote_size = int(stat_out)

        local_dir = os.path.dirname(local_path)
        if local_dir and not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)

        try:
            sftp = self._get_sftp()

            def _progress(transferred, total):
                pct = transferred * 100 // total if total else 100
                print(f"\r  [sftp] downloading {transferred}/{total} bytes ({pct}%)  ", end="", flush=True)

            sftp.get(remote_path, local_path, callback=_progress if remote_size > 0 else None)
            print(flush=True)
        except Exception:
            self._invalidate_sftp()
            raise

        # Verify locally
        local_size = os.path.getsize(local_path)
        if local_size != remote_size:
            raise Exception(
                f"Download size mismatch: remote {remote_size} bytes, local {local_size} bytes"
            )

    # ── Public API (SFTP with one reconnect retry) ────────────────────────────

    _BASTION_SFTP_FLAKY_MSG = (
        "The bastion's SFTP is currently unavailable (known Shterm flakiness: "
        "SFTP forwarding intermittently drops writes while returning success ACKs).\n"
        "Suggested actions:\n"
        "  1. Restart the daemon and retry — this usually recovers SFTP:\n"
        "       python3 agent.py -p <profile> stop\n"
        "       python3 agent.py serve <profile>\n"
        "  2. If restarting the daemon fails multiple times, transfer the file manually "
        "(scp, rsync, or other means).\n"
        "  3. For small text edits, use: python3 agent.py run \"sed -i '...' /path/to/file\""
    )

    def _sftp_op(self, op_fn, *args):
        """Run an SFTP operation with one reconnect retry.

        On first failure, _invalidate_sftp() has already been called inside
        the _upload/_download_sftp methods, so _get_sftp() will open a fresh
        SFTPClient on the retry. If _sftp_unavailable is set (bastion silently
        accepts SFTP but writes nothing), skip the retry immediately.
        """
        try:
            op_fn(*args)
            return True
        except Exception as first_err:
            if "Remote file not found" in str(first_err):
                raise
            if self._sftp_unavailable:
                raise first_err
            print(f"  [!] SFTP failed ({first_err}), retrying with new SFTP session...", flush=True)
            try:
                op_fn(*args)
                print("  [+] SFTP retry succeeded.", flush=True)
                return True
            except Exception as retry_err:
                if "Remote file not found" in str(retry_err):
                    raise
                raise retry_err

    def upload(self, local_path, remote_path):
        file_size = os.path.getsize(local_path)
        try:
            self._sftp_op(self._upload_sftp, local_path, remote_path)
        except Exception as e:
            if "Remote file not found" in str(e):
                raise
            raise Exception(
                f"[SFTP_FLAKY] Upload failed ({file_size / 1024 / 1024:.1f} MB). "
                f"SFTP is currently unavailable.\n" + self._BASTION_SFTP_FLAKY_MSG
            )
        return True

    def download(self, remote_path, local_path):
        try:
            self._sftp_op(self._download_sftp, remote_path, local_path)
        except Exception as e:
            if "Remote file not found" in str(e):
                raise
            raise Exception(
                f"[SFTP_FLAKY] Download failed. SFTP is currently unavailable.\n"
                + self._BASTION_SFTP_FLAKY_MSG
            )
        return True

    def open_shell_channel(self):
        """Open a second shell on the same transport — no 2nd password needed."""
        ch = self.transport.open_session()
        ch.get_pty(term="xterm", width=220, height=50)
        ch.invoke_shell()
        # Use a sentinel to confirm the new channel's shell is ready
        tok = _make_sentinel()
        ch.send(f"echo {tok}\n")
        recv_until(ch, [tok], timeout=20)
        return ch

    def close(self):
        for obj in (self._sftp, self.channel, self.transport):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass
        self._sftp = None


# ── Daemon server ──────────────────────────────────────────────────────────────

_session: BastionSession = None
_server = None


class Handler(socketserver.BaseRequestHandler):

    def handle(self):
        try:
            buf = b""
            while b"\n" not in buf:
                chunk = self.request.recv(4096)
                if not chunk:
                    return
                buf += chunk
            req = json.loads(buf.split(b"\n")[0].decode())
        except Exception as e:
            self._send({"status": "error", "output": f"Bad request: {e}"})
            return

        action = req.get("action", "")
        try:
            if action == "ping":
                self._send({"status": "ok", "output": "pong"})
            elif action == "run":
                out, timed_out = _session.run(req["cmd"], timeout=req.get("timeout", 120))
                self._send({"status": "timeout" if timed_out else "ok", "output": out})
            elif action == "upload":
                ok = _session.upload(req["local"], req["remote"])
                self._send({"status": "ok" if ok else "error", "output": ""})
            elif action == "download":
                ok = _session.download(req["remote"], req["local"])
                self._send({"status": "ok" if ok else "error", "output": ""})
            elif action == "send":
                out = _session.send_input(req.get("text", ""))
                self._send({"status": "ok", "output": out})
            elif action == "cancel":
                _session.cancel()
                self._send({"status": "ok", "output": "Ctrl+C sent, channel recovered"})
            elif action == "shell":
                self._handle_shell()
            elif action == "stop":
                self._send({"status": "ok", "output": "stopping"})
                threading.Thread(
                    target=lambda: (time.sleep(0.3), _server.shutdown()),
                    daemon=True
                ).start()
            else:
                self._send({"status": "error", "output": f"Unknown action: {action}"})
        except Exception as e:
            self._send({"status": "error", "output": str(e)})

    def _send(self, obj):
        self.request.sendall((json.dumps(obj) + "\n").encode())

    def _handle_shell(self):
        self._send({"status": "ok", "output": "shell"})
        ch = _session.open_shell_channel()
        stop = threading.Event()

        def fwd_out():
            while not stop.is_set():
                ready, _, _ = select.select([ch], [], [], 0.5)
                if ready:
                    try:
                        data = ch.recv(4096)
                        if data:
                            self.request.sendall(data)
                    except Exception:
                        break

        t = threading.Thread(target=fwd_out, daemon=True)
        t.start()
        try:
            while not ch.exit_status_ready():
                self.request.settimeout(0.1)
                try:
                    data = self.request.recv(4096)
                    if not data:
                        break
                    ch.send(data)
                except socket.timeout:
                    continue
                except Exception:
                    break
        finally:
            stop.set()
            # Send exit to let the remote bash close cleanly before we close
            # the channel; this prevents the bastion from terminating the whole
            # session when a channel is abruptly torn down.
            try:
                ch.send("exit\n")
                time.sleep(0.3)
            except Exception:
                pass
            try:
                ch.close()
            except Exception:
                pass
            t.join(timeout=2)
            # Verify the main session channel survived; recover if needed.
            try:
                _session._recover_channel()
            except Exception:
                pass


class Daemon(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(creds, p2, profile=DEFAULT_PROFILE):
    global _session, _server
    daemon_port = daemon_port_for(creds)

    # Check if a daemon is already running on the port and stop it first
    try:
        with socket.create_connection((DAEMON_HOST, daemon_port), timeout=2) as s:
            s.sendall((json.dumps({"action": "stop"}) + "\n").encode())
        print("[*] Stopped existing daemon on port", daemon_port, flush=True)
        time.sleep(0.8)
    except OSError:
        pass  # Nothing running, good

    _session = BastionSession(
        p1=creds["p1"], p2=p2,
        host=creds.get("host"), port=creds.get("port"), user=creds.get("user")
    )
    print(f"[*] Profile: {profile}", flush=True)
    print(f"[*] Connecting to {_session.host}:{_session.port} as {_session.user} ...", flush=True)
    _session.connect()
    print(f"[OK] Session ready. Daemon on {DAEMON_HOST}:{daemon_port}", flush=True)
    stop_cmd = f"python agent.py stop" if profile == DEFAULT_PROFILE else f"python agent.py -p {profile} stop"
    print(f"[*] Keep this window open. Run \"{stop_cmd}\" to stop.\n", flush=True)
    _server = Daemon((DAEMON_HOST, daemon_port), Handler)
    try:
        _server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _session.close()
        print("\n[*] Daemon stopped.")


# ── Client helpers ─────────────────────────────────────────────────────────────

def daemon_req(req, timeout=180, profile=DEFAULT_PROFILE):
    creds = get_profile(profile)
    daemon_port = daemon_port_for(creds)
    with socket.create_connection((DAEMON_HOST, daemon_port), timeout=10) as s:
        s.sendall((json.dumps(req) + "\n").encode())
        s.settimeout(timeout)
        chunks = []
        while True:
            try:
                chunk = s.recv(65535)
            except socket.timeout:
                raise TimeoutError(
                    f"Daemon did not respond within {timeout}s. "
                    f"Partial output: {b''.join(chunks)[-200:].decode(errors='replace')}"
                )
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
        buf = b"".join(chunks)
        line = buf.split(b"\n")[0]
        return json.loads(line.decode())


def daemon_shell(profile=DEFAULT_PROFILE):
    """Interactive shell. Characters are forwarded byte-by-byte (incl. Ctrl+C).
    To disconnect from the local side without killing the remote shell, type 'exit'
    or press Ctrl+D. The remote shell session is kept alive by the daemon.
    """
    daemon_port = daemon_port_for(get_profile(profile))
    print("[*] Interactive shell via daemon.")
    print(f"[*] Profile: {profile} ({DAEMON_HOST}:{daemon_port})")
    print("[*] Ctrl+C  → sent to remote (interrupt running command)")
    print("[*] 'exit' or Ctrl+D → close this shell connection\n")
    with socket.create_connection((DAEMON_HOST, daemon_port), timeout=10) as s:
        s.sendall((json.dumps({"action": "shell"}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            buf += s.recv(4096)
        ack = json.loads(buf.split(b"\n")[0])
        if ack.get("status") != "ok":
            print(f"[!!] {ack.get('output')}")
            return

        stop = threading.Event()

        def recv_loop():
            while not stop.is_set():
                try:
                    s.settimeout(0.1)
                    data = s.recv(4096)
                    if not data:
                        stop.set()
                        break
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
                except socket.timeout:
                    continue
                except Exception:
                    break

        t = threading.Thread(target=recv_loop, daemon=True)
        t.start()

        # Read input character-by-character so special keys (Ctrl+C, arrows, etc.)
        # are forwarded to the remote instead of being intercepted by Python.
        try:
            if os.name == "nt":
                import msvcrt
                while not stop.is_set():
                    if msvcrt.kbhit():
                        ch = msvcrt.getwch()
                        # msvcrt returns special 2-byte sequences for function keys
                        if ch in ("\x00", "\xe0"):
                            msvcrt.getwch()  # discard second byte of special key
                            continue
                        s.sendall(ch.encode("utf-8", errors="replace"))
                    else:
                        time.sleep(0.02)
            else:
                import tty, termios
                fd = sys.stdin.fileno()
                old = termios.tcgetattr(fd)
                try:
                    tty.setraw(fd)
                    while not stop.is_set():
                        ch = sys.stdin.read(1)
                        if not ch:
                            break
                        s.sendall(ch.encode("utf-8", errors="replace"))
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass
        finally:
            stop.set()
            t.join(timeout=2)


def no_daemon(profile=DEFAULT_PROFILE):
    print(f"[!!] Daemon for profile '{profile}' not running. Run \"agent.py serve {profile}\" first.")
    sys.exit(1)


# ── CLI ────────────────────────────────────────────────────────────────────────

def _build_parser():
    parser = argparse.ArgumentParser(
        prog="agent.py",
        description="Daemon-based SSH agent for Qizhi (Shterm) bastion.",
        epilog=(
            "Examples:\n"
            "  python agent.py setcreds app1\n"
            "  python agent.py serve app1\n"
            "  python agent.py -p app1 run \"hostname\"\n"
            "  python agent.py -p app1 upload ./local.txt /tmp/remote.txt\n"
            "  python agent.py -p app1 download /tmp/remote.txt ./local.txt"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--profile", "-p",
        default=os.environ.get("BASTION_PROFILE", DEFAULT_PROFILE),
        metavar="NAME",
        help=f"Profile to use (env: BASTION_PROFILE, default: {DEFAULT_PROFILE})",
    )

    subs = parser.add_subparsers(dest="action", metavar="<action>")
    subs.required = True

    # ── Daemon ──
    p_serve = subs.add_parser("serve", help="Start daemon (prompts OTP, holds SSH session)")
    p_serve.add_argument("profile_pos", nargs="?", metavar="NAME",
                         help="Profile name (shorthand for --profile)")
    p_serve.add_argument("--otp", "-o", metavar="CODE",
                         help="OTP code (skip interactive prompt)")

    subs.add_parser("stop",  help="Stop running daemon for the selected profile")
    subs.add_parser("ping",  help="Check whether the daemon for the selected profile is alive")

    # ── Operations ──
    p_run = subs.add_parser("run", help="Execute a command on the remote host")
    p_run.add_argument("--timeout", "-t", type=int, default=120, metavar="N",
                       help="Seconds to wait for the command to finish (default: 120)")
    p_run.add_argument("cmd", nargs=argparse.REMAINDER,
                       help="Command to execute (quote if it contains spaces)")

    subs.add_parser("shell", help="Open an interactive shell (Ctrl+C forwarded to remote)")

    p_upload = subs.add_parser("upload", help="Upload a local file to the remote host via SFTP")
    p_upload.add_argument("local",  help="Local file path")
    p_upload.add_argument("remote", help="Remote destination path")

    p_download = subs.add_parser("download", help="Download a remote file to local via SFTP")
    p_download.add_argument("remote", help="Remote file path")
    p_download.add_argument("local",  help="Local destination path")

    p_send = subs.add_parser("send", help="Send text to a blocked interactive prompt (e.g. \"y\")")
    p_send.add_argument("text", help="Text to send (newline appended automatically)")

    subs.add_parser("cancel", help="Send Ctrl+C to interrupt a blocked command and recover shell")

    # ── Credentials ──
    p_setcreds = subs.add_parser("setcreds", help="Configure host/port/user/password for a profile")
    p_setcreds.add_argument("profile_pos", nargs="?", metavar="NAME",
                             help="Profile name (shorthand for --profile)")

    subs.add_parser("profiles", help="List all configured profiles")

    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    # --profile NAME  OR  serve/setcreds NAME (positional shorthand)
    profile = args.profile
    if getattr(args, "profile_pos", None):
        profile = args.profile_pos

    action = args.action

    if action == "setcreds":
        print(f"Configure bastion connection profile '{profile}' (press Enter to keep shown default):\n")
        try:
            existing = get_profile(profile)
        except KeyError:
            existing = {}
        host = _prompt("Bastion host/IP", default=existing.get("host", _DEFAULT_BASTION_HOST))
        port = _prompt("Bastion port",    default=str(existing.get("port", _DEFAULT_BASTION_PORT)))
        print("\nUsername format: <local_user>/<target_ip>/<target_user>")
        print(f"  e.g. {_DEFAULT_BASTION_USER}")
        user = _prompt("Bastion username", default=existing.get("user", _DEFAULT_BASTION_USER))
        daemon_port = _prompt("Local daemon port", default=str(existing.get("daemon_port", DAEMON_PORT)))
        p1 = _prompt(
            "Static password (saved; Enter keeps existing)" if existing.get("p1") else "Static password (saved)",
            secret=True,
        )
        if not p1 and existing.get("p1"):
            p1 = existing["p1"]
        if not p1:
            print("[!!] Password cannot be empty"); sys.exit(1)
        save_profile(profile, {
            "host": host, "port": int(port), "user": user,
            "daemon_port": int(daemon_port), "p1": p1,
        })
        print(f"\n[OK] Saved to {CREDS_FILE}")
        print(f"     profile={profile}  host={host}  port={port}  user={user}  daemon_port={daemon_port}")
        return

    if action == "profiles":
        profiles = list_profiles()
        if not profiles:
            print("[--] No profiles configured. Run: python agent.py setcreds")
            return
        for name, creds in sorted(profiles.items()):
            print(
                f"{name}: {creds.get('host', _DEFAULT_BASTION_HOST)}:"
                f"{creds.get('port', _DEFAULT_BASTION_PORT)} "
                f"user={creds.get('user', _DEFAULT_BASTION_USER)} "
                f"daemon_port={daemon_port_for(creds)}"
            )
        return

    if action == "serve":
        try:
            creds = get_profile(profile)
        except KeyError as e:
            print(f"[!!] {e}"); sys.exit(1)
        if not creds.get("p1"):
            print(f"[!] No credentials for profile '{profile}'. Run: python agent.py setcreds {profile}")
            p1 = getpass.getpass("Bastion 1st Password: ")
            creds["p1"] = p1
            if input("Save for next time? [y/N] ").strip().lower() == "y":
                save_profile(profile, creds)
        p2 = args.otp if args.otp else getpass.getpass("2nd Password (OTP, NOT saved): ")
        serve(creds, p2, profile=profile)
        return

    if action == "ping":
        try:
            r = daemon_req({"action": "ping"}, timeout=5, profile=profile)
            print("[OK] Daemon is running" if r["status"] == "ok" else f"[!!] {r}")
        except Exception:
            no_daemon(profile)
        return

    if action == "stop":
        try:
            daemon_req({"action": "stop"}, timeout=5, profile=profile)
            print(f"[OK] Daemon stopped for profile '{profile}'")
        except Exception:
            print(f"[--] Daemon for profile '{profile}' was not running")
        return

    if action == "shell":
        try:
            daemon_shell(profile)
        except ConnectionRefusedError:
            no_daemon(profile)
        return

    if action == "run":
        cmd_parts = args.cmd
        if not cmd_parts:
            print('[!!] No command given. Usage: python agent.py run [--timeout N] "cmd"')
            sys.exit(1)
        cmd = " ".join(cmd_parts)
        try:
            r = daemon_req({"action": "run", "cmd": cmd, "timeout": args.timeout},
                           timeout=args.timeout + 30, profile=profile)
            print(r["output"])
            if r["status"] == "timeout":
                print(f"\n[BLOCKED] Command did not finish within {args.timeout}s.", file=sys.stderr)
                print("Options:", file=sys.stderr)
                print(f"  python agent.py --profile {profile} run --timeout <N> \"{cmd}\"  -- retry with longer timeout", file=sys.stderr)
                sys.exit(2)
            sys.exit(0 if r["status"] == "ok" else 1)
        except TimeoutError as e:
            print(f"[!!] {e}", file=sys.stderr)
            sys.exit(2)
        except ConnectionRefusedError:
            no_daemon(profile)
        return

    if action == "send":
        try:
            r = daemon_req({"action": "send", "text": args.text}, timeout=15, profile=profile)
            print(r.get("output", ""))
            sys.exit(0 if r["status"] == "ok" else 1)
        except ConnectionRefusedError:
            no_daemon(profile)
        return

    if action == "cancel":
        try:
            r = daemon_req({"action": "cancel"}, timeout=15, profile=profile)
            print(r.get("output", ""))
            sys.exit(0 if r["status"] == "ok" else 1)
        except ConnectionRefusedError:
            no_daemon(profile)
        return

    if action == "upload":
        if not os.path.exists(args.local):
            print(f"[!!] File not found: {args.local}"); sys.exit(1)
        if args.remote.startswith("~/") or args.remote == "~":
            print(f"[!!] Remote path '{args.remote}' starts with '~', which is NOT expanded by SFTP.")
            print(f"     Use an absolute path instead, e.g. /home/<user>/{args.remote.lstrip('~/')}")
            sys.exit(1)
        if args.remote.endswith("/"):
            print(f"[!!] Remote path '{args.remote}' looks like a directory. Please specify a full file path.")
            sys.exit(1)
        try:
            r = daemon_req({"action": "upload", "local": args.local, "remote": args.remote},
                           timeout=600, profile=profile)
            print("[OK] Uploaded" if r["status"] == "ok" else f"[!!] Upload failed: {r.get('output')}")
        except ConnectionRefusedError:
            no_daemon(profile)
        return

    if action == "download":
        if args.remote.startswith("~/") or args.remote == "~":
            print(f"[!!] Remote path '{args.remote}' starts with '~', which is NOT expanded by SFTP.")
            print(f"     Use an absolute path instead, e.g. /home/<user>/{args.remote.lstrip('~/')}")
            sys.exit(1)
        try:
            r = daemon_req({"action": "download", "remote": args.remote, "local": args.local},
                           timeout=600, profile=profile)
            print("[OK] Downloaded" if r["status"] == "ok" else f"[!!] Download failed: {r.get('output')}")
        except ConnectionRefusedError:
            no_daemon(profile)
        return


if __name__ == "__main__":
    main()
