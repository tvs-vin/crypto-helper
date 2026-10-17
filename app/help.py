"""The Help window: the wiki (`WIKI/`), read from the installed copy so it always matches the
version that's running.

Pages are known by id ("guides/notifications"), from a list built once from the folder; a
request names an id, never a path. Markdown is turned into a small structure of blocks and
inline pieces that the browser builds with element APIs, so nothing in a page is ever used as
HTML. Only the Markdown the wiki uses is understood: headings, paragraphs, lists (one level of
nesting, code inside items), tables, code blocks, quotes, bold, italics, code and links.
"""

import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


def _wiki_root() -> Path:
    """The checkout's WIKI/ when running from one; otherwise the copy installed with the
    package (pyproject `data-files`: <venv>/share/crypto-helper/wiki)."""
    here = Path(__file__).resolve().parent.parent / "WIKI"
    return here if here.is_dir() else Path(sys.prefix) / "share" / "crypto-helper" / "wiki"


WIKI = _wiki_root()
SECTIONS = {"guides": "Guides", "reference": "Reference", "project": "Project",
            "tools": "Tools"}  # fmt: skip
BASEURL = re.compile(r"\{\{\s*site\.baseurl\s*\}\}")
LIQUID = re.compile(r"\{\{.*?\}\}|\{%.*?%\}")
ID_RE = re.compile(r"^[a-z0-9-]+(?:/[a-z0-9-]+)?$")


@dataclass
class Page:
    id: str
    section: str  # "" for top-level pages (home, glossary)
    title: str
    blocks: list = field(default_factory=list)
    headings: list = field(default_factory=list)  # (id, text, level)
    text: str = ""  # plain text, for search


# ---- inline ----------------------------------------------------------------------------------

INLINE = re.compile(
    r"`(?P<code>[^`]+)`"
    r"|\[(?P<ltext>[^\]]+)\]\((?P<href>(?:[^()\s]|\([^()\s]*\))+)\)"
    r"|\*\*(?P<strong>.+?)\*\*"
    r"|(?<![\w*])\*(?P<em>[^*\s][^*]*?)\*(?![\w*])"
)


def link_target(href: str, page_id: str) -> dict | None:
    """{"page": id, "anchor": a} for a wiki link, {"url": u} for an outside one, None for
    anything else (shown as plain text)."""
    href = BASEURL.sub("", href).strip()
    if href.startswith(("https://", "http://")):
        return {"url": href}
    if href.startswith("#"):
        return {"page": page_id, "anchor": href[1:]}
    if href.startswith("/"):
        path, _, anchor = href[1:].partition("#")
        path = path.strip("/") or "index"
        return {"page": path, "anchor": anchor or None}
    return None


def inline(text: str, page_id: str) -> list:
    """Text → [[kind, text, extra?], ...] with kind text|strong|em|code|link."""
    text = BASEURL.sub("", text)
    out, pos = [], 0
    for m in INLINE.finditer(text):
        if m.start() > pos:
            out.append(["text", text[pos : m.start()]])
        if m["code"] is not None:
            out.append(["code", m["code"]])
        elif m["ltext"] is not None:
            target = link_target(m["href"], page_id)
            label = strip_marks(m["ltext"])
            out.append(["link", label, target] if target else ["text", label])
        elif m["strong"] is not None:
            out.append(["strong", strip_marks(m["strong"])])
        else:
            out.append(["em", m["em"]])
        pos = m.end()
    if pos < len(text):
        out.append(["text", text[pos:]])
    return out


def strip_marks(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text.replace("**", "").replace("`", "").replace("*", "")


def anchor_id(heading: str) -> str:
    """Like kramdown's automatic ids, so links written for GitHub Pages work here too."""
    s = re.sub(r"[^a-z0-9 -]", "", strip_marks(heading).lower()).replace(" ", "-")
    return re.sub(r"^[^a-z]+", "", s)


# ---- blocks ----------------------------------------------------------------------------------

LIST_ITEM = re.compile(r"^(?P<indent> *)(?P<mark>[-*]|\d+\.) (?P<text>.*)$")


def parse(markdown: str, page_id: str) -> Page:
    lines = markdown.splitlines()
    title = page_id
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), 0)
        for ln in lines[1:end]:
            if ln.startswith("title:"):
                title = ln[6:].strip().strip("\"'")
        lines = lines[end + 1 :]
    # Wiki links are written `{{ site.baseurl }}/guides/x`: without the prefix they're plain
    # absolute paths. Any other template tag is dropped.
    lines = [LIQUID.sub("", BASEURL.sub("", ln)) for ln in lines]
    page = Page(page_id, page_id.split("/")[0] if "/" in page_id else "", title)
    texts: list[str] = []
    i = 0
    para: list[str] = []

    def flush():
        if para:
            joined = " ".join(s.strip() for s in para)
            page.blocks.append({"t": "p", "text": inline(joined, page_id)})
            texts.append(strip_marks(joined))
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush()
            i += 1
            continue
        if stripped.startswith("```"):
            flush()
            code, i = _fence(lines, i)
            page.blocks.append(code)
            continue
        m = re.match(r"^(#{1,4}) (.*)$", line)
        if m:
            flush()
            level, text = len(m[1]), m[2].strip()
            hid = anchor_id(text)
            page.blocks.append({"t": "h", "level": level, "id": hid, "text": inline(text, page_id)})
            page.headings.append((hid, strip_marks(text), level))
            if level == 1 and page.title == page_id:
                page.title = strip_marks(text)
            texts.append(strip_marks(text))
            i += 1
            continue
        if stripped.startswith("|"):
            flush()
            table, i = _table(lines, i, page_id)
            page.blocks.append(table)
            texts += [strip_marks(" ".join(row)) for row in table.pop("_raw")]
            continue
        if stripped.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            joined = " ".join(quote)
            page.blocks.append({"t": "quote", "text": inline(joined, page_id)})
            texts.append(strip_marks(joined))
            continue
        if LIST_ITEM.match(line) and not line.startswith("  "):
            flush()
            block, i = _list(lines, i, page_id, texts)
            page.blocks.append(block)
            continue
        para.append(line)
        i += 1
    flush()
    page.text = " ".join(texts)
    return page


def _fence(lines: list[str], i: int) -> tuple[dict, int]:
    indent = len(lines[i]) - len(lines[i].lstrip())
    lang = lines[i].strip()[3:].strip()[:20]
    body = []
    i += 1
    while i < len(lines) and not lines[i].strip().startswith("```"):
        body.append(lines[i][indent:] if lines[i][:indent].strip() == "" else lines[i])
        i += 1
    return {"t": "code", "lang": lang, "text": "\n".join(body)}, i + 1


def _cells(line: str) -> list[str]:
    s = line.strip().strip("|")
    # A `|` inside code or escaped as \| belongs to the cell.
    parts, cur, in_code, j = [], "", False, 0
    while j < len(s):
        ch = s[j]
        if ch == "\\" and j + 1 < len(s) and s[j + 1] == "|":
            cur += "|"
            j += 2
            continue
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
        j += 1
    parts.append(cur.strip())
    return parts


def _table(lines: list[str], i: int, page_id: str) -> tuple[dict, int]:
    rows = []
    while i < len(lines) and lines[i].strip().startswith("|"):
        rows.append(_cells(lines[i]))
        i += 1
    head, body = rows[0], [r for r in rows[1:] if not all(re.fullmatch(r":?-+:?", c) for c in r)]
    return {
        "t": "table",
        "head": [inline(c, page_id) for c in head],
        "rows": [[inline(c, page_id) for c in r] for r in body],
        "_raw": [head, *body],
    }, i


def _list(lines: list[str], i: int, page_id: str, texts: list[str]) -> tuple[dict, int]:
    first = LIST_ITEM.match(lines[i])
    ordered = first["mark"][0].isdigit()
    items: list[dict] = []
    while i < len(lines):
        line = lines[i]
        m = LIST_ITEM.match(line)
        if m and not m["indent"]:
            if m["mark"][0].isdigit() != ordered:
                break
            items.append({"text": m["text"], "blocks": []})
            i += 1
            continue
        if not line.strip():
            # A blank line ends the list unless the next line carries on inside it.
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt.startswith(" ") and items:
                i += 1
                continue
            break
        if not line.startswith(" ") or not items:
            break
        item = items[-1]
        if line.strip().startswith("```"):
            code, i = _fence(lines, i)
            item["blocks"].append(code)
            continue
        sub = LIST_ITEM.match(line)
        if sub:
            last = item["blocks"][-1] if item["blocks"] else None
            nested = last if last is not None and last["t"] != "code" else None
            if nested is None:
                nested = {"t": "ol" if sub["mark"][0].isdigit() else "ul", "items": []}
                item["blocks"].append(nested)
            nested["items"].append({"text": sub["text"], "blocks": []})
        elif item["blocks"] and item["blocks"][-1]["t"] in ("ul", "ol"):
            item["blocks"][-1]["items"][-1]["text"] += " " + line.strip()
        else:
            item["text"] += " " + line.strip()
        i += 1

    def finish(entries):
        for e in entries:
            texts.append(strip_marks(e["text"]))
            e["text"] = inline(e["text"], page_id)
            for b in e["blocks"]:
                if b["t"] in ("ul", "ol"):
                    finish(b["items"])

    finish(items)
    return {"t": "ol" if ordered else "ul", "items": items}, i


# ---- the wiki --------------------------------------------------------------------------------


def _page_id(path: Path, root: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = rel.parts
    return parts[0] if len(parts) == 2 and parts[1] == "index" else "/".join(parts)


@lru_cache(maxsize=4)
def load(root: Path = WIKI) -> dict[str, Page]:
    """Every page, parsed once (the wiki only changes with an update, which restarts)."""
    pages: dict[str, Page] = {}
    if not root.is_dir():
        return pages
    for path in sorted(root.rglob("*.md")):
        if any(p.startswith(("_", ".")) for p in path.relative_to(root).parts):
            continue
        pid = _page_id(path, root)
        if ID_RE.match(pid):
            pages[pid] = parse(path.read_text(encoding="utf-8"), pid)
    return pages


def contents(pages: dict[str, Page]) -> list[dict]:
    """Sections in a fixed order; pages in the order their section's index lists them."""
    start = [{"id": p, "title": pages[p].title} for p in ("index", "glossary") if p in pages]
    out = [{"id": "", "title": "Start", "pages": start}]
    for sid, title in SECTIONS.items():
        index = pages.get(sid)
        listed = []
        if index is not None:
            for _, link in _links(index.blocks):
                pid = link.get("page")
                if pid and pid.startswith(sid + "/") and pid in pages and pid not in listed:
                    listed.append(pid)
        rest = sorted(p for p in pages if p.startswith(sid + "/") and p not in listed)
        entries = ([{"id": sid, "title": f"About {title.lower()}"}] if index else []) + [
            {"id": p, "title": pages[p].title} for p in listed + rest
        ]
        if entries:
            out.append({"id": sid, "title": title, "pages": entries})
    return out


def _links(blocks):
    """Every [label, target] link in some blocks, in reading order."""
    for b in blocks:
        pieces = []
        if b["t"] in ("p", "h", "quote"):
            pieces = [b["text"]]
        elif b["t"] == "table":
            pieces = b["head"] + [c for r in b["rows"] for c in r]
        elif b["t"] in ("ul", "ol"):
            for item in b["items"]:
                pieces.append(item["text"])
                yield from _links(item["blocks"])
        for piece in pieces:
            for part in piece:
                if part[0] == "link":
                    yield part[1], part[2]


SECTION_WEIGHT = {"guides": 4, "": 3, "reference": 2, "tools": 0, "project": -2}


def _snippet(text: str, at: int, before: int = 50, after: int = 110) -> str:
    """Some words around a match, cut at word boundaries."""
    if at < 0:
        return text[:after].rsplit(" ", 1)[0] + "…" if len(text) > after else text
    start = max(0, at - before)
    if start:
        start = text.find(" ", start) + 1 or start
    end = min(len(text), at + after)
    if end < len(text):
        end = text.rfind(" ", at, end) if text.rfind(" ", at, end) > at else end
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def search(pages: dict[str, Page], q: str, limit: int = 20) -> list[dict]:
    words = [w for w in re.findall(r"\w+", q.lower()) if len(w) > 1][:8]
    if not words:
        return []
    hits = []
    for p in pages.values():
        title, body = p.title.lower(), p.text.lower()
        heads = " ".join(h[1] for h in p.headings).lower()
        if not all(w in title or w in heads or w in body for w in words):
            continue
        score = sum(5 * (w in title) + 2 * (w in heads) + min(body.count(w), 5) for w in words)
        score += SECTION_WEIGHT.get(p.section, 0)  # how-tos before plans and history
        anchor = next((h[0] for h in p.headings if any(w in h[1].lower() for w in words)), None)
        snippet = _snippet(p.text, body.find(words[0]))
        hits.append({"id": p.id, "title": p.title, "anchor": anchor, "score": score,
                     "snippet": snippet})  # fmt: skip
    hits.sort(key=lambda h: (-h["score"], h["title"]))
    return hits[:limit]
