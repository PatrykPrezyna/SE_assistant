"""Settings for the assistant. Secrets come from the environment or a gitignored .env."""

import os
from pathlib import Path

DEFAULT_EXPLORER_URL = "http://127.0.0.1:8199/"
DEFAULT_PORT = 8201
DEFAULT_CHAT_PATH = "/chat/completions"
DEFAULT_AUTH = "bearer"


def repo_root():
    """Directory that contains methodology/product-development.yaml.

    The file lives in this tool's repo, not in the model being explored.
    An installed image keeps a copy at /app/methodology (see the Dockerfile).
    """
    here = Path(__file__).resolve()
    candidates = [*here.parents, Path("/app"), Path.cwd()]
    seen = set()
    for parent in candidates:
        try:
            parent = parent.resolve()
        except OSError:
            continue
        if parent in seen:
            continue
        seen.add(parent)
        if (parent / "methodology" / "product-development.yaml").is_file():
            return parent
    raise RuntimeError(
        "cannot find methodology/product-development.yaml above the assistant package"
    )


def default_methodology():
    """Path to the tool's methodology file. Never a path inside the model folder."""
    try:
        return repo_root() / "methodology" / "product-development.yaml"
    except RuntimeError:
        return Path("/app/methodology/product-development.yaml")


def explorer_settings(model_folder, explorer_url, port, environ=None):
    """Settings for the chat routes mounted on the explorer.

    Returns None when ASSISTANT_BASE_URL or ASSISTANT_MODEL is unset.
    The methodology file is the tool's own file unless ASSISTANT_METHODOLOGY
    points somewhere else. It is not looked up inside `model_folder`.
    """
    environ = os.environ if environ is None else environ
    base_url = environ.get("ASSISTANT_BASE_URL") or ""
    model = environ.get("ASSISTANT_MODEL") or ""
    if not base_url or not model:
        return None
    methodology = environ.get("ASSISTANT_METHODOLOGY") or str(default_methodology())
    return Settings(
        base_url=base_url,
        api_key=environ.get("ASSISTANT_API_KEY") or "",
        model=model,
        model_folder=str(model_folder),
        explorer_url=explorer_url or "",
        methodology=methodology,
        host=environ.get("ASSISTANT_HOST") or "127.0.0.1",
        port=int(port),
        chat_path=environ.get("ASSISTANT_CHAT_PATH") or DEFAULT_CHAT_PATH,
        auth=environ.get("ASSISTANT_AUTH") or DEFAULT_AUTH,
        auth_user=environ.get("ASSISTANT_AUTH_USER") or "",
        auth_password=environ.get("ASSISTANT_AUTH_PASSWORD") or "",
    )


def read_env_file(path):
    """Parse KEY=VALUE lines. Blank lines and # comments are ignored."""
    path = Path(path)
    if not path.is_file():
        return {}
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def file_settings():
    """Values from .env files. The current directory's file wins over the repo
    file. Neither overrides a real environment variable; load_settings applies
    that rule."""
    merged = {}
    seen = set()
    for path in (repo_root() / ".env", Path.cwd() / ".env"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        merged.update(read_env_file(path))
    return merged


class Settings:
    def __init__(
        self,
        base_url,
        api_key,
        model,
        model_folder,
        explorer_url,
        methodology,
        host,
        port,
        chat_path,
        auth,
        auth_user,
        auth_password,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.model_folder = Path(model_folder) if model_folder else None
        self.explorer_url = explorer_url or DEFAULT_EXPLORER_URL
        self.methodology = Path(methodology)
        self.host = host or "127.0.0.1"
        self.port = int(port)
        self.chat_path = chat_path if chat_path.startswith("/") else "/" + chat_path
        self.auth = auth or DEFAULT_AUTH
        self.auth_user = auth_user or ""
        self.auth_password = auth_password or ""

    def configuration_error(self):
        """A message when the provider is not ready. Never includes the key."""
        missing = []
        if not self.base_url:
            missing.append("ASSISTANT_BASE_URL")
        if not self.model:
            missing.append("ASSISTANT_MODEL")
        if not self.model_folder:
            missing.append("MODEL_FOLDER")
        elif not self.model_folder.is_dir():
            return f"MODEL_FOLDER is not a directory: {self.model_folder}"
        if missing:
            return (
                "Set " + ", ".join(missing) + " in .env or the environment. "
                "Add ASSISTANT_API_KEY when the provider requires a key."
            )
        if not self.methodology.is_file():
            return (
                "Methodology file not found at "
                + str(self.methodology)
                + ". Set ASSISTANT_METHODOLOGY to methodology/product-development.yaml."
            )
        return None


def load_settings(environ=None, overrides=None, files=None):
    """Build settings. Real environment variables win over .env files.

    Pass `files` to skip reading .env from disk (tests).
    """
    environ = os.environ if environ is None else environ
    if files is None:
        files = file_settings()

    def get(name, default=""):
        if name in environ and environ[name] != "":
            return environ[name]
        if name in files:
            return files[name]
        return default

    port = get("PORT") or get("ASSISTANT_PORT", str(DEFAULT_PORT))
    
    data_dir = get("SE_DATA_DIR") or get("MODEL_FOLDER")
    
    values = {
        "base_url": get("ASSISTANT_BASE_URL"),
        "api_key": get("ASSISTANT_API_KEY"),
        "model": get("ASSISTANT_MODEL"),
        "model_folder": data_dir,
        "explorer_url": get("EXPLORER_URL", DEFAULT_EXPLORER_URL),
        "methodology": get(
            "ASSISTANT_METHODOLOGY",
            str(repo_root() / "methodology" / "product-development.yaml"),
        ),
        "host": get("ASSISTANT_HOST", "127.0.0.1"),
        "port": port,
        "chat_path": get("ASSISTANT_CHAT_PATH", DEFAULT_CHAT_PATH),
        "auth": get("ASSISTANT_AUTH", DEFAULT_AUTH),
        "auth_user": get("SE_AUTH_USER"),
        "auth_password": get("SE_AUTH_PASSWORD"),
    }
    if overrides:
        for key, value in overrides.items():
            if value is not None and value != "":
                values[key] = value
    return Settings(**values)
