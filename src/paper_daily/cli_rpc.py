"""Short-lived official CLI protocol calls; no model sessions or tool execution."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from contextlib import suppress


class Client:
    def __init__(self, argv, *, env, cwd=None):
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=cwd,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.messages = queue.Queue()
        self.serial = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.proc.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if isinstance(message, dict):
                    self.messages.put(message)
        finally:
            self.messages.put(None)

    def send(self, message):
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def request(self, method, params, *, timeout=30):
        self.serial += 1
        serial = self.serial
        self.send({"jsonrpc": "2.0", "id": serial, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            try:
                message = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise TimeoutError("CLI response timed out") from exc
            if message is None:
                raise ValueError("CLI closed before replying")
            if "method" in message and "id" in message:
                # This client only authenticates/discovers models. Never grant tool access.
                self.send(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {"code": -32601, "message": "Unsupported request"},
                    }
                )
                continue
            if message.get("id") != serial:
                continue
            if "error" in message:
                raise ValueError("Official CLI rejected the request")
            return message.get("result") or {}

    def __enter__(self):
        return self

    def control(self, request, *, timeout=30):
        """Claude SDK control protocol, with no user message/model turn."""
        self.serial += 1
        serial = str(self.serial)
        self.send({"type": "control_request", "request_id": serial, "request": request})
        deadline = time.monotonic() + timeout
        while True:
            try:
                message = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise TimeoutError("CLI control response timed out") from exc
            if message is None:
                raise ValueError("CLI closed before replying")
            if message.get("type") == "control_request":
                self.send({"type": "control_response", "response": {
                    "subtype": "error", "request_id": message.get("request_id"),
                    "error": "This read-only client does not execute tools or hooks",
                }})
                continue
            response = message.get("response", {})
            if not isinstance(response, dict):
                continue
            if message.get("type") != "control_response" or response.get("request_id") != serial:
                continue
            if response.get("subtype") != "success":
                raise ValueError("CLI does not support this control request")
            return response.get("response") or {}

    def __exit__(self, *_args):
        # EOF lets official launchers stop their child process and release caches.
        # Terminating only the launcher can leave its native server alive on Windows.
        with suppress(OSError):
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        self.reader.join(timeout=2)
        self.proc.stdout.close()
