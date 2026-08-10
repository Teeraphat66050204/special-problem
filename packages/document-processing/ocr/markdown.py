"""Deterministic Typhoon Markdown to plain-text conversion."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any


class PlainHTMLExtractor(HTMLParser):
    """Collect visible HTML text while retaining block and table order."""

    BLOCK_END_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "p",
        "page_number",
        "pre",
        "section",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def _line_break(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if tag == "br":
            self._line_break()
        elif tag in {"td", "th"} and self.parts and not self.parts[-1].endswith(
            ("\n", "\t")
        ):
            self.parts.append("\t")
        elif tag == "img":
            alt_text = dict(attrs).get("alt")
            if alt_text:
                self.parts.append(alt_text)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            if self.ignored_depth:
                self.ignored_depth -= 1
            return
        if self.ignored_depth:
            return
        if tag in {"td", "th"}:
            if self.parts and not self.parts[-1].endswith(("\n", "\t")):
                self.parts.append("\t")
        elif tag in self.BLOCK_END_TAGS:
            self._line_break()

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth and not data.isspace():
            self.parts.append(data)

    def plain_text(self) -> str:
        lines = [line.strip() for line in "".join(self.parts).splitlines()]
        nonempty_lines = [line for line in lines if line]
        return "\n".join(nonempty_lines) + ("\n" if nonempty_lines else "")


def markdown_to_plain_text(raw_markdown: str, markdown_it_class: Any) -> str:
    """Convert raw Typhoon Markdown with the benchmark's deterministic rules."""
    parser = markdown_it_class("commonmark", {"html": True}).enable("table")
    parseable_markdown = raw_markdown.replace(
        "<page_number>",
        '<span data-typhoon-page-number="true">',
    ).replace("</page_number>", "</span>")
    rendered_html = parser.render(parseable_markdown)
    extractor = PlainHTMLExtractor()
    extractor.feed(rendered_html)
    extractor.close()
    return extractor.plain_text()
