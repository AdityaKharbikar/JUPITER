"""Turn a validated spec dict into a single self-contained HTML file (viewer + data inlined, no CDN)."""
import json
import os
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent / "web"


def _safe_json(spec: dict) -> str:
    # Keep the JSON from ever closing the <script> tag or starting an HTML comment.
    return (json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
            .replace("</", "<\\/").replace("<!--", "<\\!--").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render_html(spec: dict) -> str:
    template = (WEB_DIR / "template.html").read_text(encoding="utf-8")
    viewer = (WEB_DIR / "viewer.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
    title = str(spec.get("title", "Model")).replace("<", "").replace(">", "").replace("&", "and")
    return (template.replace("__TITLE__", title).replace("__SPEC__", _safe_json(spec))
            .replace("__VIEWER_JS__", viewer))


def write_html(spec: dict, path) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(render_html(spec), encoding="utf-8")
    os.replace(tmp, path)
    return str(path)
