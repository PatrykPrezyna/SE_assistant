"""Write a static, view-only Viewer site from a model folder.

The Explorer stays the editor: an engineer arranges Views and documentation
links, commits the model folder, and ``system-explorer <folder> --publish
<outdir>`` turns that commit into the files GitHub Pages serves.
"""

import json
import re
import shutil
from pathlib import Path

from .app import RE_VIEW_ID, load_folder
from .version import __version__

_HTTP = re.compile(r"https?://", re.IGNORECASE)
_TEMPLATE = Path(__file__).with_name("publish_viewer.html")
_DATA_TOKEN = "__VIEWER_DATA__"


def _load_block_views(folder: Path):
    """Prepared block Views. Activity Views are Explorer-only and skipped."""
    views_dir = folder / "views"
    views = []
    skipped = 0
    if not views_dir.is_dir():
        return views, skipped
    for path in sorted(views_dir.glob("*.json"), key=lambda p: p.name):
        if not RE_VIEW_ID.match(path.stem):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("kind") == "activity":
            skipped += 1
            continue
        nodes = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        views.append({
            "id": path.stem,
            "name": data.get("name") or path.stem,
            "description": data.get("description") or "",
            "elements": list(data.get("elements") or []),
            "nodes": nodes,
            "hiddenEdges": list(data.get("hiddenEdges") or []),
        })
    return views, skipped


def _doc_target(folder: Path, raw: str):
    """Return ``(public_href, source_file)`` for a documentation link.

    HTTP(S) links pass through. A relative file is copied only when it
    resolves to a file inside ``folder``. Anything else is omitted.
    """
    text = (raw or "").strip()
    if not text:
        return None, None
    if _HTTP.match(text):
        return text, None
    root = folder.resolve()
    try:
        candidate = (root / text).resolve()
        rel = candidate.relative_to(root)
    except (OSError, ValueError):
        return None, None
    if not candidate.is_file():
        return None, None
    return "files/" + rel.as_posix(), candidate


def _documentation(folder: Path, outdir: Path):
    """Documentation links for the published site, plus paths that were dropped."""
    layout_path = folder / "layout.json"
    links = {}
    omitted = []
    copies = {}
    if layout_path.is_file():
        try:
            layout = json.loads(layout_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            layout = {}
        docs = layout.get("docs") if isinstance(layout, dict) else None
        if isinstance(docs, dict):
            for node_id, raw in docs.items():
                if not isinstance(raw, str):
                    omitted.append(str(raw))
                    continue
                href, source = _doc_target(folder, raw)
                if href is None:
                    omitted.append(raw)
                    continue
                links[str(node_id)] = href
                if source is not None:
                    copies[href] = source
    files_dir = outdir / "files"
    if files_dir.exists():
        shutil.rmtree(files_dir)
    for href, source in copies.items():
        dest = outdir / href
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    return links, omitted


def publish_site(folder: Path, outdir: Path):
    """Write the static Viewer into ``outdir``. Returns a small summary."""
    folder = folder.resolve()
    outdir = outdir.resolve()
    model, paths = load_folder(folder)
    if model is None:
        raise SystemExit(f"no .sysml files found directly in {folder}")
    model = dict(model)
    model["file"] = ", ".join(p.name for p in paths)
    model["explorerVersion"] = __version__
    views, skipped = _load_block_views(folder)
    outdir.mkdir(parents=True, exist_ok=True)
    links, omitted = _documentation(folder, outdir)
    bundle = {"model": model, "views": views, "docs": links}
    payload = json.dumps(bundle, ensure_ascii=False).replace("<", "\\u003c")
    template = _TEMPLATE.read_text(encoding="utf-8")
    if _DATA_TOKEN not in template:
        raise SystemExit(f"{_TEMPLATE.name} is missing the {_DATA_TOKEN} marker")
    (outdir / "index.html").write_text(
        template.replace(_DATA_TOKEN, payload, 1), encoding="utf-8")
    (outdir / "model.json").write_text(
        json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (outdir / "views.json").write_text(
        json.dumps({"views": views}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (outdir / "docs.json").write_text(
        json.dumps({"links": links, "omitted": omitted}, indent=2,
                   ensure_ascii=False) + "\n",
        encoding="utf-8")
    return {
        "views": len(views),
        "skippedActivity": skipped,
        "links": links,
        "omitted": omitted,
    }
