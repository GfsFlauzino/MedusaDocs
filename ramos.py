"""Ramos (R1, R2…) sincronizados entre fluxograma e documento.

Um ramo existe nos dois lados:
  documento   → subseção "R3 · Nome" (normalmente em "Ramos em detalhe"), com a tabela de detalhe
  fluxograma  → caixa cujo texto começa com "R3" e que está vinculada a R3 ("ao clicar")
A aba Ramos lê o documento. Ao salvar um lado, o servidor compara com a versão anterior desse mesmo
lado e aplica no outro o que mudou: ramo criado, renomeado, indicador alterado ou ramo excluído.
Comparar com a versão anterior evita apagar o que nunca existiu do outro lado (playbooks antigos).

Em templates o ramo é o protótipo R{{ramo.n}}: uma subseção e uma caixa que se repetem por ramo.
"""
import copy, re

import pbcore as core

PROTO = "{{ramo.n}}"
_KEY = r"(\d+|\{\{\s*ramo\.n\s*\}\})"
SUB_RE = re.compile(rf"^R{_KEY}\s*·\s*(.*)$")
NODE_RE = re.compile(rf"^R{_KEY}(?:\s*[·:–-]\s*|\s+|$)(.*)$")
REF_RE = re.compile(rf"^R{_KEY}$")
SECTION = "Ramos em detalhe"
DETAIL_ROWS = ["Entrada", "Cenário", "O N1 verifica", "É sucesso quando", "Desfecho típico", "Contenção do SOC",
               "Contenção do CSIRT", "Saídas", "MITRE"]
RANGE_RE = re.compile(r"\bR1 a R\d+\b")
GAP, W, H = 10, 110, 92


def norm_key(k):
    return PROTO if "ramo.n" in k else str(int(k))

def ref_key(r):
    m = REF_RE.match(re.sub(r"\s+", "", str(r)))
    return norm_key(m.group(1)) if m else None

def sort_key(k):
    return (1, 0) if k == PROTO else (0, int(k))

def default_name(k):
    return "{{ramo.nome}}" if k == PROTO else "Novo ramo"

def default_q(k):
    return "{{ramo.pergunta}}" if k == PROTO else ""

# ───────────────────────── leitura ─────────────────────────

def _q_row(sub):
    for b in sub.get("blocks", []):
        if b["t"] == "table":
            for r in b["rows"]:
                if r and core._norm(r[0]).startswith("e sucesso quando"): return r
    return None

def doc_ramos(doc):
    out = {}
    for si, sec in enumerate(doc.get("sections", [])):
        for ui, sub in enumerate(sec.get("subs", [])):
            m = SUB_RE.match(sub["title"].strip())
            if not m: continue
            k = norm_key(m.group(1))
            if k in out: continue
            r = _q_row(sub)
            out[k] = {"name": m.group(2).strip(), "q": (r[1] if r and len(r) > 1 else "").strip(), "sec": si, "sub": ui}
    return out

def flow_ramos(flow, refs):
    out = {}
    for n in flow.get("nodes", []):
        first = ((n.get("lines") or [{}])[0].get("t") or "").strip()
        m = NODE_RE.match(first)
        if not m: continue
        k = norm_key(m.group(1))
        if k in out or k not in {ref_key(r) for r in refs.get(n["id"], [])}: continue
        q = next((l["t"] for l in n["lines"][1:] if l.get("s") == "m"), "")
        out[k] = {"name": m.group(2).strip(), "q": q.strip(), "node": n}
    return out

def referenced(refs):
    return {k for v in refs.values() for k in map(ref_key, v) if k}

def summary(doc, flow, refs):
    d, f = doc_ramos(doc), flow_ramos(flow, refs)
    return [{"key": k, "id": f"R{k}", "name": (d.get(k) or f.get(k))["name"], "inDoc": k in d, "inFlow": k in f}
            for k in sorted(set(d) | set(f), key=sort_key)]

# ───────────────────────── documento ─────────────────────────

def ramos_section(doc, create=True):
    secs = doc["sections"]
    for s in secs:
        if s["title"].strip().lower().startswith("ramos"): return s
    for s in secs:
        if any(SUB_RE.match(x["title"].strip()) for x in s.get("subs", [])): return s
    if not create: return None
    sec = {"title": SECTION, "blocks": [{"t": "p", "text": "Cada ramo diz o que o N1 verifica, o que conta como sucesso, até onde cada time contém e para onde o caso pode seguir."}], "subs": []}
    idx = next((i + 1 for i, s in enumerate(secs) if s["title"].startswith("Fluxo de resposta")), None)
    if idx is None: idx = next((i for i, s in enumerate(secs) if s["title"].startswith(("Registro no ticket", "Itens em aberto"))), len(secs))
    secs.insert(idx, sec)
    return sec

def _detail_blocks(sec, q):
    proto = next((x for x in sec.get("subs", []) if SUB_RE.match(x["title"].strip())), None)
    if proto:
        blocks = copy.deepcopy(proto["blocks"])
        for b in blocks:
            if b["t"] == "table":
                b["rows"] = [[r[0]] + [""] * (len(r) - 1) if r else r for r in b["rows"]]
            elif b["t"] in ("p", "quote"): b["text"] = ""
            elif b["t"] == "ul": b["items"] = [""]
        blocks = [b for b in blocks if not (b["t"] in ("p", "quote") and not b["text"]) and not (b["t"] == "ul" and b["items"] == [""]) and b["t"] != "img"]
    else:
        blocks = [{"t": "table", "head": ["Item", "Conteúdo"], "rows": [[x, ""] for x in DETAIL_ROWS]}]
    tmp = {"blocks": blocks}
    r = _q_row(tmp)
    if r is not None and len(r) > 1: r[1] = q
    return blocks

def add_doc(doc, k, name, q):
    sec = ramos_section(doc)
    sub = {"title": f"R{k} · {name or default_name(k)}", "blocks": _detail_blocks(sec, q)}
    pos = len(sec["subs"])
    for i, x in enumerate(sec["subs"]):
        m = SUB_RE.match(x["title"].strip())
        if m and sort_key(norm_key(m.group(1))) > sort_key(k): pos = i; break
    sec["subs"].insert(pos, sub)

def _doc_sub(doc, k):
    r = doc_ramos(doc).get(k)
    return doc["sections"][r["sec"]]["subs"][r["sub"]] if r else None

def rename_doc(doc, k, name):
    sub = _doc_sub(doc, k)
    if sub: sub["title"] = f"R{k} · {name}"

def set_doc_q(doc, k, q):
    sub = _doc_sub(doc, k)
    r = _q_row(sub) if sub else None
    if r is not None:
        while len(r) < 2: r.append("")
        r[1] = q

def remove_doc(doc, k):
    r = doc_ramos(doc).get(k)
    if r: doc["sections"][r["sec"]]["subs"].pop(r["sub"])

# ───────────────────────── fluxograma ─────────────────────────

def _uid(flow, base):
    used = {n["id"] for n in flow["nodes"]} | {e["id"] for e in flow["edges"]}
    k, i = base, 2
    while k in used: k = f"{base}_{i}"; i += 1
    return k

def node_lines(k, name, q):
    return [{"t": f"R{k} {name or default_name(k)}".strip(), "s": "b"}] + ([{"t": q, "s": "m"}] if q else [])

def add_flow(flow, refs, k, name, q):
    """Cria a caixa do ramo. Havendo outros ramos, fica ao lado do último e copia as ligações dele
    (ex.: decisão "Ramo" → R1…Rn → próxima etapa); senão, abaixo da decisão de ramo."""
    lanes = [l["key"] for l in core.lanes_of(flow)]
    have = sorted(flow_ramos(flow, refs).values(), key=lambda r: (lanes.index(r["node"]["lane"]) if r["node"]["lane"] in lanes else 99, r["node"]["x"]))
    nid = _uid(flow, "r" + (k if k != PROTO else ""))
    if have:
        p = have[-1]["node"]
        n = {**copy.deepcopy(p), "id": nid, "x": p["x"] + p["w"] + GAP, "lines": node_lines(k, name, q)}
        n.pop("team", None)
        flow["nodes"].append(n)
        dx = p["w"] + GAP
        for e in [e for e in flow["edges"] if p["id"] in (e["from"], e["to"])]:
            c = copy.deepcopy(e)
            c["id"] = _uid(flow, f"{e['id']}_{nid}")
            c["from"] = nid if e["from"] == p["id"] else e["from"]
            c["to"] = nid if e["to"] == p["id"] else e["to"]
            c["wps"] = [{**w, "x": w["x"] + dx} if w.get("lane") == p["lane"] and p["x"] <= w["x"] <= p["x"] + p["w"] else w
                        for w in e.get("wps", [])]
            flow["edges"].append(c)
    else:
        anchor = next((x for x in flow["nodes"] if x["type"] == "decision" and "ramo" in " ".join(l["t"] for l in x["lines"]).lower()), None)
        if anchor is None:     # sem decisão de ramo: liga ao início, se ele ainda não leva a lugar nenhum
            anchor = next((x for x in flow["nodes"] if x["type"] == "start" and not any(e["from"] == x["id"] for e in flow["edges"])), None)
        if anchor:
            lane = anchor["lane"]
            below = [x for x in flow["nodes"] if x["lane"] == lane and x["x"] < anchor["x"] + anchor["w"] and x["x"] + x["w"] > anchor["x"] and x["y"] > anchor["y"]]
            x, y = max(36.0, anchor["x"] + anchor["w"] / 2 - W / 2), max([anchor["y"] + anchor["h"] + 40] + [b["y"] + b["h"] + 24 for b in below])
        else:
            lane = lanes[0]
            same = [x for x in flow["nodes"] if x["lane"] == lane]
            x, y = (max(x["x"] + x["w"] for x in same) + 24, 20.0) if same else (68.0, 20.0)
        flow["nodes"].append({"id": nid, "lane": lane, "x": float(x), "y": float(y), "w": float(W), "h": float(H), "type": "action",
                              "lines": node_lines(k, name, q)})
        if anchor:
            flow["edges"].append({"id": _uid(flow, f"e_{nid}"), "from": anchor["id"], "to": nid, "label": "", "type": "flow",
                                  "exit": None, "entry": None, "wps": []})
    refs[nid] = [f"R{k}"]
    return nid

def rename_flow(node, k, name):
    node["lines"][0] = {"t": f"R{k} {name}".strip(), "s": node["lines"][0].get("s", "b")}

def set_flow_q(node, q):
    i = next((i for i, l in enumerate(node["lines"][1:], 1) if l.get("s") == "m"), None)
    if i is None:
        if q: node["lines"].append({"t": q, "s": "m"})
    elif q: node["lines"][i]["t"] = q
    else: node["lines"].pop(i)

def remove_flow(flow, refs, node):
    flow["nodes"] = [n for n in flow["nodes"] if n["id"] != node["id"]]
    flow["edges"] = [e for e in flow["edges"] if node["id"] not in (e["from"], e["to"])]
    refs.pop(node["id"], None)

# ───────────────────────── "R1 a Rn" ─────────────────────────

def update_range(doc, flow, keys):
    nums = [int(k) for k in keys if k != PROTO]
    if len(nums) < 2: return
    rng = f"R1 a R{max(nums)}"
    for n in flow["nodes"]:
        for l in n["lines"]: l["t"] = RANGE_RE.sub(rng, l["t"])
    def walk(blocks):
        for b in blocks:
            if b["t"] in ("p", "quote"): b["text"] = RANGE_RE.sub(rng, b["text"])
            elif b["t"] == "ul": b["items"] = [RANGE_RE.sub(rng, x) for x in b["items"]]
            elif b["t"] == "table": b["rows"] = [[RANGE_RE.sub(rng, c) for c in r] for r in b["rows"]]
    for s in doc["sections"]:
        walk(s["blocks"])
        for x in s.get("subs", []): walk(x["blocks"])

# ───────────────────────── sincronização ─────────────────────────

def sync_from_flow(doc, old_flow, old_refs, flow, refs):
    """Fluxograma salvo → documento. Altera doc no lugar; devolve a lista de mudanças."""
    old, new, changes = flow_ramos(old_flow, old_refs), flow_ramos(flow, refs), []
    for k in sorted(new, key=sort_key):
        r, d = new[k], doc_ramos(doc)
        if k not in d:
            add_doc(doc, k, r["name"], r["q"]); changes.append(f"R{k} criado no documento")
            continue
        o = old.get(k)
        if o and r["name"] and r["name"] != o["name"] and r["name"] != d[k]["name"]:
            rename_doc(doc, k, r["name"]); changes.append(f"R{k} renomeado no documento")
        if o and r["q"] != o["q"] and r["q"] != d[k]["q"]:
            set_doc_q(doc, k, r["q"]); changes.append(f"indicador de R{k} atualizado no documento")
    refd = referenced(refs)
    for k in old:
        if k not in new and k not in refd and k in doc_ramos(doc):
            remove_doc(doc, k); changes.append(f"R{k} removido do documento")
    if changes: update_range(doc, flow, doc_ramos(doc).keys())
    return changes

def sync_from_doc(flow, refs, old_doc, doc):
    """Documento salvo → fluxograma. Altera flow/refs no lugar; devolve a lista de mudanças."""
    oldd, newd, changes = doc_ramos(old_doc), doc_ramos(doc), []
    for k in sorted(newd, key=sort_key):
        r, f = newd[k], flow_ramos(flow, refs)
        if k not in f:
            if k in referenced(refs): continue          # já existe uma caixa vinculada a esse ramo
            add_flow(flow, refs, k, r["name"], r["q"]); changes.append(f"R{k} criado no fluxograma")
            continue
        o, node = oldd.get(k), f[k]["node"]
        if o and r["name"] and r["name"] != o["name"] and r["name"] != f[k]["name"]:
            rename_flow(node, k, r["name"]); changes.append(f"R{k} renomeado no fluxograma")
        if o and r["q"] != o["q"] and r["q"] != f[k]["q"]:
            set_flow_q(node, r["q"]); changes.append(f"indicador de R{k} atualizado no fluxograma")
    for k in oldd:
        if k not in newd:
            f = flow_ramos(flow, refs)
            if k in f:
                remove_flow(flow, refs, f[k]["node"]); changes.append(f"R{k} removido do fluxograma")
    if changes: update_range(doc, flow, newd.keys())
    return changes

def next_key(doc, flow, refs):
    used = [int(k) for k in set(doc_ramos(doc)) | set(flow_ramos(flow, refs)) | referenced(refs) if k != PROTO]
    return str(max(used, default=0) + 1)

def add(doc, flow, refs, k, name, q):
    """Novo ramo nos dois lados (aba Ramos e templates)."""
    if k not in doc_ramos(doc): add_doc(doc, k, name, q)
    if k not in flow_ramos(flow, refs) and k not in referenced(refs): add_flow(flow, refs, k, name, q)
    update_range(doc, flow, doc_ramos(doc).keys())

def remove(doc, flow, refs, k):
    remove_doc(doc, k)
    f = flow_ramos(flow, refs)
    if k in f: remove_flow(flow, refs, f[k]["node"])
    for v in refs.values():
        v[:] = [r for r in v if ref_key(r) != k]
    update_range(doc, flow, doc_ramos(doc).keys())
