#!/usr/bin/env python3
"""Knowledge-galaxy indexer. Standard library only.

Scans every .md file under the notes folder plus Jarvis's memory captures (captures/, written by
"hatırla …" / POST /remember) and writes viewer/graph-data.js:

    const GRAPH = {nodes: [...], links: [...]};

Every node's numeric `id` equals its index in the nodes array, so
GRAPH.nodes[i].id === i always holds. The server relies on this too.

Usage:  python3 build.py [notes_dir]      (default: ./notes)
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_NOTES = os.path.join(ROOT, "notes")
# Env overrides exist for preflight.py, which runs against throwaway folders.
CAPTURES_DIR = os.environ.get("JARVIS_CAPTURES_DIR") or os.path.join(ROOT, "captures")
OUT_FILE = os.environ.get("JARVIS_GRAPH_OUT") or os.path.join(ROOT, "viewer", "graph-data.js")
CAPTURE_GROUP = "hafıza"
EXCERPT_LEN = 700

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")


def norm(s):
    return re.sub(r"\s+", " ", s.strip().lower())


def scan(notes_dir):
    """Return a list of notes sorted by path (stable order => stable ids)."""
    found = []
    for dirpath, dirnames, filenames in os.walk(notes_dir):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fn in sorted(filenames):
            if fn.lower().endswith(".md"):
                found.append(os.path.join(dirpath, fn))
    found.sort(key=lambda p: os.path.relpath(p, notes_dir).lower())

    notes = []
    for path in found:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        rel = os.path.relpath(path, notes_dir)
        parent = os.path.dirname(rel)
        notes.append({
            "label": os.path.splitext(os.path.basename(path))[0],
            "group": os.path.basename(parent) if parent else "notes",
            "path": rel.replace(os.sep, "/"),
            "text": text,
            "capture": False,
        })
    return notes


def capture_title(text, fallback):
    """First '# heading' of a capture, else its file name."""
    for ln in text.splitlines():
        if ln.startswith("# "):
            return ln[2:].strip() or fallback
    return fallback


def scan_captures(captures_dir=None):
    """Jarvis's memory notes: flat folder of .md files, sorted by name (names start with a timestamp)."""
    captures_dir = captures_dir or CAPTURES_DIR
    if not os.path.isdir(captures_dir):
        return []
    out = []
    for fn in sorted(os.listdir(captures_dir)):
        path = os.path.join(captures_dir, fn)
        if fn.startswith(".") or not fn.lower().endswith(".md") or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        out.append({"label": capture_title(text, os.path.splitext(fn)[0]), "group": CAPTURE_GROUP,
                    "path": "captures/" + fn, "file": fn, "text": text, "capture": True})
    return out


def plain(text, title):
    """Markdown -> readable plain text for excerpts."""
    lines = text.splitlines()
    # Drop a leading H1 that just repeats the title.
    if lines and lines[0].lstrip("# ").strip().lower() == title.lower():
        lines = lines[1:]
    out = []
    for ln in lines:
        s = ln.strip()
        if re.fullmatch(r"\|?[\s:\-|]+\|?", s) and "-" in s:
            continue  # table separator row
        s = re.sub(r"^#{1,6}\s*", "", s)
        if s.startswith("|"):
            s = " · ".join(c.strip() for c in s.strip("|").split("|") if c.strip())
        out.append(s)
    t = "\n".join(out)
    t = WIKILINK_RE.sub(lambda m: m.group(1).strip(), t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)   # [text](url)
    t = re.sub(r"(\*\*|__|`)", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t


def excerpt(text, title, limit=EXCERPT_LEN):
    t = plain(text, title)
    if len(t) <= limit:
        return t
    cut = t[:limit]
    sp = cut.rfind(" ")
    if sp > limit * 0.7:
        cut = cut[:sp]
    return cut.rstrip(" ,.;:-") + "…"


def build_links(notes):
    titles = {norm(n["label"]): i for i, n in enumerate(notes)}
    patterns = [
        (i, re.compile(r"(?<![\w])" + re.escape(n["label"].lower()) + r"(?![\w])"))
        for i, n in enumerate(notes)
    ]
    wikis = [{norm(w) for w in WIKILINK_RE.findall(n["text"])} for n in notes]

    links = {}  # (a, b) with a < b -> type

    def add(a, b, kind):
        if a == b:
            return
        key = (min(a, b), max(a, b))
        if links.get(key) != "mention":
            links[key] = kind

    # 1) One note mentions another's title (plain text or [[wikilink]]).
    for a, n in enumerate(notes):
        body = n["text"].lower()
        for b, pat in patterns:
            if a != b and pat.search(body):
                add(a, b, "mention")
        for w in wikis[a]:
            if w in titles:
                add(a, titles[w], "mention")

    # 2) Two notes share at least one [[wikilink]] target.
    for a in range(len(notes)):
        for b in range(a + 1, len(notes)):
            shared = wikis[a] & wikis[b]
            if shared:
                add(a, b, "shared")

    return [{"source": a, "target": b, "type": t} for (a, b), t in sorted(links.items())]


def build(notes_dir=DEFAULT_NOTES, out_file=None, write=True, captures_dir=None):
    """Build the graph from notes/ + captures/. Returns (graph, notes) where notes carry full text."""
    out_file = out_file or OUT_FILE
    notes = (scan(notes_dir) if os.path.isdir(notes_dir) else []) + scan_captures(captures_dir)
    links = build_links(notes)
    degree = [0] * len(notes)
    for l in links:
        degree[l["source"]] += 1
        degree[l["target"]] += 1

    nodes = []
    for i, n in enumerate(notes):
        nodes.append({
            "id": i,                      # == index in nodes array (required)
            "label": n["label"],
            "group": n["group"],
            "excerpt": excerpt(n["text"], n["label"]),
            "degree": degree[i],
            "path": n["path"],            # stable across rebuilds (ids are not): the galaxy syncs by path
        })
        if n["capture"]:
            nodes[-1]["capture"] = True
    graph = {"nodes": nodes, "links": links}
    assert all(node["id"] == idx for idx, node in enumerate(nodes))

    if write:
        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        tmp = out_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("// Generated by build.py — do not edit by hand.\n")
            f.write("const GRAPH = ")
            json.dump(graph, f, ensure_ascii=False, indent=1)
            f.write(";\n")
        os.replace(tmp, out_file)
    return graph, notes


def main():
    notes_dir = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_NOTES
    if not os.path.isdir(notes_dir):
        sys.exit(f"Notes folder not found: {notes_dir}")
    graph, _ = build(notes_dir)
    kinds = {}
    for l in graph["links"]:
        kinds[l["type"]] = kinds.get(l["type"], 0) + 1
    groups = sorted({n["group"] for n in graph["nodes"]})
    print(f"Indexed {len(graph['nodes'])} notes, {len(graph['links'])} links {kinds}")
    print(f"Groups: {', '.join(groups)}")
    print(f"Wrote {os.path.relpath(OUT_FILE, ROOT)}")


if __name__ == "__main__":
    main()
