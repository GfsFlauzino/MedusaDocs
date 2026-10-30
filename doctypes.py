"""Tipos de documento: Playbook, Runbook e Documento.

Todos usam o mesmo par .md (+ .drawio opcional), o mesmo editor, versões, ciclo de vida, auditoria e templates.
O que muda por tipo está aqui: prefixo do ID, pasta no disco, se o fluxograma é obrigatório, opcional ou não existe,
se há passos e ramos, se publicar exige aprovador e se há pastas (organização em diretórios).
Os IDs são únicos entre os tipos (PB-01, RB-01 e DOC-01 convivem); o prefixo diz o tipo.
"""
import re
from pathlib import Path

import pbcore as core

TYPES = {
    "playbook": dict(prefix="PB", label="Playbook", plural="Playbooks", dir="playbooks", flow="required", steps=True, ramos=True,
                     approval=True, folders=False, props_title="Propriedades do playbook", article="o"),
    "runbook": dict(prefix="RB", label="Runbook", plural="Runbooks", dir="runbooks", flow="optional", steps=False, ramos=False,
                    approval=True, folders=True, props_title="Propriedades do runbook", article="o"),
    "doc": dict(prefix="DOC", label="Documento", plural="Documentos", dir="documentos", flow="none", steps=False, ramos=False,
                approval=False, folders=True, props_title="Propriedades do documento", article="o"),
}
BY_PREFIX = {v["prefix"]: k for k, v in TYPES.items()}
ID_RE = re.compile(r"^(PB|RB|DOC)-\d{2,4}$")
PID_IN_PATH = r"(?:PB|RB|DOC)-\d{2,4}"


def type_of(pid):
    """Tipo pelo prefixo do ID (PB-01 → playbook); None se o ID não é de documento."""
    m = re.match(r"^([A-Z]+)-\d", str(pid or "").upper())
    return BY_PREFIX.get(m.group(1)) if m else None


def info(t):
    return TYPES[t]


def src_dir(t):
    """Pasta dos arquivos do tipo: playbook continua em PB_SRC (MEDUSA_HOME/playbooks); os demais em MEDUSA_HOME/<dir>."""
    return core.SRC if t == "playbook" else Path(core.HOME) / TYPES[t]["dir"]


def sort_key(pid):
    return core.sort_key(pid)


def next_id(t, used):
    """Próximo ID livre do tipo (RB-07), com pelo menos 2 dígitos."""
    p = TYPES[t]["prefix"]
    nums = {int(x.split("-")[1]) for x in used if str(x).startswith(p + "-") and x.split("-")[1].isdigit()}
    n = 1
    while n in nums: n += 1
    return f"{p}-{n:02d}"


def public():
    """Para a interface: o que cada tipo tem."""
    return {k: {kk: v[kk] for kk in ("prefix", "label", "plural", "flow", "steps", "ramos", "approval", "folders", "props_title")}
            for k, v in TYPES.items()}
