"""Catálogo de permissões e papéis semente.

Permissão = "área.ação". Por tipo de documento T (playbook, runbook, doc): T.view, T.view_drafts, T.create,
T.edit, T.status, T.approve, T.restore, T.import, T.export, T.delete e, para runbook e doc, T.folders.
Globais: templates.*, users.manage, roles.manage, audit.view, logs.manage, sso.manage, branding.edit, app.reset.

Um papel guarda a lista de permissões; "*" (só o Administrador) vale todas, inclusive as que vierem depois.
Os três papéis do sistema reproduzem exatamente os perfis da 2.x (teste: tests/test_permissoes_golden.py).
"""

TYPES = ("playbook", "runbook", "doc")
ENABLED_TYPES = ("playbook", "runbook", "doc")    # tipos que aparecem na interface
TYPE_LABELS = {"playbook": "Playbooks", "runbook": "Runbooks", "doc": "Documentos"}
FOLDER_TYPES = ("runbook", "doc")

DOC_ACTIONS = [
    ("view", "Ver", "Documentos em Homologação e Produção, versões dessas fases e imagens"),
    ("view_drafts", "Ver rascunhos", "Também os documentos em Desenvolvimento"),
    ("suggest", "Sugerir alterações", "Propor mudanças e comentar trechos; quem edita aceita ou recusa"),
    ("create", "Criar", "Criar documentos"),
    ("edit", "Editar", "Documento, fluxograma, ramos e imagens"),
    ("status", "Alterar status", "Mudar o ciclo de vida"),
    ("approve", "Pode aprovar", "Pode ser escolhido como aprovador de Produção"),
    ("restore", "Restaurar versões", "Voltar o conteúdo a uma versão anterior"),
    ("import", "Importar", "Importar .medusa.md/.md como documento novo"),
    ("export", "Exportar", "Baixar documentos"),
    ("delete", "Excluir", "Excluir documentos (e substituir pelo Importar)"),
    ("folders", "Gerenciar pastas", "Criar, renomear, mover e excluir pastas"),
]

GLOBAL = [
    ("templates.view", "Ver templates"),
    ("templates.edit", "Editar templates, times e tags"),
    ("templates.delete", "Excluir templates"),
    ("users.manage", "Gerenciar usuários"),
    ("roles.manage", "Gerenciar roles"),
    ("audit.view", "Ver e exportar a auditoria"),
    ("logs.manage", "Configurar logs e retenção"),
    ("sso.manage", "Configurar o SSO"),
    ("branding.edit", "Alterar a aparência"),
    ("app.reset", "Resetar a aplicação e alterar a governança"),
]

ADMIN_PERMS = ("users.manage", "roles.manage", "audit.view", "logs.manage", "sso.manage", "branding.edit", "app.reset")


def doc_perms(t):
    return [f"{t}.{a}" for a, _, _ in DOC_ACTIONS if a != "folders" or t in FOLDER_TYPES]


ALL = tuple(p for t in TYPES for p in doc_perms(t)) + tuple(k for k, _ in GLOBAL)
ALL_SET = frozenset(ALL)


def expand(perms):
    """Lista gravada no papel → conjunto efetivo ("*" = todas; nomes desconhecidos são ignorados)."""
    perms = list(perms or [])
    return ALL_SET if "*" in perms else frozenset(p for p in perms if p in ALL_SET)


def clean(perms):
    """Normaliza o que vem da interface: só permissões conhecidas, sem repetição, em ordem do catálogo."""
    s = set(perms or [])
    return [p for p in ALL if p in s]


def _viewer():
    return [p for t in TYPES for p in (f"{t}.view", f"{t}.suggest", f"{t}.export")]


def _editor():
    out = _viewer()
    for t in TYPES:
        out += [f"{t}.{a}" for a in ("view_drafts", "create", "edit", "status", "approve", "restore", "import")]
    return clean(out + ["runbook.folders", "doc.folders", "templates.view", "templates.edit"])


SEED_ROLES = [
    {"key": "admin", "name": "Administrador", "description": "Tudo, inclusive usuários, roles e configurações. Não pode ser alterado.",
     "priority": 100, "permissions": ["*"]},
    {"key": "editor", "name": "Editor", "description": "Lê, cria e edita todos os documentos, muda status e edita templates.",
     "priority": 50, "permissions": _editor()},
    {"key": "viewer", "name": "Visualizador", "description": "Lê e exporta documentos em Homologação e Produção.",
     "priority": 10, "permissions": _viewer()},
]
SYSTEM_KEYS = tuple(r["key"] for r in SEED_ROLES)
DEFAULTS = {r["key"]: r for r in SEED_ROLES}


def legacy_role(role_id):
    """Espelho na coluna antiga users.role (lida pela 2.x num rollback): papel personalizado vira Visualizador."""
    return role_id if role_id in ("admin", "editor") else "viewer"


def catalog():
    """Para a tela de papéis: tipos habilitados, ações por tipo e permissões globais."""
    return {"types": [{"key": t, "label": TYPE_LABELS[t], "perms": doc_perms(t)} for t in ENABLED_TYPES],
            "actions": [{"key": a, "label": l, "help": h} for a, l, h in DOC_ACTIONS],
            "global": [{"key": k, "label": l} for k, l in GLOBAL]}
