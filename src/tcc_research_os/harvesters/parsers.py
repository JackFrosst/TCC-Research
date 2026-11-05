import json
import xml.etree.ElementTree as ET
from html.parser import HTMLParser


def parse_oai_dc(xml: str) -> tuple[list[dict], str | None]:
    root = ET.fromstring(xml)
    records = []
    for node in root.findall(".//{http://www.openarchives.org/OAI/2.0/}record"):
        header = node.find("{http://www.openarchives.org/OAI/2.0/}header")
        metadata = node.find("{http://www.openarchives.org/OAI/2.0/}metadata")
        values: dict[str, list[str]] = {}
        if metadata is not None:
            for element in metadata.iter():
                if element is metadata or not element.text:
                    continue
                values.setdefault(element.tag.rsplit("}", 1)[-1], []).append(element.text.strip())
        records.append(
            {
                "identifier": header.findtext("{http://www.openarchives.org/OAI/2.0/}identifier")
                if header is not None
                else None,
                **values,
            }
        )
    token = root.findtext(".//{http://www.openarchives.org/OAI/2.0/}resumptionToken")
    return records, token.strip() if token and token.strip() else None


def parse_sitemap(xml: str) -> list[dict]:
    root = ET.fromstring(xml)
    namespace = root.tag.partition("}")[0].lstrip("{")
    prefix = f"{{{namespace}}}" if namespace else ""
    return [
        {"url": node.findtext(f"{prefix}loc"), "last_modified": node.findtext(f"{prefix}lastmod")}
        for node in root.findall(f"{prefix}url")
        if node.findtext(f"{prefix}loc")
    ]


class _MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta: dict[str, list[str]] = {}
        self.json_ld: list[dict] = []
        self._json_script = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "meta" and values.get("content"):
            key = values.get("name") or values.get("property")
            if key:
                self.meta.setdefault(key.lower(), []).append(values["content"])
        self._json_script = tag == "script" and values.get("type") == "application/ld+json"
        if self._json_script:
            self._buffer = []

    def handle_data(self, data):
        if self._json_script:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._json_script:
            try:
                value = json.loads("".join(self._buffer))
                self.json_ld.extend(value if isinstance(value, list) else [value])
            except json.JSONDecodeError:
                pass
            self._json_script = False


def parse_structured_html(html: str) -> dict:
    parser = _MetadataParser()
    parser.feed(html)
    return {"meta": parser.meta, "json_ld": parser.json_ld}
