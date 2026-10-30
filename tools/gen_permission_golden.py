#!/usr/bin/env python3
"""Matriz "dourada" de permissões: para cada rota de ROUTES e cada papel (anônimo, visualizador, editor,
administrador), faz a chamada com corpo mínimo e grava o status HTTP.

  python3 tools/gen_permission_golden.py --app-dir <código da tag base> [--out tests/golden/permissoes-2.1.json]

O arquivo é gerado UMA vez com o código da tag base (v2.1.x-base); o teste tests/test_permissoes_golden.py
roda a mesma coleta no código atual e compara. Corpo mínimo = {} (mais a revisão atual do playbook ou do
template, para a resposta não depender de "rev" ser obrigatório ou não).
"""
import argparse, json, os, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
import helpers as H  # noqa: E402

ROLES = ("anon", "viewer", "editor", "admin")
PIDS = ("PB-01", "PB-02")          # PB-01 em Desenvolvimento, PB-02 em Produção
FAKE_USER, FAKE_RAMO, FAKE_IMG = "ninguem", "R99", "img-0000000000000000.png"


def routes_of(app_dir, home):
    env = {**os.environ, "MEDUSA_HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
    out = subprocess.run([sys.executable, "-c", "import json, server; print(json.dumps(sorted(m + ' ' + p for m, p in server.ROUTES)))"],
                         cwd=app_dir, env=env, capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def setup(app):
    """Estado conhecido: 2 playbooks (Desenvolvimento e Produção), um usuário por papel e um aprovador."""
    admin = app.admin()
    clients = {"anon": app.client(), "viewer": app.make_user("viewer"), "editor": app.make_user("editor"), "admin": admin}
    app.make_user("editor", login="aprovador.teste")
    H.create_playbook(admin, "PB-01", "Teste de phishing")
    H.create_playbook(admin, "PB-02", "Teste de malware")
    ed = clients["editor"]
    for st, extra in (("Homologação", {}), ("Produção", {"approver": "aprovador.teste"})):
        rev = admin.get("/api/pb/PB-02").json()["playbook"]["rev"]
        r = ed.put("/api/pb/PB-02/status", {"status": st, "rev": rev, **extra})
        if r.status != 200: raise AssertionError(f"PB-02 → {st}: {r}")
    return clients


def pb_rev(admin, pid):
    r = admin.get(f"/api/pb/{pid}")
    return r.json()["playbook"]["rev"] if r.status == 200 else None


def tpl_rev(admin):
    return admin.get("/api/templates/padrao").json()["template"]["rev"]


def first_version(admin, pid):
    vs = admin.get(f"/api/pb/{pid}/versions").json()["versions"]
    return min(v["id"] for v in vs)


def call(app, clients, role, method, path, body):
    if method == "POST" and path == "/api/logout" and role != "anon":
        # sessão descartável: sair não pode derrubar o cliente usado no resto da coleta
        c = app.client()
        c.login(clients[role].login_name if role != "admin" else H.ADMIN_LOGIN, H.USER_PASSWORD if role != "admin" else app.admin_password)
        return c.req(method, path, body).status
    return clients[role].req(method, path, body if method != "GET" else None).status


def collect(app_dir, routes=None):
    app = H.TempApp(app_dir=app_dir).start()
    try:
        routes = routes or routes_of(app_dir, app.home)
        clients = setup(app)
        admin = clients["admin"]
        out = {}
        for key in routes:
            method, pattern = key.split(" ", 1)
            for pid in (PIDS if "{pb}" in pattern else (None,)):
                path = pattern.replace("{u}", FAKE_USER).replace("{t}", "padrao").replace("{r}", FAKE_RAMO).replace("{f}", FAKE_IMG)
                if pid:
                    path = path.replace("{pb}", pid)
                    if "{v}" in path: path = path.replace("{v}", str(first_version(admin, pid)))
                res = {}
                for role in ROLES:
                    body = {}
                    if pid: body["rev"] = pb_rev(admin, pid)
                    elif pattern.startswith("/api/templates/{t}"): body["rev"] = tpl_rev(admin)
                    res[role] = call(app, clients, role, method, path, body)
                out[key + (f"#{pid}" if pid else "")] = res
        # cenário extra (por último, porque troca o PB-01): o editor substitui um playbook pelo Importar.
        # Mudança intencional a partir da Fase 1: passa a exigir a permissão de excluir (403 para o editor).
        text = admin.get("/api/pb/PB-01/export?fmt=medusa").body.decode("utf-8")
        r = clients["editor"].post("/api/import", {"text": text, "id": "PB-01", "mode": "replace", "template": "padrao"})
        out["POST /api/import#replace"] = {"editor": r.status}
        return out
    finally:
        app.cleanup()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--app-dir", required=True, help="pasta com o código da tag base (git worktree)")
    p.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "tests" / "golden" / "permissoes-2.1.json"))
    a = p.parse_args()
    res = collect(Path(a.app_dir).resolve())
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"base": H.BASE_TAG, "statuses": res}, ensure_ascii=False, indent=1, sort_keys=True) + "\n", "utf-8")
    print(f"{len(res)} chamadas gravadas em {a.out}")


if __name__ == "__main__":
    main()
