#!/usr/bin/env python3
"""
bastion_manager.py - Bastion daemon lifecycle manager for UT Workflow

Responsibilities:
  - ensure_connected(): verify daemon is reachable, request OTP if not
  - Heartbeat loop: ping daemon every 15s, notify on disconnect
  - OTP protocol: generate request_id, send Feishu card, accept OTP reply
  - Daemon restart: stop old daemon, start new one with OTP
  - State tracking: update workflow_state.json bastion section

Design: tasks/ut/docs/discussions/2026-06-18-hermes-runner-bastion-otp-design.md ( 6,  8)

Usage:
    mgr = BastionManager(
        workspace="D:/workspace/apmm",
        profile="t_h20",
        feishu_config_path="D:/workspace/apmm/.agents/feishu_config.json",
        workflow_state_path="D:/workspace/apmm/runs/ut-xxx/workflow_state.json",
    )
    mgr.ensure_connected(reason="startup", stage="select_batch", batch_id=None)
    mgr.start_heartbeat()
    # ... run workflow ...
    mgr.stop_heartbeat()
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from feishu_api import FeishuAPI

# ── Constants ──────────────────────────────────────────────────────────────────

OTP_PATTERN = re.compile(
    r"OTP\s+(otp-\d{8}-[a-z0-9]+)\s+([0-9]{6})", re.IGNORECASE
)
OTP_TIMEOUT_DEFAULT = 300
HEARTBEAT_INTERVAL_DEFAULT = 15

BASTION_STATUS_CONNECTED = "connected"
BASTION_STATUS_DISCONNECTED = "disconnected"
BASTION_STATUS_WAITING_FOR_OTP = "waiting_for_otp"
BASTION_STATUS_RECONNECTING = "reconnecting"
BASTION_STATUS_FAILED = "failed"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(args, cwd, timeout=30):
    """Run a subprocess, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s"


_OTP_SCHEDULE = {1: 5, 2: 15, 3: 30, 4: 60}


def otp_resend_delay(attempt: int) -> int:
    """Delay (minutes) before the given OTP resend attempt; caps at 60."""
    return _OTP_SCHEDULE.get(attempt, 60)


def otp_should_at_user(attempt: int) -> bool:
    """Whether to @-mention the user; starts from the 3rd attempt."""
    return attempt >= 3


# ── BastionManager ─────────────────────────────────────────────────────────────

class BastionManager:
    """Manages a single bastion daemon profile."""

    def __init__(
        self,
        workspace,
        profile="t_h20",
        feishu_config_path=None,
        workflow_state_path=None,
    ):
        self.workspace = Path(workspace)
        self.profile = profile
        self.feishu_config_path = feishu_config_path
        self.workflow_state_path = (
            Path(workflow_state_path) if workflow_state_path else None
        )

        # Internal state
        self._active_otp_request = None  # dict: {request_id, expires_at}
        self._heartbeat_thread = None
        self._heartbeat_stop = threading.Event()
        self._heartbeat_interval = HEARTBEAT_INTERVAL_DEFAULT
        self._on_disconnect_callback = None
        self._lock = threading.Lock()

        # Feishu API (lazy init)
        self._feishu_api = None

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def feishu(self):
        if self._feishu_api is None and self.feishu_config_path:
            try:
                self._feishu_api = FeishuAPI(str(self.feishu_config_path))
            except Exception as e:
                print(f"[bastion_manager] WARN: Feishu init failed: {e}")
                self._feishu_api = None
        return self._feishu_api

    # ── Daemon operations ──────────────────────────────────────────────────

    def ping(self):
        """Check if daemon is reachable. Returns True/False."""
        rc, stdout, _ = _run(
            ["python", "tools/agent.py", "-p", self.profile, "ping"],
            self.workspace,
            timeout=10,
        )
        return rc == 0 and "[OK]" in stdout

    def stop_daemon(self):
        """Stop the running daemon for this profile."""
        try:
            _run(
                ["python", "tools/agent.py", "-p", self.profile, "stop"],
                self.workspace,
                timeout=20,
            )
        except Exception:
            pass

    def start_daemon(self, otp):
        """Start daemon in background with the given OTP."""
        kwargs = {
            "cwd": str(self.workspace),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            kwargs["preexec_fn"] = os.setpgrp

        subprocess.Popen(
            ["python", "tools/agent.py", "serve", self.profile, "--otp", otp],
            **kwargs,
        )

    def restart_daemon(self, otp):
        """Stop existing daemon and start a new one with OTP."""
        self.stop_daemon()
        time.sleep(0.5)
        self.start_daemon(otp)

    # ── OTP protocol ───────────────────────────────────────────────────────

    def _generate_request_id(self):
        today = datetime.now().strftime("%Y%m%d")
        short_id = uuid.uuid4().hex[:6]
        return f"otp-{today}-{short_id}"

    def request_otp(self, reason, stage=None, batch_id=None, timeout=None):
        """Send OTP request via Feishu, poll for reply. Returns OTP code or None."""
        if timeout is None:
            timeout = OTP_TIMEOUT_DEFAULT

        request_id = self._generate_request_id()
        expires_at = time.time() + timeout

        with self._lock:
            self._active_otp_request = {
                "request_id": request_id,
                "profile": self.profile,
                "stage": stage,
                "batch_id": batch_id,
                "expires_at": expires_at,
            }

        # Send Feishu card
        self._send_otp_card(request_id, reason, stage, batch_id, timeout)

        # Update workflow state
        self._update_bastion_state(
            BASTION_STATUS_WAITING_FOR_OTP,
            otp_request_id=request_id,
        )

        # Poll for OTP
        since_ms = int(time.time() * 1000)
        deadline = time.time() + timeout
        otp = None
        while time.time() < deadline:
            otp = self._find_otp_reply(request_id, since_ms)
            if otp:
                break
            time.sleep(10)

        with self._lock:
            self._active_otp_request = None

        if not otp:
            print(f"[bastion_manager] OTP request {request_id} timed out")
            self._update_bastion_state(
                BASTION_STATUS_FAILED,
                last_disconnect_reason="otp_timeout",
            )
            return None

        print(f"[bastion_manager] OTP received for {request_id}")
        return otp

    def _send_otp_card(self, request_id, reason, stage, batch_id, timeout):
        """Send a Feishu card requesting OTP."""
        if not self.feishu:
            print(f"[bastion_manager] No Feishu configured, cannot request OTP")
            return

        lines = [
            f"**Profile**: `{self.profile}`",
            f"**当前阶段**: {stage or 'N/A'}",
            f"**当前批次**: {batch_id or 'N/A'}",
            f"**请求ID**: `{request_id}`",
            f"**原因**: {reason}",
            "",
            f"请回复：`OTP {request_id} XXXXXX`",
            f"（6 位数字验证码，{timeout}s 内有效）",
            "",
            "注意：OTP 不写入日志，使用后立即清除。",
        ]

        self.feishu.send_card({
            "header": {
                "title": "UT Workflow 需要 Bastion OTP",
                "template": "red",
            },
            "content": "\n".join(lines),
        })

    def _find_otp_reply(self, request_id, since_ms):
        """Poll Feishu for an OTP reply matching the given request_id."""
        if not self.feishu:
            return None

        try:
            messages = self.feishu.get_group_messages(limit=30)
        except Exception as e:
            print(f"[bastion_manager] Failed to poll messages: {e}")
            return None

        for msg in messages:
            try:
                create_time = int(msg.get("create_time", 0))
            except (ValueError, TypeError):
                create_time = 0
            if create_time < since_ms:
                continue

            match = OTP_PATTERN.search(msg.get("content", ""))
            if match and match.group(1) == request_id:
                return match.group(2)

        return None

    # ── ensure_connected ───────────────────────────────────────────────────

    def ensure_connected(self, reason="startup", stage=None, batch_id=None):
        """Ensure the daemon is connected. Request OTP if not.

        Returns True if connected (or successfully reconnected), False if failed.
        """
        if self.ping():
            self._update_bastion_state(BASTION_STATUS_CONNECTED)
            return True

        print(f"[bastion_manager] Daemon not reachable, requesting OTP...")
        otp = self.request_otp(
            reason=reason, stage=stage, batch_id=batch_id
        )
        if not otp:
            print(f"[bastion_manager] Failed to obtain OTP")
            return False

        self._update_bastion_state(BASTION_STATUS_RECONNECTING)

        self.restart_daemon(otp)

        # Wait for daemon to become healthy
        for _ in range(30):
            time.sleep(2)
            if self.ping():
                print(f"[bastion_manager] Daemon restarted and healthy")
                self._update_bastion_state(BASTION_STATUS_CONNECTED)
                return True

        print(f"[bastion_manager] Daemon restart did not become healthy")
        self._update_bastion_state(
            BASTION_STATUS_FAILED,
            last_disconnect_reason="restart_failed",
        )
        return False

    # ── Heartbeat ──────────────────────────────────────────────────────────

    def start_heartbeat(self, on_disconnect=None):
        """Start a background heartbeat thread.

        Args:
            on_disconnect: Optional callback(stage, batch_id) called on disconnect.
        """
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        self._on_disconnect_callback = on_disconnect
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self._heartbeat_thread.start()
        print(
            f"[bastion_manager] Heartbeat started (interval={self._heartbeat_interval}s)"
        )

    def stop_heartbeat(self):
        """Stop the heartbeat thread."""
        self._heartbeat_stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)
        print("[bastion_manager] Heartbeat stopped")

    def _heartbeat_loop(self):
        fail_count = 0
        while not self._heartbeat_stop.is_set():
            self._heartbeat_stop.wait(self._heartbeat_interval)
            if self._heartbeat_stop.is_set():
                break

            if self.ping():
                if fail_count > 0:
                    print(
                        f"[bastion_manager] Heartbeat recovered after {fail_count} failures"
                    )
                fail_count = 0
                self._update_bastion_state(BASTION_STATUS_CONNECTED)
            else:
                fail_count += 1
                print(
                    f"[bastion_manager] Heartbeat failed ({fail_count})"
                )
                self._update_bastion_state(
                    BASTION_STATUS_DISCONNECTED,
                    last_disconnect_reason="daemon_ping_failed",
                )
                if fail_count >= 2 and self._on_disconnect_callback:
                    # Only fire callback after 2 consecutive failures to avoid
                    # transient noise
                    try:
                        self._on_disconnect_callback()
                    except Exception as e:
                        print(f"[bastion_manager] Disconnect callback error: {e}")

    # ── Workflow state ─────────────────────────────────────────────────────

    def mark_disconnected(self, reason="unknown"):
        """Record that the bastion is disconnected.

        Used by the executor (and other callers) when a remote call surfaces a
        connection failure. Sets bastion.status="disconnected" in the workflow
        state. Does NOT mutate manifest or per-test status.
        """
        self._update_bastion_state(
            BASTION_STATUS_DISCONNECTED,
            last_disconnect_reason=reason,
        )

    def mark_connected(self):
        """Record that the bastion is connected (e.g. after a successful ping
        or reconnect). Sets bastion.status="connected"."""
        self._update_bastion_state(BASTION_STATUS_CONNECTED)

    def _update_bastion_state(self, status, **extra):
        """Update the bastion section of workflow_state.json."""
        if not self.workflow_state_path:
            return
        if not self.workflow_state_path.exists():
            return

        try:
            with self._lock:
                state = json.loads(
                    self.workflow_state_path.read_text(encoding="utf-8")
                )
        except Exception:
            return

        bastion = state.get("bastion", {})
        bastion["status"] = status
        bastion["profile"] = self.profile
        bastion["last_heartbeat_at"] = datetime.now(timezone.utc).isoformat()

        for key, value in extra.items():
            if value is not None:
                bastion[key] = value
            elif key in bastion:
                del bastion[key]

        # Clear otp_request_id when not waiting
        if status != BASTION_STATUS_WAITING_FOR_OTP:
            bastion.pop("otp_request_id", None)

        state["bastion"] = bastion
        state["last_update"] = datetime.now(timezone.utc).isoformat()

        try:
            self.workflow_state_path.write_text(
                json.dumps(state, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"[bastion_manager] Failed to write workflow state: {e}")

    def graceful_shutdown(self, stop_daemon=False):
        """Clean shutdown: stop heartbeat, clear OTP, update state.

        Called when agent.py exits, daemon terminates, or workflow stops.
        Ensures workflow_state.json reflects the final state.

        Args:
            stop_daemon: If True, also stop the daemon process (default: False)
        """
        # Stop heartbeat thread
        self.stop_heartbeat()

        # Clear active OTP request
        with self._lock:
            self._active_otp_request = None

        # Update workflow state
        self.mark_disconnected(reason="graceful_shutdown")

        # Optionally stop daemon
        if stop_daemon:
            self.stop_daemon()

    def stop_heartbeat(self):
        """Stop the heartbeat thread and wait for it to finish."""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_stop.set()
            self._heartbeat_thread.join(timeout=5)
            self._heartbeat_thread = None


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Bastion Manager - daemon lifecycle and OTP handler"
    )
    parser.add_argument(
        "--profile", "-p", default="t_h20", help="Bastion profile name"
    )
    parser.add_argument(
        "--workspace", default="D:/workspace/apmm", help="Project workspace path"
    )
    parser.add_argument(
        "--feishu-config",
        default=None,
        help="Feishu config JSON path (for OTP requests)",
    )
    parser.add_argument(
        "--workflow-state",
        default=None,
        help="workflow_state.json path (for status updates)",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("ping", help="Check daemon connectivity")

    p_ensure = sub.add_parser("ensure", help="Ensure daemon is connected")
    p_ensure.add_argument("--reason", default="cli")
    p_ensure.add_argument("--stage", default=None)
    p_ensure.add_argument("--batch-id", default=None)

    p_otp = sub.add_parser("request-otp", help="Request OTP via Feishu")
    p_otp.add_argument("--reason", required=True)
    p_otp.add_argument("--stage", default=None)
    p_otp.add_argument("--batch-id", default=None)
    p_otp.add_argument("--timeout", type=int, default=300)

    p_restart = sub.add_parser("restart", help="Restart daemon with OTP")
    p_restart.add_argument("--otp", required=True)

    args = parser.parse_args()

    mgr = BastionManager(
        workspace=args.workspace,
        profile=args.profile,
        feishu_config_path=args.feishu_config,
        workflow_state_path=args.workflow_state,
    )

    if args.command == "ping":
        ok = mgr.ping()
        print("[OK] Daemon reachable" if ok else "[!!] Daemon not reachable")
        sys.exit(0 if ok else 1)

    elif args.command == "ensure":
        ok = mgr.ensure_connected(
            reason=args.reason, stage=args.stage, batch_id=args.batch_id
        )
        sys.exit(0 if ok else 1)

    elif args.command == "request-otp":
        otp = mgr.request_otp(
            reason=args.reason,
            stage=args.stage,
            batch_id=args.batch_id,
            timeout=args.timeout,
        )
        if otp:
            print(f"[OK] OTP: {otp}")
            sys.exit(0)
        else:
            print("[!!] OTP request timed out")
            sys.exit(1)

    elif args.command == "restart":
        mgr.restart_daemon(args.otp)
        for _ in range(30):
            time.sleep(2)
            if mgr.ping():
                print("[OK] Daemon restarted and healthy")
                sys.exit(0)
        print("[!!] Daemon restart did not become healthy")
        sys.exit(1)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
