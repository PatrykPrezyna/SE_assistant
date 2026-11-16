"""Validate .sysml files using the JamieD sysml-v2-support parser (sysml-v2-lsp).

Uses the MCP server bundled with the free VS Code / Cursor extension
`JamieD.sysml-v2-support` — no SysIDE license required. Needs Node.js on
PATH; the extension is located automatically (override with the
SYSML_V2_LSP_MCP environment variable).

Usage:
  python -m system_explorer.jamied_check <folder>
  python -m system_explorer.jamied_check path/to/file.sysml
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path


def find_mcp_server() -> Path:
    env = os.environ.get("SYSML_V2_LSP_MCP")
    if env and Path(env).is_file():
        return Path(env)

    roots = [
        Path(os.environ.get("USERPROFILE", "")) / ".vscode" / "extensions",
        Path(os.environ.get("USERPROFILE", "")) / ".cursor" / "extensions",
        Path(os.environ.get("HOME", "")) / ".vscode" / "extensions",
        Path(os.environ.get("HOME", "")) / ".cursor" / "extensions",
    ]
    matches: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        matches.extend(
            root.glob(
                "jamied.sysml-v2-support-*/node_modules/"
                "sysml-v2-lsp/dist/server/mcpServer.js"
            )
        )
    if not matches:
        sys.exit(
            "JamieD sysml-v2-support MCP server not found.\n"
            "Install the VS Code extension 'JamieD.sysml-v2-support', or set "
            "SYSML_V2_LSP_MCP to mcpServer.js."
        )
    return sorted(matches)[-1]


def collect_sysml(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    files = sorted(path.glob("*.sysml"))
    if not files:
        sys.exit(f"No .sysml files in {path}")
    return files


class McpClient:
    def __init__(self, server_js: Path):
        node = shutil.which("node")
        if not node:
            sys.exit("Node.js ('node') is required on PATH.")
        self.proc = subprocess.Popen(
            [node, str(server_js)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._id = 0
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            sys.stderr.buffer.write(line)

    def _send(self, msg: dict) -> None:
        assert self.proc.stdin is not None
        line = (json.dumps(msg) + "\n").encode("utf-8")
        self.proc.stdin.write(line)
        self.proc.stdin.flush()

    def _recv(self) -> dict:
        assert self.proc.stdout is not None
        while True:
            raw = self.proc.stdout.readline()
            if not raw:
                raise RuntimeError("MCP server closed unexpectedly")
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            return json.loads(line)

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        req_id = self._id
        self._send(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        )
        while True:
            msg = self._recv()
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self) -> None:
        if self.proc.stdin:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _tool_payload(result: dict) -> dict:
    if "content" not in result:
        return result
    chunks = [
        c.get("text", "")
        for c in result.get("content", [])
        if c.get("type") == "text"
    ]
    joined = "\n".join(chunks).strip()
    if not joined:
        return result
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        return {"raw": joined}


def _extract_diags(payload: dict) -> list:
    """Return blocking diagnostics (syntax errors + semantic errors).

    JamieD's validate tool sets ``valid: true`` when syntax is OK even if
    soft warnings remain (e.g. unused-definition false positives on nested
    part usages). Only fail the script on real errors.
    """
    collected: list = []

    for d in payload.get("syntaxErrors") or []:
        if isinstance(d, dict):
            collected.append({**d, "severity": "error"})
        else:
            collected.append({"message": str(d), "severity": "error"})

    for d in payload.get("semanticIssues") or payload.get("semanticErrors") or []:
        if not isinstance(d, dict):
            collected.append({"message": str(d), "severity": "error"})
            continue
        sev = str(d.get("severity", "warning")).lower()
        if sev in ("error", "fatal"):
            collected.append({**d, "severity": "error"})

    for key in ("diagnostics", "errors", "issues"):
        if key not in payload or payload[key] is None:
            continue
        diags = payload[key]
        if isinstance(diags, dict):
            diags = diags.get("items") or diags.get("diagnostics") or [diags]
        if not isinstance(diags, list):
            diags = [diags]
        for d in diags:
            if isinstance(d, str):
                collected.append({"message": d, "severity": "error"})
                continue
            sev = str(d.get("severity", "error")).lower()
            if sev in ("error", "fatal"):
                collected.append(d)

    if collected:
        return collected
    if payload.get("valid") is False or payload.get("ok") is False:
        return [{"message": json.dumps(payload)[:500], "severity": "error"}]
    return []


def validate_sources(client: McpClient, files: list[Path]) -> list[dict]:
    tools = client.request("tools/list")
    names = {t["name"] for t in tools.get("tools", [])}
    if "validate" not in names and "parse" not in names:
        sys.exit(f"Unexpected MCP tools: {sorted(names)}")

    # Prefer validate; also try common arg shapes
    tool = "validate" if "validate" in names else "parse"

    all_diags: list[dict] = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        args = {"code": text, "uri": f.as_uri()}
        result = client.request("tools/call", {"name": tool, "arguments": args})
        payload = _tool_payload(result)
        diags = _extract_diags(payload)
        for d in diags:
            if isinstance(d, str):
                all_diags.append({"file": str(f), "message": d})
            else:
                all_diags.append({"file": str(f), **d})
        if not diags:
            print(f"OK  {f}")
        else:
            print(f"ERR {f}  ({len(diags)} diagnostic(s))")
    return all_diags


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)
    target = Path(sys.argv[1]).resolve()
    files = collect_sysml(target)
    server = find_mcp_server()
    print(f"Using JamieD parser MCP: {server}", file=sys.stderr)
    print(f"Checking {len(files)} file(s)…", file=sys.stderr)

    client = McpClient(server)
    try:
        client.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "system_explorer.jamied_check", "version": "0.1"},
            },
        )
        client.notify("notifications/initialized", {})
        diags = validate_sources(client, files)
    finally:
        client.close()

    if diags:
        print("\nDiagnostics:")
        for d in diags:
            sev = d.get("severity", d.get("severityName", "error"))
            msg = d.get("message", d)
            line = d.get("line")
            if line is None:
                rng = d.get("range") or {}
                start = rng.get("start") or {}
                line = start.get("line")
            loc = f":{int(line) + 1}" if isinstance(line, int) else ""
            print(f"  [{sev}] {d.get('file', '?')}{loc}: {msg}")
        sys.exit(1)
    print("\nAll checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
