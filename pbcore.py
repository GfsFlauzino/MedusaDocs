"""Núcleo dos playbooks: leitura e escrita de .md e .drawio, modelo de fluxo e modelos de criação.

Fonte da verdade continua sendo o par .md + .drawio de cada pasta PB-xx (o mesmo que vai ao Confluence).
O editor trabalha sobre dois modelos JSON:
  doc   = {title, byline, sections:[{title, blocks, subs:[{title, blocks}]}]}
  flow  = {subtitle, nodes:[{id, lane, x, y, w, h, type, lines, team?}], edges:[{id, from, to, label, type, exit, entry, wps}]}
"""
import hashlib, html, json, os, re, unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).parent
# MEDUSA_HOME: pasta de dados da instalação (playbooks, templates, banco, backups). No Docker é o volume /data.
HOME = Path(os.environ.get("MEDUSA_HOME") or HERE)
SRC = Path(os.environ.get("PB_SRC") or HOME / "playbooks")
MAPPINGS_FILE = Path(os.environ.get("PB_MAPPINGS") or HOME / "mappings.json")
ID_RE = re.compile(r"^PB-\d{2,3}$")

# ───────────────────────── catálogo do modelo visual ─────────────────────────
# Formas, cores e raias são as já usadas nos fluxogramas. O editor só oferece o que está aqui.

# Raias padrão. Cada fluxograma tem a própria lista (flow["lanes"]), editável: times centrais
# do cadastro (teams.json, category "central") + opcionalmente a raia "Times de apoio" (kind "support").
DEFAULT_LANES = [
    {"key": "n1", "label": "SOC N1", "team": "SOC N1", "color": "#1D62D1", "kind": "team"},
    {"key": "n2", "label": "SOC N2", "team": "SOC N2", "color": "#B25E09", "kind": "team"},
    {"key": "cs", "label": "CSIRT", "team": "CSIRT", "color": "#C0272D", "kind": "team"},
    {"key": "ap", "label": "Times de apoio", "team": None, "color": "#5B6673", "kind": "support"},
]
SUPPORT_LANE_LABEL = "Times de apoio"
LANE_KEY_RE = re.compile(r"^[a-z0-9_-]{1,24}$")
MAX_LANES = 12

def lanes_of(flow):
    return flow.get("lanes") or json.loads(json.dumps(DEFAULT_LANES))
LANE_X, LANE_Y0, LANE_GAP, LANE_START, LANE_MIN_W, LANE_MIN_H, LANE_PAD = -12, 60, 8, 28, 772, 84, 20

NODE_TYPES = {
    "start":     {"label": "Início",              "shape": "pill",    "fill": "#FFFFFF", "stroke": "#1D62D1", "sw": 2, "dashed": False, "w": 96,  "h": 48,
                  "style": "rounded=1;arcSize=50;fillColor=#FFFFFF;strokeColor=#1D62D1;strokeWidth=2;"},
    "action":    {"label": "Ação",                "shape": "rect",    "fill": "#FFFFFF", "stroke": "#4D4D4D", "sw": 1, "dashed": False, "w": 176, "h": 48,
                  "style": "rounded=1;arcSize=12;fillColor=#FFFFFF;strokeColor=#4D4D4D;"},
    "decision":  {"label": "Decisão",             "shape": "rhombus", "fill": "#FFFFFF", "stroke": "#4D4D4D", "sw": 1, "dashed": False, "w": 120, "h": 64,
                  "style": "rhombus;fillColor=#FFFFFF;strokeColor=#4D4D4D;"},
    "close":     {"label": "Encerramento",        "shape": "rect",    "fill": "#E6F4EA", "stroke": "#2E7D32", "sw": 1, "dashed": False, "w": 176, "h": 48,
                  "style": "rounded=1;arcSize=12;fillColor=#E6F4EA;strokeColor=#2E7D32;"},
    "neutral":   {"label": "Vínculo / descarte",  "shape": "rect",    "fill": "#EEEEEE", "stroke": "#9E9E9E", "sw": 1, "dashed": False, "w": 120, "h": 40,
                  "style": "rounded=1;arcSize=12;fillColor=#EEEEEE;strokeColor=#9E9E9E;"},
    "attention": {"label": "Ponto de atenção",    "shape": "rect",    "fill": "#FFF7E6", "stroke": "#B25E09", "sw": 2, "dashed": False, "w": 128, "h": 76,
                  "style": "rounded=1;arcSize=12;fillColor=#FFF7E6;strokeColor=#B25E09;strokeWidth=2;"},
    "crossref":  {"label": "Outro playbook",      "shape": "rect",    "fill": "#FFFFFF", "stroke": "#7A3E9D", "sw": 1, "dashed": True,  "w": 120, "h": 40,
                  "style": "rounded=1;arcSize=12;fillColor=#FFFFFF;strokeColor=#7A3E9D;dashed=1;"},
    "support":   {"label": "Time de apoio",       "shape": "rect",    "fill": "#FFFFFF", "stroke": "#5B6673", "sw": 1, "dashed": True,  "w": 64,  "h": 44, "fc": "#333333",
                  "style": "rounded=1;arcSize=12;fillColor=#FFFFFF;strokeColor=#5B6673;dashed=1;fontColor=#333333;"},
}
NODE_BASE = "whiteSpace=wrap;html=1;fontSize=11;fontFamily=Helvetica;"

EDGE_TYPES = {
    "flow":       {"label": "Fluxo",                         "color": "#4D4D4D", "dashed": False, "sw": 1},
    "handoff":    {"label": "Handoff ao N2",                 "color": "#B25E09", "dashed": True,  "sw": 1},
    "escalation": {"label": "Escalonamento ao CSIRT",        "color": "#C0272D", "dashed": True,  "sw": 1.5},
    "crossref":   {"label": "Referência a outro playbook",   "color": "#7A3E9D", "dashed": True,  "sw": 1},
    "support":    {"label": "Acionamento de apoio (CSIRT)",  "color": "#5B6673", "dashed": True,  "sw": 1},
}
EDGE_BASE = ("edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;endSize=6;"
             "fontSize=11;fontColor=#555555;labelBackgroundColor=#FFFFFF;")

MITRE = json.loads((HERE / "mitre.json").read_text("utf-8")) if (HERE / "mitre.json").exists() else {"tactics": []}

CATALOG = {"mitre": MITRE, "defaultLanes": DEFAULT_LANES, "nodeTypes": NODE_TYPES, "edgeTypes": EDGE_TYPES, "supportLaneLabel": SUPPORT_LANE_LABEL,
           "layout": {"x": LANE_X, "y0": LANE_Y0, "gap": LANE_GAP, "start": LANE_START, "minW": LANE_MIN_W, "minH": LANE_MIN_H, "pad": LANE_PAD}}

# ───────────────────────── markdown ⇄ doc ─────────────────────────

def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", s)
    return s

def split_row(line):
    s = line.strip()
    if s.startswith("|"): s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"): s = s[:-1]
    cells = re.split(r"(?<!\\)\|", s)
    return [c.strip().replace("\\|", "|") for c in cells]

def cell_md(c):
    return c.replace("|", "\\|").replace("\n", " ").strip()

def parse_blocks(lines):
    blocks, i = [], 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
        elif ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(split_row(lines[i])); i += 1
            blocks.append({"t": "table", "head": rows[0], "rows": rows[2:]})
        elif ln.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(lines[i][2:]); i += 1
            blocks.append({"t": "ul", "items": items})
        elif ln.startswith(">"):
            q = []
            while i < len(lines) and lines[i].startswith(">"):
                q.append(lines[i].lstrip(">").strip()); i += 1
            blocks.append({"t": "quote", "text": " ".join(q)})
        else:
            p = []
            while i < len(lines) and lines[i].strip() and not lines[i].startswith(("|", "- ", ">")):
                p.append(lines[i]); i += 1
            blocks.append({"t": "p", "text": " ".join(p)})
    return blocks

def parse_md(text):
    lines = text.replace("\r\n", "\n").split("\n")
    title = lines[0].lstrip("# ").strip()
    byline, sections, cur, sub = "", [], None, None
    for ln in lines[1:]:
        if ln.startswith("## "):
            cur = {"title": ln[3:].strip(), "lines": [], "subs": []}; sections.append(cur); sub = None
        elif ln.startswith("### ") and cur is not None:
            sub = {"title": ln[4:].strip(), "lines": []}; cur["subs"].append(sub)
        elif cur is not None:
            (sub if sub is not None else cur)["lines"].append(ln)
        elif ln.strip() and not byline:
            byline = ln.strip()
    for s in sections:
        s["blocks"] = parse_blocks(s.pop("lines"))
        for x in s["subs"]:
            x["blocks"] = parse_blocks(x.pop("lines"))
    return {"title": title, "byline": byline, "sections": sections}

def blocks_md(blocks):
    out = []
    for b in blocks:
        t = b.get("t")
        if t == "p" and b.get("text", "").strip():
            out.append(b["text"].strip())
        elif t == "quote" and b.get("text", "").strip():
            out.append("> " + b["text"].strip())
        elif t == "ul":
            items = [i for i in b.get("items", []) if i.strip()]
            if items: out.append("\n".join("- " + i.strip() for i in items))
        elif t == "table":
            head = b.get("head") or []
            if not head: continue
            n = len(head)
            rows = [(r + [""] * n)[:n] for r in b.get("rows", [])]
            lines = ["| " + " | ".join(cell_md(c) for c in head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
            lines += ["| " + " | ".join(cell_md(c) for c in r) + " |" for r in rows]
            out.append("\n".join(lines))
    return out

def doc_to_md(doc):
    out = [f"# {doc['title'].strip()}", ""]
    if doc.get("byline", "").strip():
        out += [doc["byline"].strip(), ""]
    for s in doc["sections"]:
        out += [f"## {s['title'].strip()}", ""]
        for b in blocks_md(s.get("blocks", [])): out += [b, ""]
        for x in s.get("subs", []):
            out += [f"### {x['title'].strip()}", ""]
            for b in blocks_md(x.get("blocks", [])): out += [b, ""]
    return "\n".join(out).rstrip() + "\n"

def render_blocks(blocks):
    out = []
    for b in blocks:
        if b["t"] == "p":
            out.append(f"<p>{inline(b['text'])}</p>")
        elif b["t"] == "quote":
            out.append(f"<blockquote>{inline(b['text'])}</blockquote>")
        elif b["t"] == "ul":
            lis = []
            for it in b["items"]:
                m = re.match(r"\[( |x)\] (.*)", it)
                if m:
                    lis.append(f"<li class='chk {'done' if m.group(1) == 'x' else 'open'}'>{inline(m.group(2))}</li>")
                else:
                    lis.append(f"<li>{inline(it)}</li>")
            out.append("<ul>" + "".join(lis) + "</ul>")
        elif b["t"] == "table":
            th = "".join(f"<th>{inline(c)}</th>" for c in b["head"])
            trs = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in b["rows"])
            out.append(f"<div class='tw'><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>")
    return "\n".join(out)

def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w\s-]", "", s.lower())
    return re.sub(r"[\s_]+", "-", s.strip())[:60]

# ───────────────────────── drawio ⇄ flow ─────────────────────────

def style_dict(s):
    d = {}
    for part in (s or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1); d[k] = v
        elif part:
            d[part] = True
    return d

def label_to_lines(v):
    lines = []
    for seg in re.split(r"<br\s*/?>", v or "", flags=re.I):
        s = "n"
        if re.fullmatch(r"\s*<b>.*</b>\s*", seg, re.S): s = "b"
        elif re.fullmatch(r"\s*<font[^>]*>.*</font>\s*", seg, re.S): s = "m"
        text = html.unescape(re.sub(r"<[^>]+>", "", seg)).strip()
        if text: lines.append({"t": text, "s": s})
    return lines

def lines_to_label(lines):
    parts = []
    for ln in lines:
        t = html.escape(ln.get("t", "").strip(), quote=False)
        if not t: continue
        s = ln.get("s", "n")
        parts.append(f"<b>{t}</b>" if s == "b" else f"<font color='#666666'>{t}</font>" if s == "m" else t)
    return "<br>".join(parts)

def infer_type(st):
    if st.get("arcSize") == "50": return "start"
    if "rhombus" in st: return "decision"
    fill, stroke = st.get("fillColor", "").upper(), st.get("strokeColor", "").upper()
    if fill == "#EEEEEE": return "neutral"
    if fill == "#E6F4EA": return "close"
    if fill == "#FFF7E6": return "attention"
    if stroke == "#7A3E9D": return "crossref"
    if stroke == "#5B6673": return "support"
    return "action"

def infer_edge(st):
    c = st.get("strokeColor", "").upper()
    for k, v in EDGE_TYPES.items():
        if v["color"].upper() == c: return k
    return "flow"

def infer_team(lines):
    text = " ".join(l["t"] for l in lines)
    for k in sorted(load_teams(), key=len, reverse=True):
        if re.search(rf"(?<![\w/]){re.escape(k)}(?![\w/])", text): return k
    return None

def lane_from_cell(cid, label, color, used):
    """Raia lida do .drawio: chave estável a partir do id (lane-n1 → n1) ou do nome."""
    key = cid[5:] if cid.startswith("lane-") else slug(label)[:24] or "raia"
    key = re.sub(r"[^a-z0-9_-]", "", key.lower())[:24] or "raia"
    base, i = key, 2
    while key in used: key = f"{base[:20]}{i}"; i += 1
    support = slug(label).startswith(("times-de-apoio", "apoio"))
    return {"key": key, "label": label, "team": None if support else label, "color": color, "kind": "support" if support else "team"}

def drawio_to_flow(path):
    root = ET.parse(path).getroot()
    diagram = list(root)[0]
    allc = list(diagram.iter("mxCell"))
    verts = {c.get("id"): c for c in allc if not c.get("edge")}
    lanes_abs, subtitle, lanes = {}, "", []
    for cid, c in sorted(verts.items(), key=lambda kv: float((kv[1].find("mxGeometry").get("y", 0) if kv[1].find("mxGeometry") is not None else 0))):
        st = style_dict(c.get("style"))
        g = c.find("mxGeometry")
        if "swimlane" in st and g is not None:
            lane = lane_from_cell(cid, html.unescape(re.sub("<[^>]+>", "", c.get("value") or "")).strip(), st.get("fillColor", "#5B6673"),
                                  {l["key"] for l in lanes})
            lanes.append(lane)
            lanes_abs[cid] = (lane["key"], float(g.get("x", 0)), float(g.get("y", 0)), float(g.get("height", 0)))
        if cid == "title":
            subtitle = html.unescape(re.sub("<[^>]+>", "", (c.get("value") or "").split("—", 1)[-1])).strip() if "—" in (c.get("value") or "") else ""
    nodes = []
    for cid, c in verts.items():
        st = style_dict(c.get("style"))
        g = c.find("mxGeometry")
        if g is None or not c.get("vertex") or "swimlane" in st or cid == "title" or c.get("parent") not in lanes_abs:
            continue
        lines = label_to_lines(c.get("value"))
        t = infer_type(st)
        n = {"id": cid, "lane": lanes_abs[c.get("parent")][0], "x": float(g.get("x", 0)), "y": float(g.get("y", 0)),
             "w": float(g.get("width", 120)), "h": float(g.get("height", 48)), "type": t, "lines": lines}
        if t == "support": n["team"] = infer_team(lines)
        nodes.append(n)
    ids = {n["id"] for n in nodes}
    lane_rows = sorted(lanes_abs.values(), key=lambda r: r[2])
    def rel_wp(x, y):
        for k, lx, ly, lh in lane_rows:
            if ly <= y <= ly + lh + LANE_GAP: return {"lane": k, "x": x - lx, "y": y - ly}
        k, lx, ly, lh = lane_rows[-1] if y > lane_rows[-1][2] else lane_rows[0]
        return {"lane": k, "x": x - lx, "y": y - ly}
    edges = []
    for c in allc:
        if not c.get("edge") or c.get("source") not in ids or c.get("target") not in ids:
            continue
        st = style_dict(c.get("style"))
        eid = c.get("id")
        if eid in ids: eid = "x-" + eid   # o .drawio do PB-03 tinha caixa e seta com o mesmo id
        def side(px, py):
            return {"x": float(st[px]), "y": float(st[py])} if px in st and py in st else None
        g = c.find("mxGeometry")
        arr = g.find("Array") if g is not None else None
        wps = [rel_wp(float(p.get("x")), float(p.get("y"))) for p in arr.iter("mxPoint")] if arr is not None else []
        e = {"id": eid, "from": c.get("source"), "to": c.get("target"), "label": html.unescape(c.get("value") or ""),
             "type": infer_edge(st), "exit": side("exitX", "exitY"), "entry": side("entryX", "entryY"), "wps": wps}
        off = g.find("mxPoint[@as='offset']") if g is not None else None
        if e["label"] and off is not None:
            e["_off"] = (float(off.get("x", 0)), float(off.get("y", 0)), float(g.get("x", 0) or 0))
        edges.append(e)
    flow = {"subtitle": subtitle, "lanes": lanes or lanes_of({}), "nodes": nodes, "edges": edges}
    # rótulo movido no editor: o .drawio guarda o deslocamento a partir do meio da seta; aqui volta a ser
    # deslocamento a partir da posição automática (a mesma do flow.js)
    if any("_off" in e for e in edges):
        lanes_l, absn = layout(flow)
        for e in edges:
            if "_off" not in e: continue
            ox, oy, gx = e.pop("_off")
            pts = edge_points(e, lanes_l, absn)
            if not pts: continue
            mx, my = point_at(pts, (gx + 1) / 2)
            ax, ay = label_auto(e, pts)
            e["lp"] = {"dx": round(mx + ox - ax, 1), "dy": round(my + oy - ay, 1)}
    return flow

# layout (mesmo algoritmo do flow.js; usado ao gravar o .drawio)

def layout(flow):
    lanes, y = {}, LANE_Y0
    width = max([LANE_MIN_W] + [n["x"] + n["w"] + LANE_PAD for n in flow["nodes"]])
    for l in lanes_of(flow):
        ns = [n for n in flow["nodes"] if n["lane"] == l["key"]]
        h = max([LANE_MIN_H] + [n["y"] + n["h"] + LANE_PAD for n in ns])
        lanes[l["key"]] = {"x": LANE_X, "y": y, "w": width, "h": h}
        y += h + LANE_GAP
    absn = {}
    for n in flow["nodes"]:
        L = lanes[n["lane"]]
        absn[n["id"]] = (L["x"] + n["x"], L["y"] + n["y"], n["w"], n["h"])
    return lanes, absn

def auto_sides(s, t):
    sx, sy, sw, sh = s; tx, ty, tw, th = t
    if ty >= sy + sh + 8: return {"x": .5, "y": 1}, {"x": .5, "y": 0}
    if ty + th <= sy - 8: return {"x": .5, "y": 0}, {"x": .5, "y": 1}
    if tx + tw / 2 >= sx + sw / 2: return {"x": 1, "y": .5}, {"x": 0, "y": .5}
    return {"x": 0, "y": .5}, {"x": 1, "y": .5}

def _dir(p):
    return "h" if p["x"] in (0, 1) and p["y"] not in (0, 1) else "v"

def route(start, sdir, wps, end, edir):
    """Rota ortogonal da seta (mesmo algoritmo do flow.js)."""
    path, cur, d = [start], start, sdir
    for t, ed in [(p, None) for p in wps] + [(end, edir)]:
        if cur[0] != t[0] and cur[1] != t[1]:
            if ed is not None and ed == d:
                if d == "v": my = (cur[1] + t[1]) / 2; path += [(cur[0], my), (t[0], my)]
                else: mx = (cur[0] + t[0]) / 2; path += [(mx, cur[1]), (mx, t[1])]
            else:
                path.append((cur[0], t[1]) if d == "v" else (t[0], cur[1]))
        path.append(t)
        a, b = path[-2], path[-1]
        if a != b: d = "h" if a[1] == b[1] else "v"
        cur = t
    return [p for i, p in enumerate(path) if i == 0 or p != path[i - 1]]

def edge_points(e, lanes, absn):
    if e["from"] not in absn or e["to"] not in absn: return None
    s, t = absn[e["from"]], absn[e["to"]]
    ax, an = auto_sides(s, t)
    ex, en = e.get("exit") or ax, e.get("entry") or an
    wps = [(lanes[w["lane"]]["x"] + w["x"], lanes[w["lane"]]["y"] + w["y"]) for w in e.get("wps", []) if w.get("lane") in lanes]
    start = (s[0] + s[2] * ex["x"], s[1] + s[3] * ex["y"]); end = (t[0] + t[2] * en["x"], t[1] + t[3] * en["y"])
    return route(start, _dir(ex), wps, end, _dir(en))

def point_at(pts, frac):
    segs = [(a, b, abs(a[0] - b[0]) + abs(a[1] - b[1])) for a, b in zip(pts, pts[1:])]
    goal = sum(s[2] for s in segs) * max(0.0, min(1.0, frac))
    for a, b, ln in segs:
        if goal <= ln and ln:
            k = goal / ln
            return a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k
        goal -= ln
    return pts[-1]

def label_auto(e, pts):
    """Posição automática do rótulo (mesma regra do flow.js: rótulo curto perto da saída)."""
    if len(e.get("label") or "") <= 8 and len(pts) > 1:
        (a0, a1), (b0, b1) = pts[0], pts[1]
        dx = (b0 > a0) - (b0 < a0); dy = (b1 > a1) - (b1 < a1)
        return a0 + dx * 18 + (12 if dy else 0), a1 + dy * 16 - (7 if dx else 0)
    best, bi = -1, 0
    for i in range(len(pts) - 1):
        ln = abs(pts[i][0] - pts[i + 1][0]) + abs(pts[i][1] - pts[i + 1][1])
        if ln > best: best, bi = ln, i
    return (pts[bi][0] + pts[bi + 1][0]) / 2, (pts[bi][1] + pts[bi + 1][1]) / 2

def fmt(v):
    v = round(float(v), 2)
    return str(int(v)) if v == int(v) else str(v)

def flow_to_drawio(flow, pid, name, original=None):
    lanes, absn = layout(flow)
    total_h = max(L["y"] + L["h"] for L in lanes.values()) + 30
    width = next(iter(lanes.values()))["w"]
    model = ET.Element("mxGraphModel", {"dx": "1200", "dy": "900", "grid": "1", "gridSize": "8", "guides": "1", "tooltips": "1",
                                        "connect": "1", "arrows": "1", "fold": "1", "page": "1", "pageScale": "1",
                                        "pageWidth": fmt(width + 28), "pageHeight": fmt(total_h), "math": "0", "shadow": "0"})
    root = ET.SubElement(model, "root")
    def cell(attrs, geo=None, points=None, offset=None):
        c = ET.SubElement(root, "mxCell", attrs); c.tail = "\n"
        if geo is not None:
            g = ET.SubElement(c, "mxGeometry", {**geo, "as": "geometry"})
            if points:
                arr = ET.SubElement(g, "Array", {"as": "points"})
                for x, y in points: ET.SubElement(arr, "mxPoint", {"x": fmt(x), "y": fmt(y)})
            if offset:
                ET.SubElement(g, "mxPoint", {"x": fmt(offset[0]), "y": fmt(offset[1]), "as": "offset"})
        return c
    cell({"id": "0"}); cell({"id": "1", "parent": "0"})
    sub = flow.get("subtitle", "").strip()
    cell({"id": "title", "value": f"<b>{html.escape(pid)} · {html.escape(name)}</b>" + (f" — {html.escape(sub)}" if sub else ""),
          "style": "text;html=1;fontSize=15;align=left;verticalAlign=middle;", "vertex": "1", "parent": "1"},
         {"x": fmt(LANE_X), "y": "12", "width": fmt(width), "height": "36"})
    for l in lanes_of(flow):
        L = lanes[l["key"]]
        cell({"id": "lane-" + l["key"], "value": html.escape(l["label"]),
              "style": f"swimlane;horizontal=0;startSize={LANE_START};html=1;fontStyle=1;fontSize=13;fillColor={l['color']};strokeColor={l['color']};"
                       "fontColor=#FFFFFF;swimlaneFillColor=#FFFFFF;collapsible=0;rounded=1;arcSize=2;", "vertex": "1", "parent": "1"},
             {"x": fmt(L["x"]), "y": fmt(L["y"]), "width": fmt(L["w"]), "height": fmt(L["h"])})
    for n in flow["nodes"]:
        t = NODE_TYPES.get(n["type"], NODE_TYPES["action"])
        cell({"id": n["id"], "value": lines_to_label(n.get("lines", [])), "style": NODE_BASE + t["style"], "vertex": "1",
              "parent": "lane-" + n["lane"]},
             {"x": fmt(n["x"]), "y": fmt(n["y"]), "width": fmt(n["w"]), "height": fmt(n["h"])})
    for e in flow["edges"]:
        if e["from"] not in absn or e["to"] not in absn: continue
        ex, en = e.get("exit"), e.get("entry")
        ax, an = auto_sides(absn[e["from"]], absn[e["to"]])
        ex, en = ex or ax, en or an
        et = EDGE_TYPES.get(e.get("type"), EDGE_TYPES["flow"])
        style = EDGE_BASE + f"strokeColor={et['color']};" + ("dashed=1;" if et["dashed"] else "") + (f"strokeWidth={et['sw']};" if et["sw"] != 1 else "")
        style += f"exitX={fmt(ex['x'])};exitY={fmt(ex['y'])};exitDx=0;exitDy=0;entryX={fmt(en['x'])};entryY={fmt(en['y'])};entryDx=0;entryDy=0;"
        pts = [(lanes[w["lane"]]["x"] + w["x"], lanes[w["lane"]]["y"] + w["y"]) for w in e.get("wps", []) if w.get("lane") in lanes]
        offset, lp = None, e.get("lp")
        if e.get("label") and lp and (lp.get("dx") or lp.get("dy")):
            path = edge_points(e, lanes, absn)
            ax, ay = label_auto(e, path); mx, my = point_at(path, .5)
            offset = (ax + float(lp["dx"]) - mx, ay + float(lp["dy"]) - my)
        cell({"id": e["id"], "value": e.get("label", ""), "style": style, "edge": "1", "parent": "1",
              "source": e["from"], "target": e["to"]}, {"relative": "1"}, pts, offset)
    if original and Path(original).exists():
        mx = ET.parse(original).getroot()
    else:
        mx = ET.Element("mxfile", {"host": "app.diagrams.net", "type": "device", "compressed": "false"})
    diagrams = list(mx)
    first = diagrams[0] if diagrams else ET.SubElement(mx, "diagram")
    first.attrib.update({"id": f"{pid.lower().replace('-', '')}-fluxo", "name": f"1 · Fluxo {pid}"})
    for ch in list(first): first.remove(ch)
    first.text = None
    first.append(model)
    for d in mx: d.tail = "\n"
    mx.text = "\n"
    return ET.tostring(mx, encoding="unicode")

# ───────────────────────── governança (status, aprovação, revisão) ─────────────────────────
# Ficam na tabela "Propriedades do playbook" do .md (vão junto para o Confluence),
# mas só o servidor altera: o editor de documento os mostra bloqueados.

STATUSES = ["Desenvolvimento", "Homologação", "Produção"]
GOV_KEYS = {"status": "Status", "approver": "Aprovador", "reviewer": "Último revisor", "reviewed": "Data de revisão"}

def _norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().strip().lower()

def norm_status(s):
    for st in STATUSES:
        if _norm(s) == _norm(st): return st
    return STATUSES[0]

def props_table(doc):
    for sec in doc.get("sections", []):
        if sec["title"].startswith("Propriedades"):
            for b in sec["blocks"]:
                if b["t"] == "table" and len(b.get("head", [])) >= 2: return b
            b = {"t": "table", "head": ["Campo", "Valor"], "rows": []}
            sec["blocks"].append(b); return b
    sec = {"title": "Propriedades do playbook", "blocks": [{"t": "table", "head": ["Campo", "Valor"], "rows": []}], "subs": []}
    doc.setdefault("sections", []).insert(0, sec)
    return sec["blocks"][0]

def get_gov(doc):
    t = props_table(clone_doc(doc))
    rows = {_norm(r[0]): (r[1] if len(r) > 1 else "") for r in t["rows"] if r}
    g = {k: rows.get(_norm(label), "").strip() for k, label in GOV_KEYS.items()}
    g["status"] = norm_status(g["status"])
    return g

def set_gov(doc, gov):
    t = props_table(doc)
    labels = {_norm(v): k for k, v in GOV_KEYS.items()}
    t["rows"] = [r for r in t["rows"] if not r or _norm(r[0]) not in labels]
    pos = next((i + 1 for i, r in enumerate(t["rows"]) if r and _norm(r[0]) == "versao"), min(3, len(t["rows"])))
    new = [[GOV_KEYS[k], gov.get(k, "") or ""] + [""] * (len(t["head"]) - 2) for k in GOV_KEYS]
    t["rows"][pos:pos] = new
    return doc

def clone_doc(doc):
    return json.loads(json.dumps(doc))

# ───────────────────────── visão para o leitor ─────────────────────────

EXTRA_ALIASES = {"SOC N1": [r"\bN1\b"], "SOC N2": [r"\bN2\b"]}

def team_patterns(teams):
    return {t: [rf"(?<![\w/]){re.escape(t)}(?![\w/])"] + EXTRA_ALIASES.get(t, []) for t in teams}

def plain(s): return re.sub(r"[*`]", "", s)

def team_of_phase(title):
    m = re.search(r"—\s*(.+?)\s*$", title)
    return m.group(1) if m else "CSIRT"

def build_view(pid, folder, doc, flow, refs, teams=None):
    props, steps, ramos, states, snippets, closing, secs = {}, [], [], [], [], {}, []
    for sec in doc["sections"]:
        blocks = sec["blocks"]
        if sec["title"].startswith("Propriedades"):
            for b in blocks:
                if b["t"] == "table": props = {r[0]: (r[1] if len(r) > 1 else "") for r in b["rows"]}
        subs = []
        for sub in sec["subs"]:
            shtml = render_blocks(sub["blocks"])
            subs.append({"id": slug(sub["title"]), "title": sub["title"], "html": shtml})
            if re.match(r"R\d+\s*·", sub["title"]):
                ramos.append({"id": sub["title"].split()[0], "title": sub["title"], "html": shtml,
                              "short": sub["title"].split("·", 1)[1].strip()})
            for b in sub["blocks"]:
                if b["t"] == "table" and b["head"][:1] == ["ID"] and len(b["head"]) >= 3:
                    for r in b["rows"]:
                        r = (r + ["", "", ""])[:3]
                        if r[0]: steps.append({"id": r[0], "action": r[1], "exit": r[2], "phase": sub["title"], "team": team_of_phase(sub["title"])})
        if sec["title"].startswith("Tabela de decisão"):
            for b in blocks:
                if b["t"] == "table":
                    for r in b["rows"]:
                        m = re.match(r"(E\d)\s+(.*)", r[0])
                        if m:
                            r = (r + ["", "", "", ""])[:4]
                            states.append({"id": m.group(1), "name": m.group(2), "def": r[1], "dest": r[2], "prio": r[3]})
        if sec["title"].startswith("Critérios de encerramento"):
            for b in blocks:
                if b["t"] == "table":
                    for r in b["rows"]:
                        r = (r + ["", "", ""])[:3]; closing[r[0]] = {"closes": r[1], "never": r[2]}
        if not sec["title"].startswith(("Propriedades", "Itens em aberto", "Fluxograma")):
            for ttl, bl in [(sec["title"], blocks)] + [(s["title"], s["blocks"]) for s in sec["subs"]]:
                for b in bl:
                    if b["t"] == "ul": snippets += [(sec["title"], plain(i)) for i in b["items"]]
                    elif b["t"] == "table": snippets += [(ttl, plain(" — ".join(r))) for r in b["rows"]]
                    elif b["t"] in ("p", "quote"): snippets.append((sec["title"], plain(b["text"])))
        secs.append({"id": slug(sec["title"]), "title": sec["title"], "html": render_blocks(blocks), "subs": subs})
    mentions = {}
    for team, pats in team_patterns(teams if teams is not None else load_teams()).items():
        seen, lst = set(), []
        for s, t in snippets:
            if any(re.search(p, t) for p in pats) and t not in seen:
                seen.add(t); lst.append({"section": s, "text": t if len(t) < 420 else t[:417] + "…"})
        mentions[team] = lst
    name = doc["title"].split("—", 1)[-1].strip()
    return {"id": pid, "slug": pid.lower(), "folder": folder, "name": name, "title": doc["title"], "byline": plain(doc.get("byline", "")),
            "props": props, "sections": secs, "steps": steps, "ramos": ramos, "states": states, "closing": closing,
            "mentions": mentions, "flow": flow, "refs": refs, "doc": doc, "gov": get_gov(doc)}

# ───────────────────────── arquivos ─────────────────────────

def read_json(p, default):
    try: return json.loads(Path(p).read_text("utf-8"))
    except FileNotFoundError: return default

def folder_of(pid):
    for f in sorted(SRC.glob(f"{pid}-*")):
        if f.is_dir(): return f
    return None

def files_of(folder):
    md = next(iter(sorted(folder.glob("*.md"))), None)
    dio = next(iter(sorted(folder.glob("*.drawio"))), None)
    return md, dio

def load_playbook(folder, teams=None):
    pid = re.match(r"(PB-\d+)", folder.name).group(1)
    md, dio = files_of(folder)
    doc = parse_md(md.read_text("utf-8"))
    flow = drawio_to_flow(dio) if dio else {"subtitle": "", "lanes": lanes_of({}), "nodes": [], "edges": []}
    refs = read_json(MAPPINGS_FILE, {}).get(pid, {})
    view = build_view(pid, folder.name, doc, flow, refs, teams)
    view["rev"] = revision(folder, refs)
    return view

def revision(folder, refs=None):
    """Impressão digital do conteúdo atual: detecta gravação concorrente (dois editores no mesmo playbook)."""
    md, dio = files_of(folder)
    h = hashlib.sha1()
    for f in (md, dio):
        if f and f.exists(): h.update(f.read_bytes())
    if refs is None: refs = read_json(MAPPINGS_FILE, {}).get(re.match(r"(PB-\d+)", folder.name).group(1), {})
    h.update(json.dumps(refs, sort_keys=True).encode())
    return h.hexdigest()[:16]

def all_folders():
    return [f for f in sorted(SRC.glob("PB-*")) if f.is_dir() and files_of(f)[0]]

# Times e tags pertencem aos templates (templates.py registra o provedor). Aqui fica a união de todos,
# usada onde não há um template definido (reconhecer nomes de times em textos e caixas de apoio).
_teams_provider = None

def set_teams_provider(fn):
    global _teams_provider
    _teams_provider = fn

def load_teams():
    teams = _teams_provider() if _teams_provider else {}
    for name, t in teams.items():
        t.setdefault("category", "central" if name in ("SOC N1", "SOC N2", "CSIRT") else "apoio")
    return teams

def load_all():
    teams = load_teams()
    return {"playbooks": [load_playbook(f, teams) for f in all_folders()], "teams": teams, "catalog": CATALOG,
            "statuses": STATUSES}
