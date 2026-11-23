"""HTML renderer (minimal, dependency-free, dark theme consistent with the UI)."""
from __future__ import annotations

import html as html_lib
import re


def _inline(text: str) -> str:
    escaped = html_lib.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def render_html(title: str, markdown: str) -> str:
    body: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            body.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("### "):
            body.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("- "):
            body.append(f"<li>{_inline(line[2:])}</li>")
        elif line.strip():
            body.append(f"<p>{_inline(line)}</p>")
    content = "\n".join(body)
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html_lib.escape(title)}</title>
<style>body{{background:#0b1020;color:#edf3ff;font:15px Inter,system-ui,sans-serif;max-width:900px;margin:auto;padding:32px}}
h2{{color:#6ea8fe;border-bottom:1px solid #26334d;padding-bottom:8px}}h3{{color:#36d399}}li{{margin:5px 0}}p{{line-height:1.6}}</style>
</head><body><h1>{html_lib.escape(title)}</h1>{content}</body></html>"""
