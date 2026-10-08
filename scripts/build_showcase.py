#!/usr/bin/env python3
"""Build/validate the public-only showcase with Python 3.10+ standard library.

No deployment, network requests, directory copying or template evaluation.
Output is fixed to the repository's ignored _site/ directory.
"""
import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
import struct
from string import Template
import sys
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).absolute().parent.parent
ROUTES = {
    "home.html": "index.html",
    "manufacturing.html": "manufacturing-demo.html",
    "governed-actions.html": "governed-actions.html",
    "reconciliation.html": "reconciliation.html",
    "concepts.html": "concepts.html",
    "boundary.html": "boundary.html",
}
ASSETS = {
    "assets/manufacturing-owner-dashboard.png": "a75921b961fc9917c176cb455ecc00f1e62b7521a82250b1b81b8389625a04ab",
    "assets/manufacturing-ai-human-approval.png": "b24ae8bea3f135bd1cfc4eb84a6b9d0b8d702fde24fbd5781fefa7a69a50d603",
    "assets/manufacturing-shipment-reconciliation.png": "da344a42a50a363cbb50a99c7470c2df43907a63e473f537c5bb2073967d466c",
    "assets/terminal-demo-overview.png": "bb8d001599c43da979929cc4fc9fe88550f35c025563f4bd0e316c8a11417fcc",
}
FILES = frozenset(ROUTES.values()) | frozenset(ASSETS) | {"styles.css", "sitemap.xml", ".nojekyll"}
INPUTS = ["site/layout.html", "site/pages.json", "site/styles.css"] + ["site/pages/" + p for p in ROUTES] + list(ASSETS)
FORBIDDEN = re.compile(r"/Users/|/home/|file://|general_agent_framework|(?:gh[pousr]_[A-Za-z0-9]{20,})|(?:sk-[A-Za-z0-9]{20,})|-----BEGIN .*PRIVATE KEY|(?:password|api[_-]?key|access[_-]?token)\s*[:=]", re.I)
STATIC_TAGS = frozenset("html head meta title link body a header div span small nav ul li main footer strong section p h1 h2 h3 aside figure img figcaption article ol br".split())
GLOBAL_ATTRIBUTES = frozenset("id class lang aria-label aria-labelledby aria-hidden".split())
TAG_ATTRIBUTES = {
    "a": {"href", "aria-current"},
    "main": {"tabindex"},
    "meta": {"charset", "name", "property", "content"},
    "link": {"rel", "href"},
    "img": {"src", "width", "height", "alt", "loading"},
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def relative_parts(relative):
    """Validate a relative name without touching the filesystem."""
    require(isinstance(relative, str) and relative and "\\" not in relative, "Invalid path")
    parts = relative.split("/")
    require(not PurePosixPath(relative).is_absolute() and all(p not in ("", ".", "..") for p in parts), "Traversal or absolute path rejected")
    return parts


def safe_path(root, relative):
    """Reject traversal, symlink ancestors and hardlinked regular files."""
    parts = relative_parts(relative)
    root = root.absolute()
    for ancestor in [root, *root.parents]:
        require(not ancestor.is_symlink(), "Symlink ancestor rejected")
    path = root
    for part in parts:
        path = path / part
        require(not path.is_symlink(), "Symlink input/output rejected: " + relative)
        if path.is_file():
            require(path.stat().st_nlink == 1, "Hardlinked input/output rejected: " + relative)
    return path


def public_base(value):
    require(value and not any(c.isspace() for c in value), "A public HTTPS base URL is required")
    url = urlsplit(value)
    require(url.scheme == "https" and url.hostname and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.github\.io", url.hostname), "Use a public HTTPS GitHub Pages project URL")
    require(url.username is None and url.password is None and not url.port and not url.query and not url.fragment, "Base URL cannot contain credentials, port, query or fragment")
    require(url.path in ("/general-agent-framework", "/general-agent-framework/"), "Base URL must use the project path")
    return "https://" + url.hostname + "/general-agent-framework/"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_sources():
    data = {}
    for name in INPUTS:
        path = safe_path(ROOT, name)
        require(path.is_file(), "Missing input: " + name)
        data[name] = path.read_bytes()
    for name, digest in ASSETS.items():
        require(sha(data[name]) == digest, "Frozen source checksum mismatch: " + name)
    config = json.loads(data["site/pages.json"])
    require(set(config) == {"pages", "assets"}, "Unexpected configuration keys")
    require(isinstance(config["pages"], list) and len(config["pages"]) == 6, "Expected six pages")
    seen = set()
    for page in config["pages"]:
        require(set(page) == {"source", "output", "nav", "lang", "title", "description"}, "Unexpected page keys")
        require(all(isinstance(v, str) and v.strip() for v in page.values()), "Page values must be nonempty strings")
        safe_path(ROOT / "site/pages", page["source"])
        safe_path(ROOT / "_site", page["output"])
        require(ROUTES.get(page["source"]) == page["output"] and page["source"] not in seen, "Page source/output outside whitelist or duplicated")
        require(page["lang"] in ("en", "zh-CN"), "Unsupported page language")
        seen.add(page["source"])
    for key in ("title", "description", "nav"):
        require(len({p[key] for p in config["pages"]}) == 6, "Page " + key + " must be unique")
    expected_assets = [{"source": name, "output": name, "sha256": digest} for name, digest in ASSETS.items()]
    require(config["assets"] == expected_assets, "Asset configuration differs from frozen whitelist")
    return data, config["pages"]


def scan_text(text, name):
    require(not FORBIDDEN.search(text), "Potential private path or credential in: " + name)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.refs, self.images, self.meta, self.links = set(), [], [], {}, []
        self.h1 = self.main = self.header = self.footer = 0
        self.title = ""
        self.in_title = False
        self.lang = None
        self.current = []
        self.aria_refs = []

    def handle_starttag(self, tag, attrs):
        require(len({k for k, _ in attrs}) == len(attrs), "Duplicate HTML attribute")
        a = dict(attrs)
        require(tag in STATIC_TAGS, "Unsupported HTML tag: " + tag)
        require(set(a) <= GLOBAL_ATTRIBUTES | TAG_ATTRIBUTES.get(tag, set()), "Unsupported HTML attribute on: " + tag)
        if "id" in a:
            require(a["id"] not in self.ids and a["id"], "Duplicate/empty HTML id")
            self.ids.add(a["id"])
        if "aria-labelledby" in a:
            self.aria_refs.extend(a["aria-labelledby"].split())
        if tag == "html":
            self.lang = a.get("lang")
        if tag == "h1":
            self.h1 += 1
        if tag in ("main", "header", "footer"):
            setattr(self, tag, getattr(self, tag) + 1)
        if tag == "title":
            require(not self.in_title and not self.title, "Duplicate title")
            self.in_title = True
        if tag == "meta":
            if "charset" in a:
                require(a == {"charset": "utf-8"}, "Unsupported charset metadata")
            elif "name" in a:
                require(set(a) == {"name", "content"} and a["name"] in {"viewport", "description"}, "Unsupported named metadata")
            else:
                require(set(a) == {"property", "content"} and a["property"] in {"og:type", "og:title", "og:description", "og:url", "og:site_name"}, "Unsupported property metadata")
            key = a.get("property", a.get("name"))
            if key:
                require(key not in self.meta, "Duplicate metadata")
                self.meta[key] = a.get("content", "")
        if tag == "link":
            self.links.append((a.get("rel"), a.get("href")))
        for key in ("href", "src"):
            if key in a:
                self.refs.append((tag, key, a[key]))
        if tag == "img":
            require(a.get("alt", "").strip(), "Image requires meaningful alt text")
            self.images.append(a)
        if a.get("aria-current") == "page":
            self.current.append(a.get("href"))

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, value):
        if self.in_title:
            self.title += value


def inventory(output):
    require(output.is_dir(), "Missing output directory")
    names = set()
    for item in output.rglob("*"):
        relative = item.relative_to(output).as_posix()
        safe_path(output, relative)
        if item.is_dir():
            require(relative == "assets", "Unexpected output directory: " + relative)
        else:
            require(item.is_file(), "Non-file output rejected")
            names.add(relative)
    return names


def render(data, pages, base):
    layout = Template(data["site/layout.html"].decode("utf-8"))
    artifact = {name: data[name] for name in ASSETS}
    artifact["styles.css"] = data["site/styles.css"]
    for page in pages:
        navigation = "".join('<li><a href="' + p["output"] + '"' + (' aria-current="page"' if p == page else '') + '>' + html.escape(p["nav"]) + '</a></li>' for p in pages)
        content = data["site/pages/" + page["source"]].decode("utf-8")
        artifact[page["output"]] = layout.substitute(
            lang=html.escape(page["lang"], quote=True), title=html.escape(page["title"], quote=True),
            description=html.escape(page["description"], quote=True), canonical=html.escape(base + page["output"], quote=True),
            navigation=navigation, content=content).encode("utf-8")
    artifact["sitemap.xml"] = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join("  <url><loc>" + html.escape(base + p["output"]) + "</loc></url>\n" for p in pages) + "</urlset>\n").encode("utf-8")
    artifact[".nojekyll"] = b""
    require(set(artifact) == FILES, "Rendered artifact differs from whitelist")
    return artifact


def validate_artifact(pages, base, expected):
    """Fully validate rendered bytes before deleting or writing any output."""
    require(set(expected) == FILES, "Artifact must match exact 13-file whitelist")
    documents = {}
    for name in FILES:
        actual = expected[name]
        if name in ASSETS:
            require(sha(actual) == ASSETS[name], "Output image checksum mismatch")
        else:
            scan_text(actual.decode("utf-8"), name)
    css = expected["styles.css"].decode("utf-8")
    # A narrow static CSS vocabulary avoids alternate/escaped resource channels.
    css_tokens = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    functions = {v.lower() for v in re.findall(r"([a-zA-Z-]+)\s*\(", css_tokens)}
    at_rules = {v.lower() for v in re.findall(r"@([a-zA-Z-]+)", css_tokens)}
    require("\\" not in css and functions <= {"var", "clamp", "repeat", "minmax", "counter", "media"} and at_rules <= {"media"}, "External or unvalidated CSS resource rejected")
    for page in pages:
        name = page["output"]
        parser = PageParser()
        parser.feed(expected[name].decode("utf-8"))
        parser.close()
        require(parser.h1 == 1 and parser.main == 1 and parser.header == 1 and parser.footer == 1, "Expected one H1 and semantic landmarks: " + name)
        require(parser.lang == page["lang"] and parser.title == page["title"], "Title/language mismatch: " + name)
        require(parser.meta.get("description") == page["description"], "Description mismatch")
        for key, value in {"og:title": page["title"], "og:description": page["description"], "og:url": base + name, "og:type": "website", "og:site_name": "General Agent Framework"}.items():
            require(parser.meta.get(key) == value, "Open Graph mismatch: " + key)
        require(parser.links == [("canonical", base + name), ("stylesheet", "styles.css")], "Canonical/CSS links mismatch")
        require(parser.current == [name], "Active navigation mismatch")
        require(all(ref in parser.ids for ref in parser.aria_refs), "Broken aria-labelledby")
        documents[name] = parser
    for name, parser in documents.items():
        for tag, key, target in parser.refs:
            require(target and not any(c.isspace() for c in target), "Empty or whitespace URL")
            url = urlsplit(target)
            if url.scheme:
                if tag == "link" and url.scheme == "https" and target == base + name:
                    continue
                require(tag == "a" and key == "href", "Remote assets are not permitted")
                if url.scheme == "mailto":
                    require(url.path == "pathetichomeless@outlook.com", "Unexpected contact mailbox")
                    continue
                require(url.scheme == "https" and url.netloc == "github.com" and not url.username and not url.password, "Non-public external URL")
                require(url.path == "/pathetichomeless-star/general-agent-framework" or url.path.startswith("/pathetichomeless-star/general-agent-framework/blob/main/"), "External link outside public repository")
                continue
            require(not url.netloc and not url.query and not target.startswith("/"), "Use project-safe relative URLs")
            relative = unquote(url.path) or name
            relative_parts(relative)
            require(relative in expected, "Broken or disallowed relative link: " + target)
            if url.fragment:
                require(relative in documents and unquote(url.fragment) in documents[relative].ids, "Broken local anchor: " + target)
        for image in parser.images:
            src = image["src"]
            require(src in ASSETS, "Image outside frozen whitelist")
            png = expected[src]
            require(png[:8] == b"\x89PNG\r\n\x1a\n", "Invalid PNG")
            width, height = struct.unpack(">II", png[16:24])
            require(image.get("width") == str(width) and image.get("height") == str(height), "Image dimensions mismatch")
    sitemap = ET.fromstring(expected["sitemap.xml"])
    require(sitemap.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset", "Invalid sitemap root")
    locations = [e.text for e in sitemap.findall("{*}url/{*}loc")]
    require(locations == [base + p["output"] for p in pages], "Sitemap URL mismatch")


def validate_output(output, expected):
    """Audit only the exact on-disk copies of the prevalidated artifact."""
    require(inventory(output) == FILES, "Output inventory must match exact 13-file whitelist")
    for name in FILES:
        require(safe_path(output, name).read_bytes() == expected[name], "Output differs from approved sources/build: " + name)


def run(base_url, validate_only=False):
    base = public_base(base_url)
    data, pages = load_sources()
    for name in INPUTS:
        if name not in ASSETS:
            scan_text(data[name].decode("utf-8"), name)
    artifact = render(data, pages, base)
    validate_artifact(pages, base, artifact)
    output = safe_path(ROOT, "_site")
    if not validate_only:
        if output.exists():
            previous = inventory(output)
            # A failed build may leave a safe subset of the authorized files.
            require(previous <= FILES, "Refusing to clean unexpected existing output")
            # Only the explicit files and one known directory may be removed.
            for name in previous:
                safe_path(output, name).unlink()
            if (output / "assets").exists():
                (output / "assets").rmdir()
            output.rmdir()
        output.mkdir()
        (output / "assets").mkdir()
        for name, content in artifact.items():
            safe_path(output, name).write_bytes(content)
    validate_output(output, artifact)
    print("VALIDATED: exact 13-file public artifact; six pages, local links/anchors, metadata and frozen images")
    print("base_url=" + base + " (local validation only; deployment not performed)")
    for name in sorted(FILES):
        print(sha(artifact[name]) + "  " + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Central public HTTPS project URL used only for generated metadata")
    parser.add_argument("--validate-only", action="store_true", help="Read-only audit of existing _site against sources, links and whitelist")
    args = parser.parse_args()
    try:
        run(args.base_url, args.validate_only)
    except (ValueError, OSError, KeyError, TypeError, ET.ParseError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
