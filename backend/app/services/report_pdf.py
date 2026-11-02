"""PDF rendering for investigation reports (dependency-light, via PyMuPDF).

PyMuPDF (``fitz``) is already a runtime dependency (used for PDF text
extraction), so no new package is required. The renderer lays out the same
report sections used by the on-screen and markdown views into a paginated A4
document.

All text is sanitised and re-encoded to Latin-1 with replacement so untrusted
content can never break the layout or the file. No HTML is interpreted: text is
drawn as literal glyphs, so there is no markup-injection surface.
"""
from __future__ import annotations

import fitz  # PyMuPDF

from .report_service import escape_text, safe_text

PAGE_W, PAGE_H = 595.0, 842.0  # A4 in points
MARGIN_X = 54.0
MARGIN_TOP = 56.0
MARGIN_BOTTOM = 54.0
LINE_GAP = 4.0


def _latin1(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


class _Layout:
    def __init__(self) -> None:
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.y = MARGIN_TOP
        self.max_w = PAGE_W - 2 * MARGIN_X

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.y = MARGIN_TOP

    def _ensure(self, needed: float) -> None:
        if self.y + needed > PAGE_H - MARGIN_BOTTOM:
            self._new_page()

    def _wrap(self, text: str, size: float, font: str) -> list[str]:
        words = text.split(" ")
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            width = fitz.get_text_length(candidate, fontname=font, fontsize=size)
            if width <= self.max_w or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def write(self, text: str, *, size: float = 10.5, bold: bool = False, indent: float = 0.0) -> None:
        font = "hebo" if bold else "helv"
        text = _latin1(escape_text(text))
        line_h = size + LINE_GAP
        for line in self._wrap(text, size, font):
            self._ensure(line_h)
            self.page.insert_text(
                fitz.Point(MARGIN_X + indent, self.y),
                line,
                fontname=font,
                fontsize=size,
                color=(0.1, 0.11, 0.13),
            )
            self.y += line_h

    def space(self, amount: float = 6.0) -> None:
        self.y += amount

    def rule(self) -> None:
        self._ensure(6)
        self.page.draw_line(
            fitz.Point(MARGIN_X, self.y),
            fitz.Point(PAGE_W - MARGIN_X, self.y),
            color=(0.8, 0.82, 0.85),
            width=0.5,
        )
        self.y += 6


def render_report_pdf(report: dict) -> bytes:
    """Render a ``build_report`` result to PDF bytes."""
    layout = _Layout()
    layout.write(safe_text(report.get("title")) or "Investigation Report", size=17, bold=True)
    layout.space(2)
    objective = safe_text(report.get("objective"))
    if objective:
        layout.write(f"Question: {objective}", size=10.5)
    generated = safe_text(report.get("json_data", {}).get("generated_at"))
    layout.write(
        f"Generated: {generated}    Confidence: {report.get('confidence', 0.0):.2f}",
        size=9.5,
    )
    inv = report.get("json_data", {}).get("investigation", {})
    if inv.get("id") is not None:
        layout.write(
            f"Investigation id: {inv['id']}    Status: {safe_text(inv.get('status'))}",
            size=9.5,
        )
    if inv.get("is_demo"):
        layout.write("Demonstration data for evaluation purposes.", size=9.5, bold=True)
    layout.space(4)
    layout.rule()

    for section in report.get("sections", []):
        layout.space(4)
        layout.write(safe_text(section.get("heading")), size=12, bold=True)
        body = safe_text(section.get("body"))
        if body:
            layout.write(body, size=10.5)
        for item in section.get("items", []):
            layout.write(f"\u2022 {safe_text(item)}", size=10, indent=10.0)
        layout.space(2)

    pdf_bytes = layout.doc.tobytes()
    layout.doc.close()
    return pdf_bytes


def report_filename(name: str) -> str:
    """A safe download filename for a report PDF."""
    cleaned = "".join(
        ch if ch.isalnum() or ch in ("-", "_", " ") else "-" for ch in (name or "investigation")
    ).strip()
    cleaned = "-".join(cleaned.split()) or "investigation"
    return f"{cleaned[:80]}-report.pdf"
