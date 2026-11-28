"""Local chat page. Binds to 127.0.0.1 unless ASSISTANT_HOST says otherwise."""

import argparse
import base64
import json
import os
import shutil
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .agent import opening_text, run_turn
from .config import load_settings
from .provider import ProviderError

PAGE = Path(__file__).resolve().parent / "chat.html"
MAX_BODY = 1_000_000
MAX_MESSAGES = 40
MAX_CHARS = 8000


def check_basic_auth(auth_header, username, password):
    """Check HTTP Basic Auth credentials. Returns True if authorized."""
    if not username or not password:
        return True
    if not auth_header or not auth_header.startswith("Basic "):
        return False
    try:
        encoded = auth_header[6:]
        decoded = base64.b64decode(encoded).decode("utf-8")
        provided_user, _, provided_pass = decoded.partition(":")
        return provided_user == username and provided_pass == password
    except Exception:
        return False


def seed_model_folder(target_path):
    """Copy the example model to target_path if it's empty."""
    target = Path(target_path)
    if target.exists() and any(target.iterdir()):
        return
    target.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[2]
    example = repo_root / "methodology" / "example"
    if not example.is_dir():
        return
    for item in example.iterdir():
        if item.is_file():
            shutil.copy2(item, target / item.name)
        elif item.is_dir():
            shutil.copytree(item, target / item.name, dirs_exist_ok=True)


def safe_explorer_url(url):
    parsed = urlparse(url or "")
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return url
    return "http://127.0.0.1:8199/"


def sanitize_messages(raw):
    if not isinstance(raw, list):
        raise ValueError("messages must be a list")
    if len(raw) > MAX_MESSAGES:
        raise ValueError("too many messages")
    clean = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each message must be an object")
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant"):
            continue
        if not isinstance(content, str):
            raise ValueError("message content must be a string")
        if len(content) > MAX_CHARS:
            raise ValueError("a message is too long")
        clean.append({"role": role, "content": content})
    if not clean or clean[-1]["role"] != "user":
        raise ValueError("the last message must be from the user")
    return clean


def session_payload(settings):
    folder = settings.model_folder
    if folder and folder.is_dir():
        greeting = opening_text(folder)
        shown = str(folder)
    else:
        greeting = (
            "Set MODEL_FOLDER or SE_DATA_DIR to the model directory, then restart the assistant."
        )
        shown = ""
    
    problem = settings.configuration_error()
    if not settings.base_url or not settings.model:
        problem = "AI assistant disabled. Set ASSISTANT_BASE_URL and ASSISTANT_MODEL to enable chat features."
    
    return {
        "messages": [{"role": "assistant", "content": greeting}],
        "explorerUrl": safe_explorer_url(settings.explorer_url),
        "modelFolder": shown,
        "configured": problem is None,
        "configMessage": problem or "",
    }


def chat_payload(body, settings, complete_fn=None):
    if not isinstance(body, dict):
        return {"notes": [], "error": "request body must be a JSON object"}
    problem = settings.configuration_error()
    if problem:
        return {"notes": [], "error": problem}
    try:
        messages = sanitize_messages(body.get("messages") if isinstance(body, dict) else None)
    except ValueError as exc:
        return {"notes": [], "error": str(exc)}
    try:
        updated, notes = run_turn(messages, settings, complete_fn)
    except ProviderError as exc:
        return {"messages": messages, "notes": [], "error": str(exc)}
    except Exception as exc:
        # A missing methodology file or a bug must come back as JSON.
        # An uncaught exception drops the socket, and the panel shows
        # "Failed to fetch" with the thinking indicator left on screen.
        return {
            "messages": messages,
            "notes": [],
            "error": f"The assistant failed: {exc}",
        }
    return {"messages": updated, "notes": notes, "error": ""}


def make_handler(settings, complete_fn=None):
    class Handler(BaseHTTPRequestHandler):
        def _check_auth(self):
            """Check Basic Auth if configured. Returns True if authorized."""
            if not settings.auth_user or not settings.auth_password:
                return True
            auth_header = self.headers.get("Authorization", "")
            if check_basic_auth(auth_header, settings.auth_user, settings.auth_password):
                return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="SE Assistant"')
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = json.dumps({"error": "Authentication required"}).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return False

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/healthz":
                self._json(200, {"status": "ok"})
                return
            if not self._check_auth():
                return
            if path == "/api/session":
                self._json(200, session_payload(settings))
                return
            if path in ("/", "/chat.html"):
                data = PAGE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._check_auth():
                return
            path = urlparse(self.path).path
            if path != "/api/chat":
                self._json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._json(413, {"error": "request is too large"})
                return
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeError, json.JSONDecodeError):
                self._json(400, {"error": "request body must be JSON"})
                return
            payload = chat_payload(body, settings, complete_fn)
            status = 200 if not payload.get("error") else 400
            if payload.get("error") and settings.configuration_error():
                status = 503
            self._json(status, payload)

        def _json(self, status, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            sys.stderr.write("%s %s\n" % (self.command, urlparse(self.path).path))

    return Handler


def serve(settings, complete_fn=None):
    if settings.model_folder:
        seed_model_folder(settings.model_folder)
    
    server = ThreadingHTTPServer((settings.host, settings.port), make_handler(settings, complete_fn))
    url = f"http://{settings.host}:{settings.port}/"
    print(f"SE assistant at {url}")
    print(f"Model folder: {settings.model_folder}")
    print(f"Diagram: {safe_explorer_url(settings.explorer_url)}")
    if settings.base_url and settings.model:
        print(f"Provider: {settings.base_url}{settings.chat_path} model {settings.model}")
    else:
        print("AI assistant disabled: set ASSISTANT_BASE_URL and ASSISTANT_MODEL to enable")
    print("API key: " + ("set" if settings.api_key else "not set"))
    if settings.auth_user and settings.auth_password:
        print("HTTP Basic Auth: enabled")
    problem = settings.configuration_error()
    if problem:
        print(f"Warning: {problem}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


def say(text, settings):
    problem = settings.configuration_error()
    if problem:
        print(problem, file=sys.stderr)
        return 1
    messages = [
        {"role": "assistant", "content": opening_text(settings.model_folder)},
        {"role": "user", "content": text},
    ]
    try:
        updated, notes = run_turn(messages, settings)
    except ProviderError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for note in notes:
        print(note)
    print(updated[-1]["content"])
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local SE assistant chat.")
    parser.add_argument("command", nargs="?", default="serve", choices=("serve", "say"))
    parser.add_argument("text", nargs="?", default="")
    parser.add_argument("--model-folder", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--explorer-url", default=None)
    args = parser.parse_args(argv)
    settings = load_settings(overrides={
        "model_folder": args.model_folder,
        "port": args.port,
        "explorer_url": args.explorer_url,
    })
    if args.command == "say":
        if not args.text:
            parser.error("say requires the team's message")
        return say(args.text, settings)
    serve(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
