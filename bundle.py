"""Formato de troca de playbooks entre instalações: arquivo único .medusa.md

  ---                                  front matter (metadados)
  format: medusa-playbook
  version: 1
  id: PB-02
  name: Intrusão Contra a Rede
  ...
  ---
  # PB-02 — Intrusão Contra a Rede     documento completo, em Markdown comum
  ...
  <!-- medusa:teams                     times citados (cor, categoria, descrição), em JSON
  {...}
  -->
  <!-- medusa:flow -->                  fluxograma em Mermaid (ver flowdsl.py)
  ```mermaid
  ...
  ```
  <!-- medusa:images                    imagens do documento (opcional), em JSON: {"img-….png": "data:image/png;base64,…"}
  {...}
  -->

Abre em qualquer visualizador de Markdown; GitHub, GitLab e Confluence (macro Mermaid) desenham o fluxo.
Um .md comum (sem fluxo) também é aceito na importação.
"""
import json, re
from datetime import datetime

import flowdsl
import pbcore as core

FORMAT, VERSION = "medusa-playbook", 1
MAX_SIZE = 6 * 1024 * 1024


class BundleError(ValueError):
    pass


def referenced_teams(view, teams):
    names = {l["team"] for l in core.lanes_of(view["flow"]) if l.get("team")}
    names |= {n.get("team") for n in view["flow"]["nodes"] if n.get("team")}
    names |= {s["team"] for s in view["steps"]}
    return {n: teams[n] for n in sorted(names) if n in teams}


def export(view, teams, user_name, app_name, images=None):
    g = view["gov"]
    fm = {"format": FORMAT, "version": VERSION, "id": view["id"], "name": view["name"],
          "status_origem": g["status"], "aprovador_origem": g.get("approver") or "",
          "exportado_em": datetime.now().isoformat(timespec="seconds"), "exportado_por": user_name, "gerado_por": app_name}
    front = "---\n" + "".join(f"{k}: {str(v).replace(chr(10), ' ')}\n" for k, v in fm.items()) + "---\n\n"
    md = core.doc_to_md(view["doc"])
    tm = json.dumps(referenced_teams(view, teams), ensure_ascii=False, indent=2).replace("-->", "-- >")
    flow = flowdsl.render(view["flow"], view["refs"])
    imgs = f"\n<!-- medusa:images\n{json.dumps(images, indent=0)}\n-->\n" if images else ""
    return f"{front}{md}\n<!-- medusa:teams\n{tm}\n-->\n\n<!-- medusa:flow -->\n```mermaid\n{flow}```\n{imgs}"


def parse(text, teams):
    """Lê um .medusa.md (ou .md comum). Não grava nada: devolve o que seria importado."""
    if len(text.encode("utf-8")) > MAX_SIZE: raise BundleError(f"Arquivo grande demais (máx. {MAX_SIZE // 1024 // 1024} MB)")
    text = text.replace("\r\n", "\n").lstrip("﻿")
    meta, warns = {}, []
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if m:
        for line in m.group(1).split("\n"):
            if ":" in line:
                k, v = line.split(":", 1); meta[k.strip()] = v.strip()
        text = text[m.end():]
        if meta.get("format") not in (None, FORMAT, "medusa-template"): warns.append(f"Formato \"{meta.get('format')}\" desconhecido; tentando importar mesmo assim.")
        if str(meta.get("version", "1")) not in ("1",): warns.append(f"Versão {meta.get('version')} do formato; esta ferramenta lê a versão 1.")
    # imagens (data URLs; o servidor confere tipo, tamanho e nome antes de gravar)
    images = {}
    im = re.search(r"<!--\s*medusa:images\s*\n(.*?)\n-->", text, re.S)
    if im:
        try:
            raw = json.loads(im.group(1))
            if isinstance(raw, dict): images = {str(k)[:80]: str(v) for k, v in list(raw.items())[:200]}
        except ValueError:
            warns.append("Bloco de imagens ilegível; ignorado.")
        text = text[:im.start()] + text[im.end():]
    # times
    team_defs = {}
    tm = re.search(r"<!--\s*medusa:teams\s*\n(.*?)\n-->", text, re.S)
    if tm:
        try:
            raw = json.loads(tm.group(1))
            if isinstance(raw, dict):
                team_defs = {str(k)[:40]: v for k, v in list(raw.items())[:60] if isinstance(v, dict)}
        except ValueError:
            warns.append("Bloco de times ilegível; ignorado.")
        text = text[:tm.start()] + text[tm.end():]
    # fluxo
    flow_txt = None
    fm_ = re.search(r"<!--\s*medusa:flow\s*-->\s*```mermaid\n(.*?)```", text, re.S)
    if fm_:
        flow_txt = fm_.group(1); text = text[:fm_.start()] + text[fm_.end():]
    else:
        mm = re.search(r"```mermaid\n((?:%%.*\n)*\s*(?:flowchart|graph)\b.*?)```", text, re.S)
        if mm: flow_txt = mm.group(1); text = text[:mm.start()] + text[mm.end():]
    # documento
    if not re.match(r"^\s*#\s+\S", text): raise BundleError("O documento precisa começar com um título (# PB-00 — Nome)")
    doc = core.parse_md(text.strip() + "\n")
    tid = re.match(r"(PB-\d{2,3})\s*[—-]\s*(.+)$", doc["title"])
    pid = (meta.get("id") or (tid.group(1) if tid else "")).upper()
    name = meta.get("name") or (tid.group(2).strip() if tid else doc["title"])
    if not doc["sections"]: warns.append("O documento não tem seções (##).")
    known = dict(teams); known.update({k: v for k, v in team_defs.items() if k not in known})
    if flow_txt:
        try:
            flow, refs, fw = flowdsl.parse(flow_txt, known)
        except flowdsl.FlowSyntaxError as e:
            raise BundleError(f"Fluxograma: {e}")
        warns += [w for w in fw if "não existe no cadastro" not in w]
    else:
        flow, refs = {"subtitle": "", "lanes": core.lanes_of({}), "edges": [],
                      "nodes": [{"id": "alerta", "lane": "n1", "x": 68.0, "y": 34.0, "w": 96.0, "h": 48.0, "type": "start",
                                 "lines": [{"t": "Alerta", "s": "n"}]}]}, {}
        warns.append("Sem fluxograma no arquivo: será criado um fluxo inicial vazio.")
    # times que precisam ser criados
    needed = {l["team"]: "central" for l in flow["lanes"] if l.get("team")}
    needed.update({n["team"]: "apoio" for n in flow["nodes"] if n.get("team") and n["team"] not in needed})
    create = {}
    for name_, cat in needed.items():
        if name_ in teams: continue
        d = team_defs.get(name_, {})
        lane = next((l for l in flow["lanes"] if l.get("team") == name_), None)
        create[name_] = {"color": d.get("color") if re.fullmatch(r"#[0-9A-Fa-f]{6}", str(d.get("color", ""))) else (lane or {}).get("color", "#5B6673"),
                         "kind": str(d.get("kind") or ("Time central" if cat == "central" else "Apoio"))[:80],
                         "summary": str(d.get("summary") or "Importado com um playbook. Complete a descrição.")[:1000],
                         "does": [str(x)[:300] for x in d.get("does", [])][:30] if isinstance(d.get("does"), list) else [],
                         "never": [str(x)[:300] for x in d.get("never", [])][:30] if isinstance(d.get("never"), list) else [],
                         "category": cat}
    return {"meta": meta, "id": pid, "name": name, "doc": doc, "flow": flow, "refs": refs, "createTeams": create, "warnings": warns,
            "teamDefs": team_defs, "images": images}
