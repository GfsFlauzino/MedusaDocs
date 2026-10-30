#!/usr/bin/env python3
"""Gera tests/fixtures/playbooks-v3.db com o código da tag base: 3 usuários (um por papel), sessões,
auditoria e 5 versões do PB-01. Usado por tests/test_migracao.py (migração e rollback).

  python3 tools/gen_db_fixture.py --app-dir <código da tag base>
"""
import argparse, json, shutil, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import helpers as H  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--app-dir", required=True)
    a = p.parse_args()
    app = H.TempApp(app_dir=Path(a.app_dir).resolve()).start()
    try:
        admin = app.admin()
        viewer, editor = app.make_user("viewer"), app.make_user("editor")
        H.create_playbook(admin, "PB-01", "Teste de phishing")                       # versão 1: criação
        for i in range(3):                                                          # versões 2 a 4: documento
            pb = editor.get("/api/pb/PB-01").json()["playbook"]
            doc = pb["doc"]; doc["sections"][1]["blocks"].append({"t": "p", "text": f"Parágrafo de teste {i + 1}."})
            r = editor.put("/api/pb/PB-01/doc", {"doc": doc, "rev": pb["rev"]}); assert r.status == 200, r
        pb = editor.get("/api/pb/PB-01").json()["playbook"]                          # versão 5: status
        r = editor.put("/api/pb/PB-01/status", {"status": "Homologação", "rev": pb["rev"]}); assert r.status == 200, r
        admin.put("/api/branding", {"name": "SOC Teste"})
        token = viewer.token()
    finally:
        app.stop()
    src = app.home / "data" / "playbooks.db"
    c = sqlite3.connect(src); c.execute("PRAGMA wal_checkpoint(TRUNCATE)"); c.execute("PRAGMA journal_mode = DELETE")
    counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("users", "sessions", "audit", "pb_versions", "settings")}
    ver = c.execute("PRAGMA user_version").fetchone()[0]
    c.close()
    out = ROOT / "tests" / "fixtures"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, out / "playbooks-v3.db")
    (out / "playbooks-v3.json").write_text(json.dumps({
        "user_version": ver, "counts": counts, "viewer_token": token,
        "logins": {H.ADMIN_LOGIN: app.admin_password, "viewer.teste": H.USER_PASSWORD, "editor.teste": H.USER_PASSWORD},
        "roles": {H.ADMIN_LOGIN: "admin", "viewer.teste": "viewer", "editor.teste": "editor"},
    }, indent=1) + "\n", "utf-8")
    app.cleanup()
    print("fixture gravada:", counts, "user_version", ver)


if __name__ == "__main__":
    main()
