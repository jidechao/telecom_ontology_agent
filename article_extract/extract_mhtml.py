# -*- coding: utf-8 -*-
"""Extract readable article text from an MHTML snapshot."""
import email
import re
import sys
from html.parser import HTMLParser


class TextExtractor(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag in ("p", "div", "section", "h1", "h2", "h3", "h4", "li", "br", "tr", "table"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in ("p", "div", "section", "h1", "h2", "h3", "h4", "li", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0:
            self.parts.append(data)


def main(src, dst):
    with open(src, "rb") as f:
        msg = email.message_from_bytes(f.read())

    html_payload = None
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "text/html" and html_payload is None:
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or "utf-8"
            html_payload = payload.decode(charset, errors="replace")

    if html_payload is None:
        print("no html part found", file=sys.stderr)
        sys.exit(1)

    parser = TextExtractor()
    parser.feed(html_payload)
    text = "".join(parser.parts)
    # Normalize whitespace
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = text.strip()

    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"extracted {len(text)} chars -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
