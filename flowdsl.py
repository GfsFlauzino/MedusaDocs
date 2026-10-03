"""Medusa Flow: o fluxograma escrito em Mermaid (flowchart), com anotações em comentário.

Por que Mermaid: é uma linguagem conhecida, que GitHub, GitLab, Confluence (macro Mermaid), Notion e o
próprio mermaid.live desenham sozinhos. As informações que o Mermaid não tem (tipo de caixa do modelo,
vínculo com passos, posição) vão em classes (:::close) e em comentários %% @..., que o Mermaid ignora.

Regras da linguagem
  flowchart TB
  subgraph n1["SOC N1"]            → raia (time central); "Times de apoio" vira a raia de apoio
    alerta(["Alerta"])            → Início (formato estádio)
    dedup{"Caso aberto?"}         → Decisão (losango)
    enriq["<b>Enriquecer</b><br><small>reputação · ASN</small>"]   → Ação; <b> negrito, <small> cinza
    fim["Encerrar no N1"]:::close → classes: close, neutral, attention, crossref, support
  end
  alerta --> dedup                → seta de fluxo
  dedup -->|sim| vinc             → seta com rótulo
  hand -.->|handoff| corr         → tracejada: handoff, apoio ou referência (deduzido pelas raias)
  contn2 ==> conf                 → escalonamento ao CSIRT
  %% @refs alerta T0, T1          → ao clicar na caixa, o analista lê esses passos/ramos/seções
  %% @pos alerta 68 34 96 48      → posição (x y largura altura) dentro da raia; sem ela, layout automático
  %% @route e9 0.5,1 0.5,0 n1:80,350 n1:380,350   → lados de saída/entrada e pontos de dobra (opcional)
  %% @type hand corr handoff      → força o tipo de uma seta tracejada
  %% @label dedup>vinc 12,-6      → rótulo da seta deslocado (x,y) da posição automática
  %% @lane n1 #1D62D1             → cor da raia
  %% @subtitle texto              → subtítulo do fluxo
"""
import html, re

from pbcore import EDGE_TYPES, NODE_TYPES, DEFAULT_LANES, SUPPORT_LANE_LABEL, LANE_KEY_RE, slug

HEADER = "%% medusa-flow 1"
CLASS_OF = {"close": "close", "neutral": "neutral", "attention": "attention", "crossref": "crossref", "support": "support"}
CLASSDEFS = {
    "close": "fill:#E6F4EA,stroke:#2E7D32", "neutral": "fill:#EEEEEE,stroke:#9E9E9E",
    "attention": "fill:#FFF7E6,stroke:#B25E09,stroke-width:2px", "crossref": "fill:#FFFFFF,stroke:#7A3E9D,stroke-dasharray:5 3",
    "support": "fill:#FFFFFF,stroke:#5B6673,stroke-dasharray:5 3",
}
ARROW_OF = {"flow": "-->", "escalation": "==>", "handoff": "-.->", "crossref": "-.->", "support": "-.->"}
NODE_ID_RE = re.compile(r"^[A-Za-z_][\w-]{0,39}$")
PALETTE = ["#1D62D1", "#B25E09", "#C0272D", "#2E7D32", "#7A3E9D", "#00838F", "#5B6673", "#AD1457"]


class FlowSyntaxError(ValueError):
    pass

# ───────────────────────── fluxo → texto ─────────────────────────

def _q(s):
    return s.replace('"', "#quot;")

def _label(lines):
    out = []
    for l in lines:
        t = html.escape(l.get("t", ""), quote=False)
        out.append(f"<b>{t}</b>" if l.get("s") == "b" else f"<small>{t}</small>" if l.get("s") == "m" else t)
    return _q("<br>".join(out)) or " "

def _num(v):
    v = round(float(v), 2)
    return str(int(v)) if v == int(v) else str(v)

def infer_edge_type(src, dst, lanes, arrow):
    if arrow == "==>": return "escalation"
    if arrow != "-.->": return "flow"
    kinds = {l["key"]: l for l in lanes}
    order = [l["key"] for l in lanes]
    if dst.get("type") == "crossref": return "crossref"
    if kinds.get(dst["lane"], {}).get("kind") == "support" or dst.get("type") == "support": return "support"
    if src["lane"] != dst["lane"] and order.index(dst["lane"]) > order.index(src["lane"]): return "handoff"
    return "crossref"

def render(flow, refs=None, positions=True):
    refs = refs or {}
    lanes = flow.get("lanes") or DEFAULT_LANES
    nodes = {n["id"]: n for n in flow["nodes"]}
    L = [HEADER]
    if flow.get("subtitle"): L.append(f"%% @subtitle {flow['subtitle']}")
    L.append("flowchart TB")
    for lane in lanes:
        L.append(f'  subgraph {lane["key"]}["{_q(lane["label"])}"]')
        L.append(f'    %% @lane {lane["key"]} {lane.get("color", "")}'.rstrip())
        for n in flow["nodes"]:
            if n["lane"] != lane["key"]: continue
            lab = _label(n.get("lines", []))
            shape = f'(["{lab}"])' if n["type"] == "start" else f'{{"{lab}"}}' if n["type"] == "decision" else f'["{lab}"]'
            cls = f':::{CLASS_OF[n["type"]]}' if n["type"] in CLASS_OF else ""
            L.append(f"    {n['id']}{shape}{cls}")
        L.append("  end")
    for e in flow["edges"]:
        if e["from"] not in nodes or e["to"] not in nodes: continue
        arrow = ARROW_OF.get(e.get("type"), "-->")
        lab = f"|{_q(e['label'])}|" if e.get("label") else ""
        L.append(f"  {e['from']} {arrow}{lab} {e['to']}")
        if arrow == "-.->" and infer_edge_type(nodes[e["from"]], nodes[e["to"]], lanes, arrow) != e["type"]:
            L.append(f"  %% @type {e['from']} {e['to']} {e['type']}")
    if refs:
        L.append("")
        for nid, r in refs.items():
            if nid in nodes and r: L.append(f"  %% @refs {nid} {', '.join(r)}")
    if positions:
        L.append("")
        for n in flow["nodes"]:
            L.append(f"  %% @pos {n['id']} {_num(n['x'])} {_num(n['y'])} {_num(n['w'])} {_num(n['h'])}")
        for e in flow["edges"]:
            if e.get("exit") or e.get("entry") or e.get("wps"):
                side = lambda p: f"{_num(p['x'])},{_num(p['y'])}" if p else "auto"
                wps = " ".join(f"{w['lane']}:{_num(w['x'])},{_num(w['y'])}" for w in e.get("wps", []))
                L.append(f"  %% @route {e['from']}>{e['to']} {side(e.get('exit'))} {side(e.get('entry'))} {wps}".rstrip())
            lp = e.get("lp")
            if e.get("label") and lp and (lp.get("dx") or lp.get("dy")):
                L.append(f"  %% @label {e['from']}>{e['to']} {_num(lp['dx'])},{_num(lp['dy'])}")
    used = sorted({n["type"] for n in flow["nodes"] if n["type"] in CLASSDEFS})
    if used:
        L.append("")
        L += [f"  classDef {c} {CLASSDEFS[c]}" for c in used]
    return "\n".join(L) + "\n"

# ───────────────────────── texto → fluxo ─────────────────────────

def _shape(o, c, g):
    # forma com rótulo entre aspas (aceita qualquer caractere menos aspas) ou sem aspas (até o fechamento)
    return rf'{o}\s*"(?P<{g}q>[^"]*)"\s*{c}|{o}(?P<{g}>[^"]*?){c}'
SHAPE_GROUPS = ("st", "ci", "hx", "de", "re", "ro")
SHAPE_RE = "(" + "|".join([_shape(r"\(\[", r"\]\)", "st"), _shape(r"\(\(", r"\)\)", "ci"), _shape(r"\{\{", r"\}\}", "hx"),
                          _shape(r"\{", r"\}", "de"), _shape(r"\[", r"\]", "re"), _shape(r"\(", r"\)", "ro")]) + ")"
NODE_RE = re.compile(r"(?P<id>[A-Za-z_]\w*(?:-\w+)*)\s*(?:" + SHAPE_RE + r")?(?::::(?P<cls>[\w-]+))?")
ARROW_RE = re.compile(r"\s*(?:--\s*(?P<lt>[^->|][^>|]*?)\s*(?P<a1>-->|-\.->|==>)|(?P<a2>-->|-\.->|==>|---|-\.-|===))\s*(?:\|(?P<lb>[^|]*)\|)?\s*")

def _unq(s):
    return (s or "").replace("#quot;", '"').strip()

def label_lines(raw):
    lines = []
    for seg in re.split(r"<br\s*/?>|\\n", _unq(raw), flags=re.I):
        s = "n"
        if re.fullmatch(r"\s*<(b|strong)>.*</(b|strong)>\s*", seg, re.S | re.I): s = "b"
        elif re.fullmatch(r"\s*<(small|i|em|font[^>]*)>.*</(small|i|em|font)>\s*", seg, re.S | re.I): s = "m"
        t = html.unescape(re.sub(r"<[^>]+>", "", seg)).strip()
        if t: lines.append({"t": t[:160], "s": s})
    return lines

def estimate_size(ntype, lines):
    t = NODE_TYPES[ntype]
    longest = max([len(l["t"]) for l in lines] or [6])
    w = max(t["w"], min(240, int(longest * 6.2 + 20)))
    if ntype == "decision": w = max(w, min(260, int(longest * 7.5 + 40)))
    h = max(t["h"], len(lines) * 14 + (28 if ntype == "decision" else 16))
    return float(round(w / 8) * 8), float(round(h / 4) * 4)

def parse(text, teams=None):
    """Retorna (flow, refs, avisos). Erros de sintaxe viram FlowSyntaxError com o número da linha."""
    teams = teams or {}
    lanes, lane_by, nodes, edges, refs, warns = [], {}, {}, [], {}, []
    pos, routes, forced, colors, lpos = {}, {}, {}, {}, {}
    subtitle, current = "", None

    def get_lane(key, label):
        if key not in lane_by:
            support = slug(label).startswith(("times-de-apoio", "apoio"))
            team = None if support else label
            color = (teams.get(team) or {}).get("color") if team else "#5B6673"
            lane = {"key": key, "label": label, "team": team, "color": color or PALETTE[len(lanes) % len(PALETTE)],
                    "kind": "support" if support else "team"}
            lanes.append(lane); lane_by[key] = lane
            if team and team not in teams: warns.append(f"Time \"{team}\" não existe no cadastro: será criado como time central.")
        return lane_by[key]

    def node_ref(m, lineno):
        nid = m.group("id")
        if not NODE_ID_RE.fullmatch(nid): raise FlowSyntaxError(f"linha {lineno}: id de caixa inválido \"{nid}\"")
        grp = next((g for g in SHAPE_GROUPS if m.group(g + "q") is not None or m.group(g) is not None), None)
        raw = None if grp is None else (m.group(grp + "q") if m.group(grp + "q") is not None else m.group(grp))
        cls = m.group("cls")
        if nid not in nodes:
            lane = current or (lanes[0] if lanes else get_lane("n1", "SOC N1"))
            nodes[nid] = {"id": nid, "lane": lane["key"], "type": "action", "lines": [{"t": nid, "s": "n"}], "_declared": False}
        n = nodes[nid]
        if raw is not None:
            n["lines"] = label_lines(raw) or [{"t": nid, "s": "n"}]
            n["type"] = "start" if grp == "st" else "decision" if grp in ("de", "hx") else "action"
            n["_declared"] = True
            if current and not n.get("_lane_fixed"): n["lane"] = current["key"]; n["_lane_fixed"] = True
        if cls:
            if cls in CLASS_OF: n["type"] = cls
            else: warns.append(f"linha {lineno}: classe \"{cls}\" desconhecida (use close, neutral, attention, crossref ou support)")
        return nid

    for lineno, raw_line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        line = raw_line.strip()
        if not line: continue
        if line.startswith("%%"):
            m = re.match(r"%%\s*@(\w+)\s*(.*)$", line)
            if not m: continue
            kind, arg = m.group(1), m.group(2).strip()
            if kind == "subtitle": subtitle = arg[:300]
            elif kind == "refs":
                p = arg.split(None, 1)
                if len(p) == 2: refs[p[0]] = [x.strip() for x in re.split(r"[,\s]+", p[1]) if x.strip()][:40]
            elif kind == "pos":
                p = arg.split()
                try: pos[p[0]] = [float(v) for v in p[1:5]]
                except (ValueError, IndexError): warns.append(f"linha {lineno}: @pos inválido")
            elif kind == "route":
                p = arg.split()
                if p and ">" in p[0]: routes[tuple(p[0].split(">", 1))] = p[1:]
            elif kind == "label":
                mm = re.fullmatch(r"([\w-]+)>([\w-]+)\s+(-?[\d.]+),(-?[\d.]+)", arg)
                if mm: lpos[(mm.group(1), mm.group(2))] = {"dx": float(mm.group(3)), "dy": float(mm.group(4))}
            elif kind == "type":
                p = arg.split()
                if len(p) == 3 and p[2] in EDGE_TYPES: forced[(p[0], p[1])] = p[2]
            elif kind == "lane":
                p = arg.split()
                if len(p) == 2 and re.fullmatch(r"#[0-9A-Fa-f]{6}", p[1]): colors[p[0]] = p[1]
            continue
        if re.match(r"^(flowchart|graph)\b", line, re.I) or line.startswith(("classDef ", "class ", "style ", "linkStyle ", "click ", "direction ")):
            continue
        m = re.match(r'^subgraph\s+([\w-]+)\s*(?:\[\s*"?(.*?)"?\s*\])?\s*$', line)
        if m:
            key = re.sub(r"[^a-z0-9_-]", "", m.group(1).lower())[:24] or f"raia{len(lanes) + 1}"
            label = _unq(m.group(2)) if m.group(2) else m.group(1).replace("_", " ")
            if not LANE_KEY_RE.fullmatch(key): raise FlowSyntaxError(f"linha {lineno}: nome de raia inválido")
            current = get_lane(key, label[:60])
            continue
        if line == "end":
            current = None; continue
        # sequência: nó (seta nó)*
        pos_i, prev, chain = 0, None, []
        m = NODE_RE.match(line, pos_i)
        if not m: raise FlowSyntaxError(f"linha {lineno}: não entendi \"{line[:60]}\"")
        prev = node_ref(m, lineno); pos_i = m.end()
        while pos_i < len(line):
            a = ARROW_RE.match(line, pos_i)
            if not a: raise FlowSyntaxError(f"linha {lineno}: esperado uma seta (-->, -.->, ==>) em \"{line[pos_i:pos_i + 30]}\"")
            pos_i = a.end()
            m = NODE_RE.match(line, pos_i)
            if not m: raise FlowSyntaxError(f"linha {lineno}: falta a caixa de destino da seta")
            nxt = node_ref(m, lineno); pos_i = m.end()
            arrow = a.group("a1") or a.group("a2")
            arrow = {"---": "-->", "-.-": "-.->", "===": "==>"}.get(arrow, arrow)
            edges.append({"from": prev, "to": nxt, "arrow": arrow, "label": _unq(a.group("lb") or a.group("lt") or "")[:80]})
            prev = nxt
    if not nodes: raise FlowSyntaxError("nenhuma caixa encontrada")
    if not lanes: get_lane("n1", "SOC N1")
    if len(lanes) > 12: raise FlowSyntaxError("no máximo 12 raias")
    for k, c in colors.items():
        if k in lane_by: lane_by[k]["color"] = c

    # tipos e tamanhos
    flow_nodes = []
    for n in nodes.values():
        if not n["_declared"]: warns.append(f"Caixa \"{n['id']}\" só aparece em setas; criada como Ação.")
        n.pop("_declared", None); n.pop("_lane_fixed", None)
        if n["type"] == "support":
            txt = " ".join(l["t"] for l in n["lines"])
            n["team"] = next((t for t in sorted(teams, key=len, reverse=True) if re.search(rf"(?<![\w/]){re.escape(t)}(?![\w/])", txt)), None)
        w, h = estimate_size(n["type"], n["lines"])
        p = pos.get(n["id"])
        n.update(x=p[0], y=p[1], w=p[2] if len(p) > 2 else w, h=p[3] if len(p) > 3 else h) if p else n.update(w=w, h=h)
        flow_nodes.append(n)
    auto_layout(flow_nodes, edges, lanes, placed={nid for nid in pos if nid in nodes})

    # setas
    out_edges, used = [], set(nodes)
    def eid():
        i = 1
        while f"e{i}" in used: i += 1
        used.add(f"e{i}"); return f"e{i}"
    for e in edges:
        src, dst = nodes[e["from"]], nodes[e["to"]]
        etype = forced.get((e["from"], e["to"])) or infer_edge_type(src, dst, lanes, e["arrow"])
        r = routes.get((e["from"], e["to"]), [])
        def side(v):
            try: x, y = v.split(","); return {"x": float(x), "y": float(y)}
            except (ValueError, AttributeError): return None
        wps = []
        for w in r[2:]:
            mm = re.fullmatch(r"([\w-]+):(-?[\d.]+),(-?[\d.]+)", w)
            if mm and mm.group(1) in lane_by: wps.append({"lane": mm.group(1), "x": float(mm.group(2)), "y": float(mm.group(3))})
        out_edges.append({"id": eid(), "from": e["from"], "to": e["to"], "label": e["label"], "type": etype,
                          "exit": side(r[0]) if r else None, "entry": side(r[1]) if len(r) > 1 else None, "wps": wps})
        if e["label"] and (e["from"], e["to"]) in lpos: out_edges[-1]["lp"] = lpos[(e["from"], e["to"])]
    refs = {k: v for k, v in refs.items() if k in nodes}
    return {"subtitle": subtitle, "lanes": lanes, "nodes": flow_nodes, "edges": out_edges}, refs, warns

# ───────────────────────── layout automático ─────────────────────────

def auto_layout(nodes, edges, lanes, placed=frozenset()):
    """Posiciona as caixas sem @pos: ordem do fluxo (camadas) de cima para baixo dentro de cada raia,
    caixas da mesma camada lado a lado, ordenadas pela posição média de quem aponta para elas."""
    todo = [n for n in nodes if n["id"] not in placed]
    if not todo: return
    byid = {n["id"]: n for n in nodes}
    succ = {n["id"]: [] for n in nodes}
    pred = {n["id"]: [] for n in nodes}
    for e in edges:
        succ[e["from"]].append(e["to"]); pred[e["to"]].append(e["from"])
    # camadas pelo caminho mais longo, ignorando ciclos (arestas de retorno)
    rank, state = {}, {}
    def visit(v, stack):
        state[v] = 1
        r = 0
        for p in pred[v]:
            if state.get(p) == 1: continue          # ciclo
            if p not in rank: visit(p, stack)
            r = max(r, rank[p] + 1)
        rank[v] = r; state[v] = 2
    order_decl = [n["id"] for n in nodes]
    for v in order_decl:
        if v not in rank: visit(v, [])
    x_of = {n["id"]: n["x"] + n["w"] / 2 for n in nodes if n["id"] in placed}
    START_X, GAP_X, GAP_Y, TOP = 48, 28, 40, 20
    for lane in lanes:
        lane_nodes = [byid[v] for v in order_decl if byid[v]["lane"] == lane["key"] and v not in placed]
        if not lane_nodes: continue
        fixed = [n for n in nodes if n["lane"] == lane["key"] and n["id"] in placed]
        y = max([TOP] + [n["y"] + n["h"] + GAP_Y for n in fixed])
        rows = {}
        for n in lane_nodes: rows.setdefault(rank[n["id"]], []).append(n)
        for r in sorted(rows):
            row = rows[r]
            def bary(n):
                xs = [x_of[p] for p in pred[n["id"]] if p in x_of]
                return sum(xs) / len(xs) if xs else 1e9 + order_decl.index(n["id"])
            row.sort(key=bary)
            x = START_X
            for n in row:
                want = bary(n)
                if want < 1e9: x = max(x, round((want - n["w"] / 2) / 8) * 8)
                n["x"], n["y"] = float(x), float(y)
                x_of[n["id"]] = x + n["w"] / 2
                x += n["w"] + GAP_X
            y += max(n["h"] for n in row) + GAP_Y
