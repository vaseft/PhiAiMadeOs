"""Optional stdio tools for the workbench; human approval stays exclusively in UI."""
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from mcp.server import MCPServer
from .settings import get_settings

app = MCPServer("PAMOs local workbench proposals")


def call(path, body=None):
    token_path = get_settings().root / ".local/mcp-client-token"
    if not token_path.exists():
        raise ValueError("请先启动 PAMOs 工作台")
    request = urllib.request.Request("http://127.0.0.1:8765/api/v1/" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-PAMOS-MCP-Token": token_path.read_text(encoding="utf-8").strip(), "Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        result = exc.read(20000).decode("utf-8", errors="replace")
        raise ValueError(result) from None


def identifier(value):
    if not isinstance(value, str) or not value.isalnum() or len(value) > 64:
        raise ValueError("记录 ID 无效")
    return value


@app.tool()
def pamos_capabilities() -> dict:
    """Read actual capabilities; editor connection does not certify client compatibility."""
    return call("capabilities")


@app.tool()
def pamos_candidates() -> dict:
    """List immutable local candidates, their hashes and review state."""
    return call("candidates")


@app.tool()
def pamos_segment(candidate_id: str, start_s: float = 0, end_s: float = 30) -> dict:
    """Read a bounded timeline window. Audio and external APIs are not exposed."""
    return call(f"candidates/{identifier(candidate_id)}/timeline?" + urllib.parse.urlencode({"start_s": start_s, "end_s": end_s}))


@app.tool()
def pamos_propose(candidate_id: str, expected_chart_sha256: str, operations: list[dict], beat_window: list) -> dict:
    """Propose whitelist-only patch with CAS hash; requires separate workbench human approval."""
    return call(f"candidates/{identifier(candidate_id)}/proposals", {"expected_chart_sha256": expected_chart_sha256, "operations": operations, "beat_window": beat_window})


@app.tool()
def pamos_preview(proposal_id: str) -> dict:
    """Read diff and deterministic audit. No approval token is returned."""
    return call("proposals/" + identifier(proposal_id))


@app.tool()
def pamos_commit(proposal_id: str) -> dict:
    """Create an audited revision only after the human approves this exact diff in UI."""
    return call(f"proposals/{identifier(proposal_id)}/commit", {})


if __name__ == "__main__":
    app.run(transport="stdio")
