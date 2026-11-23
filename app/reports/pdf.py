"""Minimal dependency-free PDF export.

The full-fidelity export is HTML/Markdown; this compact PDF is optimized for
reliability in a minimal container. Text is transliterated to the Latin subset
supported by the built-in Helvetica font so Cyrillic reports still render.
"""
from __future__ import annotations

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _ascii(text: str) -> str:
    out = []
    for ch in text:
        low = ch.lower()
        if low in _TRANSLIT:
            repl = _TRANSLIT[low]
            out.append(repl.upper() if ch.isupper() else repl)
        elif ord(ch) < 128:
            out.append(ch)
        else:
            out.append("?")
    return "".join(out)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def render_pdf(title: str, markdown: str) -> bytes:
    lines = []
    for raw in markdown.splitlines():
        line = _ascii(raw.strip())
        if not line:
            lines.append("")
            continue
        line = line.replace("#", "").replace("**", "").replace("- ", "  - ")
        # Wrap long lines for A4 width at ~95 chars.
        while len(line) > 95:
            cut = line.rfind(" ", 0, 95)
            cut = cut if cut > 40 else 95
            lines.append(line[:cut])
            line = "  " + line[cut:].lstrip()
        lines.append(line)

    page_lines = []
    for line in lines[:55]:  # first page; enough for a compact report
        page_lines.append(line)
    content = ["BT", "/F1 9 Tf", "12 TL", "40 800 Td"]
    for line in page_lines:
        content.append(f"({_escape(line)}) Tj")
        content.append("T*")
    content.append("ET")
    stream = "\n".join(content).encode("latin-1", "replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    return bytes(out)
