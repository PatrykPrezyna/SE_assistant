"""Hosted (cloud) mode: serve a model folder from a GitHub repo to a team.

The local tool reads and writes files in a folder on your machine. Hosted,
that folder lives in a git checkout inside the container, and the git repo
stays the single source of truth:

- reads pull the checkout first (throttled), so pushes from teammates' IDEs
  show up on refresh;
- every View/layout save is committed — authored by the signed-in user —
  and pushed back to the branch;
- everyone must sign in with GitHub, and only collaborators on the repo (or
  an explicit ALLOWED_USERS list) get in.

Configured entirely by environment variables (see cloud_main / FEATURES.md),
started with `system-explorer-cloud`. Stdlib only, plus the `git` binary.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from .app import make_handler
from .projects import ProjectLibrary, project_cookie_header
from .version import __version__

# Assistant imports are done on-demand to avoid circular dependencies

SESSION_COOKIE = "sx_session"
STATE_COOKIE = "sx_oauth_state"
SESSION_SECONDS = 7 * 24 * 3600
BOT_NAME = "System Explorer"
BOT_EMAIL = "system-explorer@users.noreply.github.com"


class CloudContext:
    """What make_handler needs to know when hosted."""

    def __init__(self, sync, auth, repo_root: Path):
        self.sync = sync          # GitSync
        self.auth = auth          # GitHubAuth, or None for anonymous access
        self.repo_root = repo_root


# ----------------------------------------------------------------------
# Git checkout <-> remote
# ----------------------------------------------------------------------


class GitSync:
    """A git checkout kept in step with one branch of a remote.

    The token never touches disk: it rides on each command as an
    Authorization header instead of being baked into the remote URL.
    Concurrent edits are not merged cleverly — pulls rebase, and a push
    rejected because a teammate pushed first is retried once after a pull.
    """

    def __init__(self, remote, repo_dir: Path, branch="main", token=None,
                 pull_interval=30.0, async_push=True):
        self.remote = remote
        self.repo_dir = Path(repo_dir)
        self.branch = branch
        self.token = token
        self.pull_interval = pull_interval
        self.async_push = async_push
        self._lock = threading.RLock()  # serializes every git command
        self._last_pull = 0.0
        self._push_pending = False
        self._push_lock = threading.Lock()

    def _git(self, *args, check=True):
        cmd = ["git"]
        if self.token:
            basic = base64.b64encode(
                f"x-access-token:{self.token}".encode()).decode()
            cmd += ["-c", f"http.extraHeader=Authorization: Basic {basic}"]
        cmd += ["-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}"]
        cmd += list(args)
        res = subprocess.run(cmd, cwd=self.repo_dir if self.repo_dir.exists()
                             else None, capture_output=True, text=True)
        if check and res.returncode != 0:
            # stderr never contains the token: it isn't in the URL
            raise RuntimeError(f"git {args[0]} failed: {res.stderr.strip()}")
        return res

    def clone_or_update(self):
        with self._lock:
            if (self.repo_dir / ".git").is_dir():
                self.pull(force=True)
                return
            self.repo_dir.parent.mkdir(parents=True, exist_ok=True)
            self._git("clone", "--branch", self.branch, "--single-branch",
                      self.remote, str(self.repo_dir))
            self._last_pull = time.monotonic()

    def pull(self, force=False):
        """Fetch teammates' commits; at most once per pull_interval."""
        with self._lock:
            now = time.monotonic()
            if not force and now - self._last_pull < self.pull_interval:
                return
            self._last_pull = now
            res = self._git("pull", "--rebase", "--autostash", "-q",
                            "origin", self.branch, check=False)
            if res.returncode != 0:
                self._git("rebase", "--abort", check=False)
                print(f"warning: git pull failed: {res.stderr.strip()}",
                      file=sys.stderr)

    def commit_and_push(self, paths, message, user=None):
        """Commit `paths` (written or deleted) as `user`, then push."""
        with self._lock:
            rel = [str(Path(p).resolve().relative_to(self.repo_dir.resolve()))
                   for p in paths]
            self._git("add", "-A", "--", *rel)
            staged = self._git("diff", "--cached", "--quiet", check=False)
            if staged.returncode == 0:
                return  # saved content identical to what's committed
            args = ["commit", "-q", "-m", message]
            if user:
                args += ["--author", f"{user.get('name') or user['login']} "
                                     f"<{_noreply_email(user)}>"]
            self._git(*args)
        if self.async_push:
            self._schedule_push()
        else:
            self.push()

    def _schedule_push(self):
        # a burst of saves (switching Views auto-saves) becomes one push
        with self._push_lock:
            if self._push_pending:
                return
            self._push_pending = True
        threading.Timer(1.0, self._push_background).start()

    def _push_background(self):
        with self._push_lock:
            self._push_pending = False
        try:
            self.push()
        except RuntimeError as exc:
            print(f"warning: {exc}", file=sys.stderr)

    def push(self):
        with self._lock:
            res = self._git("push", "-q", "origin", f"HEAD:{self.branch}",
                            check=False)
            if res.returncode != 0:
                # most likely a teammate pushed first: rebase onto it, retry
                self.pull(force=True)
                self._git("push", "-q", "origin", f"HEAD:{self.branch}")


def _noreply_email(user):
    # GitHub attributes commits to the account via its noreply address
    if user.get("id"):
        return f"{user['id']}+{user['login']}@users.noreply.github.com"
    return f"{user['login']}@users.noreply.github.com"


# ----------------------------------------------------------------------
# Sign-in with GitHub
# ----------------------------------------------------------------------


class GitHubAuth:
    """GitHub OAuth sign-in plus a signed, stateless session cookie.

    Who may sign in: the ALLOWED_USERS list when given, otherwise anyone
    GitHub reports as a collaborator on `repo` (checked with the server's
    token at sign-in time). The network calls are separate methods so tests
    can stub them.
    """

    def __init__(self, client_id, client_secret, session_secret, public_url,
                 repo, token=None, allowed_users=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.key = session_secret.encode("utf-8")
        self.public_url = public_url.rstrip("/")
        self.secure = self.public_url.startswith("https://")
        self.repo = repo
        self.token = token
        self.allowed = {u.strip().lower() for u in (allowed_users or [])
                        if u.strip()}
        # Set by cloud_main: called with the GitHub user after a successful
        # sign-in. Returns extra Set-Cookie headers (the new project).
        self.on_login = None

    # -- session cookie -------------------------------------------------

    def sign(self, payload: dict) -> str:
        body = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()).decode()
        mac = hmac.new(self.key, body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{mac}"

    def verify(self, value: str):
        body, _, mac = (value or "").rpartition(".")
        good = hmac.new(self.key, body.encode(), hashlib.sha256).hexdigest()
        if not body or not hmac.compare_digest(mac.encode(), good.encode()):
            return None
        try:
            payload = json.loads(base64.urlsafe_b64decode(body.encode()))
        except ValueError:
            return None
        if payload.get("exp", 0) < time.time():
            return None
        return payload

    def make_session(self, user) -> str:
        return self.sign({"login": user["login"], "name": user.get("name"),
                          "id": user.get("id"),
                          "exp": int(time.time()) + SESSION_SECONDS})

    def session_user(self, cookie_header):
        cookie = _read_cookie(cookie_header, SESSION_COOKIE)
        return self.verify(cookie) if cookie else None

    def _cookie(self, name, value, max_age):
        attrs = f"{name}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"
        return attrs + ("; Secure" if self.secure else "")

    # -- GitHub calls (stubbed in tests) ---------------------------------

    def exchange_code(self, code):
        data = _http_json(
            "https://github.com/login/oauth/access_token",
            data={"client_id": self.client_id,
                  "client_secret": self.client_secret, "code": code,
                  "redirect_uri": self.public_url + "/auth/callback"})
        if "access_token" not in data:
            raise PermissionError(data.get("error_description", "no token"))
        return data["access_token"]

    def fetch_user(self, access_token):
        return _http_json("https://api.github.com/user", token=access_token)

    def is_allowed(self, login):
        if self.allowed:
            return login.lower() in self.allowed
        url = f"https://api.github.com/repos/{self.repo}/collaborators/{login}"
        try:
            _http_json(url, token=self.token)
            return True  # 204: is a collaborator
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            raise

    # -- /auth/* routes --------------------------------------------------

    def handle(self, h, path):
        if path == "/auth/login":
            state = secrets.token_urlsafe(16)
            query = urlencode({"client_id": self.client_id,
                               "redirect_uri": self.public_url + "/auth/callback",
                               "state": state, "allow_signup": "false"})
            h.send_response(302)
            h.send_header("Location",
                          "https://github.com/login/oauth/authorize?" + query)
            h.send_header("Set-Cookie", self._cookie(STATE_COOKIE, state, 600))
            h.end_headers()
        elif path == "/auth/callback":
            self._callback(h)
        elif path == "/auth/logout":
            h.send_response(302)
            h.send_header("Location", "/auth/signed-out")
            h.send_header("Set-Cookie", self._cookie(SESSION_COOKIE, "", 0))
            h.end_headers()
        elif path == "/auth/signed-out":
            _page(h, 200, "Signed out",
                  '<p>You are signed out. <a href="/auth/login">Sign in again</a></p>')
        elif path == "/auth/me":
            user = self.session_user(h.headers.get("Cookie"))
            if user is None:
                h.send_error(401, "sign in required")
            else:
                h._send(json.dumps({"login": user["login"],
                                    "name": user.get("name")}))
        else:
            h.send_error(404)

    def _callback(self, h):
        qs = parse_qs(urlsplit(h.path).query)
        state = qs.get("state", [""])[0]
        expected = _read_cookie(h.headers.get("Cookie"), STATE_COOKIE)
        if not state or not expected or not hmac.compare_digest(
                state.encode(), expected.encode()):
            _page(h, 400, "Sign-in failed",
                  '<p>The sign-in link expired. <a href="/auth/login">Try again</a></p>')
            return
        try:
            user = self.fetch_user(self.exchange_code(qs.get("code", [""])[0]))
            allowed = self.is_allowed(user["login"])
        except (PermissionError, urllib.error.URLError, KeyError) as exc:
            print(f"warning: sign-in failed: {exc}", file=sys.stderr)
            _page(h, 502, "Sign-in failed",
                  '<p>GitHub sign-in failed. <a href="/auth/login">Try again</a></p>')
            return
        if not allowed:
            _page(h, 403, "No access",
                  f"<p>GitHub user <b>{_esc(user['login'])}</b> is not a "
                  f"collaborator on {_esc(self.repo)}. Ask the repo owner "
                  f"to add you.</p>")
            return
        extra_cookies = []
        if self.on_login is not None:
            try:
                extra_cookies = list(self.on_login(user) or [])
            except Exception as exc:
                print(f"warning: could not open a project: {exc}",
                      file=sys.stderr)
                _page(h, 502, "Sign-in failed",
                      "<p>A new project could not be created. "
                      "<a href=\"/auth/login\">Try again</a></p>")
                return
        h.send_response(302)
        h.send_header("Location", "/")
        h.send_header("Set-Cookie", self._cookie(
            SESSION_COOKIE, self.make_session(user), SESSION_SECONDS))
        h.send_header("Set-Cookie", self._cookie(STATE_COOKIE, "", 0))
        for cookie in extra_cookies:
            h.send_header("Set-Cookie", cookie)
        h.end_headers()


def _read_cookie(header, name):
    if not header:
        return None
    jar = SimpleCookie()
    try:
        jar.load(header)
    except Exception:
        return None
    return jar[name].value if name in jar else None


def _http_json(url, data=None, token=None):
    headers = {"Accept": "application/json",
               "User-Agent": f"system-explorer/{__version__}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _page(h, status, title, body_html):
    data = (f"<!doctype html><meta charset=utf-8><title>{title}</title>"
            f"<body style='font-family:sans-serif;margin:3em'>"
            f"<h2>{title}</h2>{body_html}</body>").encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    h.wfile.write(data)


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------


def _env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        sys.exit(f"missing required environment variable {name}")
    return value


def cloud_main():
    """`system-explorer-cloud`: clone the repo, then serve one model folder."""
    repo = _env("GITHUB_REPO", required=True)            # owner/name
    model_path = _env("MODEL_PATH", required=True)       # folder in the repo
    token = _env("GITHUB_TOKEN", required=True)
    branch = _env("GITHUB_BRANCH", "main")
    remote = _env("GIT_REMOTE", f"https://github.com/{repo}.git")
    work_dir = Path(_env("WORK_DIR", "/tmp/system-explorer/repo"))
    port = int(_env("PORT", "8080"))

    sync = GitSync(remote, work_dir, branch, token,
                   pull_interval=float(_env("PULL_INTERVAL", "30")))
    print(f"Cloning {repo}@{branch} ...", flush=True)
    sync.clone_or_update()

    folder = (work_dir / model_path).resolve()
    try:
        folder.relative_to(work_dir.resolve())
    except ValueError:
        sys.exit(f"MODEL_PATH escapes the repository: {model_path}")
    if not folder.is_dir():
        sys.exit(f"MODEL_PATH is not a directory: {model_path}")
    # The folder is a workspace. Projects live under projects/ and are
    # committed with GitSync. .sysml files already in the folder (the
    # spine-cooling model, in the deployment) are not the landing project
    # and are never rewritten. See docs/adr/0007-git-backed-projects.md.
    library = ProjectLibrary(folder)

    if _env("ALLOW_ANONYMOUS") == "1":
        auth = None
        print("WARNING: ALLOW_ANONYMOUS=1 - anyone with the URL can view "
              "and edit. Use only for local testing.", flush=True)
    else:
        auth = GitHubAuth(
            client_id=_env("GITHUB_CLIENT_ID", required=True),
            client_secret=_env("GITHUB_CLIENT_SECRET", required=True),
            session_secret=_env("SESSION_SECRET", required=True),
            public_url=_env("PUBLIC_URL", required=True),
            repo=repo, token=token,
            allowed_users=(_env("ALLOWED_USERS", "") or "").split(","),
        )

        def _open_new_project(user, _library=library, _sync=sync, _auth=auth):
            info = _library.create_empty(owner=user.get("login"))
            _sync.commit_and_push(
                info["files"], f"Create project '{info['name']}'", user
            )
            return [project_cookie_header(info["id"], secure=_auth.secure)]

        auth.on_login = _open_new_project

    # Assistant configuration (optional). The methodology file ships with
    # this tool. The cloned model repo does not contain it.
    assistant_settings = None
    try:
        from assistant.config import explorer_settings
        assistant_settings = explorer_settings(folder, "", port)
        if assistant_settings:
            print(
                f"SE assistant enabled: {assistant_settings.base_url} "
                f"model {assistant_settings.model}",
                flush=True,
            )
        else:
            print(
                "SE assistant disabled (set ASSISTANT_BASE_URL and "
                "ASSISTANT_MODEL to enable)",
                flush=True,
            )
    except ImportError:
        print("SE assistant module not available", flush=True)
    
    handler = make_handler(folder, folder / "layout.json",
                           CloudContext(sync, auth, work_dir),
                           assistant_settings, library=library)
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"Serving workspace {repo}:{model_path} on port {port}", flush=True)
    print("Each sign-in starts a new project under projects/.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cloud_main()
