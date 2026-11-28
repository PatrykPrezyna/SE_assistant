"""Projects inside one workspace folder.

Hosted mode has no durable disk (see docs/adr/0001-git-backed-projects.md).
Each project is a directory under ``<workspace>/projects/<id>/`` and is
committed with the git sync the server already uses. Files that already
live in the workspace root — the spine-cooling model, in the deployment —
are never written, deleted, or staged by this module.

The insulin-pump example ships in this package. It is not copied into the
workspace until someone edits it.
"""

import json
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

EXAMPLE_ID = "example"
REPOSITORY_ID = "repository"
PROJECT_COOKIE = "sx_project"
EXAMPLE_NAME = "Insulin pump"

# Folder names we will create. `example` and `repository` are cookie values,
# not directories, so a project can never shadow them.
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
_RESERVED = frozenset({EXAMPLE_ID, REPOSITORY_ID})

_SKELETON = {
    "NewProject.sysml": """\
package NewProject {
    doc /*
    A new project. Say what the system is, in a sentence or two.
    */
}
""",
    "NewProjectContext.sysml": """\
package NewProjectContext {
    private import NewProject::*;

    doc /*
    People and organizations around the system. Add each one as a part def
    in this file, the same way the insulin pump example defines Patient
    and Caregiver.
    */
}
""",
}


def example_dir() -> Path:
    """The bundled insulin-pump model. Present after pip install."""
    return Path(__file__).resolve().parent / "examples" / "insulin-pump"


def read_project_cookie(header):
    if not header:
        return None
    # A tiny reader so this module does not import cloud.py (cloud imports app).
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        if name == PROJECT_COOKIE and value:
            return value
    return None


def project_cookie_header(project_id, secure=False, max_age=31536000):
    attrs = (
        f"{PROJECT_COOKIE}={project_id}; Path=/; SameSite=Lax; Max-Age={max_age}"
    )
    if secure:
        attrs += "; Secure"
    return attrs


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sysml_files(folder: Path):
    return sorted(Path(folder).glob("*.sysml"), key=lambda p: p.name)


class ProjectLibrary:
    """The ``projects/`` tree inside one workspace root."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.projects_dir = self.root / "projects"
        # Local workspace: the project created when the process started.
        # Hosted mode leaves this empty and creates one on login instead.
        self.default_id = None

    def assert_project_file(self, path: Path):
        """Refuse any write that is not inside ``projects/<id>/``.

        This is the guard that keeps the spine-cooling files at the
        workspace root untouched.
        """
        resolved = Path(path).resolve()
        try:
            rel = resolved.relative_to(self.projects_dir.resolve())
        except ValueError:
            raise PermissionError(
                f"refusing to write outside projects/: {path}"
            ) from None
        if not rel.parts or rel.parts[0] in _RESERVED or not _ID_RE.match(rel.parts[0]):
            raise PermissionError(
                f"refusing to write outside a project folder: {path}"
            )
        return resolved

    def create_empty(self, owner=None):
        """Write a package plus an empty context file. Does not commit."""
        project_id = self._new_id()
        dest = self.projects_dir / project_id
        dest.mkdir(parents=True)
        meta = {
            "id": project_id,
            "name": "New project",
            "created": _now(),
            "owner": owner or "",
            "kind": "empty",
        }
        files = []
        for name, text in _SKELETON.items():
            path = dest / name
            path.write_text(text, encoding="utf-8")
            files.append(self.assert_project_file(path))
        meta_path = dest / "project.json"
        meta_path.write_text(
            json.dumps(meta, indent=2) + "\n", encoding="utf-8"
        )
        files.append(self.assert_project_file(meta_path))
        return {**meta, "dir": dest, "files": files, "readOnly": False}

    def copy_example(self, owner=None):
        """Copy the packaged example into a new writable project."""
        source = example_dir()
        if not _sysml_files(source):
            raise FileNotFoundError(f"insulin pump example is missing at {source}")
        project_id = self._new_id()
        dest = self.projects_dir / project_id
        shutil.copytree(source, dest)
        meta = {
            "id": project_id,
            "name": "Insulin pump copy",
            "created": _now(),
            "owner": owner or "",
            "kind": "copy",
        }
        meta_path = dest / "project.json"
        meta_path.write_text(
            json.dumps(meta, indent=2) + "\n", encoding="utf-8"
        )
        files = [
            self.assert_project_file(p)
            for p in dest.rglob("*")
            if p.is_file()
        ]
        return {**meta, "dir": dest, "files": files, "readOnly": False}

    def list_projects(self):
        """Newest saved project first, then the read-only repository model."""
        items = []
        if self.projects_dir.is_dir():
            for child in self.projects_dir.iterdir():
                if not child.is_dir() or not _ID_RE.match(child.name):
                    continue
                if child.name in _RESERVED:
                    continue
                items.append(self._describe(child))
        items.sort(key=lambda item: item.get("created") or "", reverse=True)
        repo = self.repository_entry()
        if repo:
            items.append(repo)
        return items

    def repository_entry(self):
        if not _sysml_files(self.root):
            return None
        return {
            "id": REPOSITORY_ID,
            "name": "Repository model",
            "readOnly": True,
            "kind": "repository",
            "created": "",
            "owner": "",
        }

    def resolve(self, project_id):
        """Return a binding dict, or None when ``project_id`` is unknown."""
        if project_id == EXAMPLE_ID:
            folder = example_dir()
            return {
                "folder": folder,
                "readOnly": True,
                "project": {
                    "id": EXAMPLE_ID,
                    "name": EXAMPLE_NAME,
                    "readOnly": True,
                    "kind": "example",
                },
            }
        if project_id == REPOSITORY_ID:
            entry = self.repository_entry()
            if entry is None:
                return None
            return {"folder": self.root, "readOnly": True, "project": entry}
        if project_id and self._is_project(project_id):
            folder = self.projects_dir / project_id
            return {
                "folder": folder,
                "readOnly": False,
                "project": self._describe(folder),
            }
        return None

    def _describe(self, folder: Path):
        meta = {}
        meta_path = folder / "project.json"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except ValueError:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        return {
            "id": folder.name,
            "name": meta.get("name") or "Project",
            "created": meta.get("created") or "",
            "owner": meta.get("owner") or "",
            "kind": meta.get("kind") or "project",
            "readOnly": False,
        }

    def _is_project(self, project_id):
        if not project_id or project_id in _RESERVED or not _ID_RE.match(project_id):
            return False
        folder = self.projects_dir / project_id
        return folder.is_dir() and (
            (folder / "project.json").is_file() or bool(_sysml_files(folder))
        )

    def _new_id(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        for _ in range(5):
            project_id = f"p{stamp}-{secrets.token_hex(2)}"
            if not (self.projects_dir / project_id).exists():
                return project_id
        raise RuntimeError("could not allocate a project id")
