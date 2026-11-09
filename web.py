"""AI Chatbot - web UI.

Run:  python web.py            then open http://localhost:8000
      python web.py --port 9000

Uses only the standard library plus the Chatbot class from main.py.

Settings (environment variables, e.g. on your hosting service):
  PORT                   port to listen on; when set, the server listens on all
                         interfaces (0.0.0.0) so the host can reach it
  APP_PASSWORD           if set, visitors must enter this password to chat
  MAX_MESSAGES_PER_HOUR  messages each visitor may send per hour (default 30)
"""

import hmac
import json
import os
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import anthropic

from main import Chatbot

STATIC_DIR = Path(__file__).parent / "static"

# Language codes the web UI can send -> name given to Claude.
LANGUAGES = {"en-US": "English", "km-KH": "Khmer"}

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
MAX_MESSAGES_PER_HOUR = int(os.environ.get("MAX_MESSAGES_PER_HOUR", "30"))

# One Chatbot (conversation history) per browser session.
sessions: dict[str, Chatbot] = {}
session_locks: dict[str, threading.Lock] = {}
sessions_lock = threading.Lock()


def get_session(session_id: str) -> tuple[Chatbot, threading.Lock]:
    with sessions_lock:
        if session_id not in sessions:
            sessions[session_id] = Chatbot()
            session_locks[session_id] = threading.Lock()
        return sessions[session_id], session_locks[session_id]


# Message times per visitor IP, for the hourly limit.
recent_messages: dict[str, deque] = defaultdict(deque)
rate_lock = threading.Lock()


def allow_message(ip: str) -> bool:
    """Record a message from `ip`; False if it is over the hourly limit."""
    now = time.monotonic()
    with rate_lock:
        times = recent_messages[ip]
        while times and now - times[0] > 3600:
            times.popleft()
        if len(times) >= MAX_MESSAGES_PER_HOUR:
            return False
        times.append(now)
        return True


def password_ok(given: str) -> bool:
    if not APP_PASSWORD:
        return True
    return hmac.compare_digest(given.encode("utf-8"), APP_PASSWORD.encode("utf-8"))


def error_text(e: Exception) -> str:
    if isinstance(e, anthropic.AuthenticationError) or "api_key" in str(e):
        return "Invalid or missing API key - set ANTHROPIC_API_KEY."
    if isinstance(e, anthropic.RateLimitError):
        return "Rate limited - wait a moment and try again."
    if isinstance(e, anthropic.APIStatusError):
        return f"API error {e.status_code}: {e.message}"
    if isinstance(e, anthropic.APIConnectionError):
        return "Network error - check your internet connection."
    return f"Unexpected error: {e}"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = (STATIC_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self.send_error(400, "Invalid JSON")
            return
        session_id = str(data.get("session") or uuid.uuid4())

        if not password_ok(str(data.get("password", ""))):
            self.send_json(401, {"error": "password"})
            return

        if self.path == "/api/login":
            self.send_json(200, {"ok": True})
            return

        if self.path == "/api/reset":
            bot, lock = get_session(session_id)
            with lock:
                bot.reset()
            self.send_response(204)
            self.end_headers()
            return

        if self.path == "/api/chat":
            message = str(data.get("message", "")).strip()
            if not message:
                self.send_error(400, "Empty message")
                return
            if not allow_message(self.client_ip()):
                self.send_json(429, {"error": "limit"})
                return
            language = LANGUAGES.get(str(data.get("lang", "")))
            self.stream_reply(session_id, message, language)
            return

        self.send_error(404)

    def send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def client_ip(self) -> str:
        # Behind a host's proxy (Render, etc.) the real visitor IP is the first
        # entry of X-Forwarded-For.
        forwarded = self.headers.get("X-Forwarded-For", "")
        return forwarded.split(",")[0].strip() or self.client_address[0]

    def stream_reply(self, session_id: str, message: str, language: str | None = None):
        """Stream the reply as plain text; errors are sent as a final line starting with \\x00."""
        bot, lock = get_session(session_id)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def write(text: str):
            self.wfile.write(text.encode("utf-8"))
            self.wfile.flush()

        with lock:
            try:
                streamed = []

                def on_text(t):
                    streamed.append(t)
                    write(t)

                reply = bot.ask(message, on_text=on_text, language=language)
                if not streamed and reply:  # e.g. the refusal message
                    write(reply)
            except (BrokenPipeError, ConnectionResetError):
                pass  # browser went away
            except Exception as e:
                try:
                    write("\x00" + error_text(e))
                except (BrokenPipeError, ConnectionResetError):
                    pass

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet


def main():
    # Hosting services set PORT and need us to listen on all interfaces;
    # locally we stay on 127.0.0.1 so only this computer can connect.
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"🤖 AI Chatbot web UI running at http://localhost:{port}  (Ctrl+C to stop)", flush=True)
    if APP_PASSWORD:
        print("🔒 Password required (APP_PASSWORD is set)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye!")


if __name__ == "__main__":
    main()
