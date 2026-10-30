"""Tipos de documento, pastas, campos e templates por tipo (Fase 4)."""
import hashlib, json, sqlite3, sys, tempfile, unittest
from pathlib import Path

import helpers as H

sys.path.insert(0, str(H.APP_DIR))
import store  # noqa: E402

ONE_LANE = {"subtitle": "", "lanes": [{"key": "n1", "label": "SOC N1", "team": "SOC N1", "color": "#1D62D1", "kind": "team"}],
            "nodes": [{"id": "a", "lane": "n1", "x": 60, "y": 30, "w": 96, "h": 48, "type": "start", "lines": [{"t": "Início", "s": "n"}]}],
            "edges": []}


def rev(c, pid):
    return c.get(f"/api/doc/{pid}").json()["playbook"]["rev"]


class Tipos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = H.TempApp().start()
        cls.admin = cls.app.admin()
        H.create_playbook(cls.admin, "PB-01", "Phishing")
        r = cls.admin.post("/api/doc", {"type": "runbook", "name": "Isolar host no EDR", "fields": {"ferramenta": "EDR", "fase_nist": "Detecção e Análise"}})
        assert r.status == 200, r
        cls.rb = r.json()["playbook"]
        r = cls.admin.post("/api/doc", {"type": "doc", "name": "Política de resposta", "fields": {"categoria": "Política", "publico": ["SOC", "CSIRT"]}})
        assert r.status == 200, r
        cls.doc = r.json()["playbook"]

    @classmethod
    def tearDownClass(cls):
        cls.app.cleanup()

    def test_ids_e_tipos(self):
        self.assertEqual((self.rb["id"], self.rb["type"], self.rb["hasFlow"]), ("RB-01", "runbook", False))
        self.assertEqual((self.doc["id"], self.doc["type"]), ("DOC-01", "doc"))
        self.assertEqual(self.admin.get("/api/doc/next-id?type=runbook").json()["id"], "RB-02")
        items = {i["id"]: i for i in self.admin.get("/api/library?type=runbook").json()["items"]}
        self.assertEqual(items["RB-01"]["fields"]["ferramenta"], "EDR")
        self.assertEqual(set(items), {"RB-01"} | ({"RB-05"} & set(items)) | ({"RB-02"} & set(items)))
        self.assertTrue((self.app.home / "runbooks").is_dir() and (self.app.home / "documentos").is_dir())

    def test_runbook_sem_fluxograma_depois_com(self):
        r = self.admin.post("/api/doc", {"type": "runbook", "name": "Bloquear usuário", "fields": {"ferramenta": "Identidade"}})
        pid = r.json()["playbook"]["id"]
        self.assertEqual(self.admin.get(f"/api/pb/{pid}/export?fmt=drawio").status, 400)
        r = self.admin.put(f"/api/doc/{pid}/flow", {"flow": ONE_LANE, "refs": {}, "rev": rev(self.admin, pid)})
        self.assertEqual(r.status, 200, r)
        self.assertTrue(self.admin.get(f"/api/doc/{pid}").json()["playbook"]["hasFlow"])
        self.assertEqual(self.admin.post(f"/api/doc/{pid}/ramos", {"name": "x", "rev": rev(self.admin, pid)}).status, 400)

    def test_documento_sem_fluxograma_e_sem_aprovador(self):
        pid = self.doc["id"]
        self.assertEqual(self.admin.put(f"/api/doc/{pid}/flow", {"flow": ONE_LANE, "refs": {}, "rev": rev(self.admin, pid)}).status, 400)
        for st in ("Homologação", "Produção"):
            r = self.admin.put(f"/api/doc/{pid}/status", {"status": st, "rev": rev(self.admin, pid)})
            self.assertEqual(r.status, 200, r)

    def test_pastas(self):
        a = self.admin.post("/api/folders", {"type": "runbook", "name": "Por ferramenta"}).json()["folder"]
        b = self.admin.post("/api/folders", {"type": "runbook", "name": "EDR", "parent_id": a["id"]}).json()["folder"]
        self.assertEqual(self.admin.put(f"/api/doc/RB-01/folder", {"folder_id": b["id"]}).status, 200)
        lib = lambda q: [i["id"] for i in self.admin.get("/api/library?type=runbook&" + q).json()["items"]]
        self.assertEqual(lib(f"folder={b['id']}"), ["RB-01"])
        self.assertEqual(lib(f"folder={a['id']}"), [])
        self.assertEqual(lib(f"folder={a['id']}&recursive=1"), ["RB-01"])
        self.assertNotIn("RB-01", lib("folder=none"))
        tree = self.admin.get("/api/folders?type=runbook").json()
        self.assertEqual(next(f for f in tree["folders"] if f["id"] == a["id"])["total"], 1)
        self.assertEqual(self.admin.put(f"/api/folders/{a['id']}", {"parent_id": b["id"]}).status, 400)          # ciclo
        self.assertEqual(self.admin.delete(f"/api/folders/{b['id']}").status, 400)                              # cheia
        self.assertEqual(self.admin.post("/api/folders", {"type": "playbook", "name": "X"}).status, 400)        # playbook não usa pastas
        r = self.admin.post("/api/folders/from-template", {"type": "runbook"}).json()
        self.assertGreaterEqual(r["created"], 5)
        self.assertEqual(self.admin.post("/api/folders/from-template", {"type": "runbook"}).json()["created"], 0)   # idempotente
        audit = [e["action"] for e in self.admin.get("/api/audit?q=documento_movido").json()["entries"]]
        self.assertIn("documento_movido", audit)

    def test_facetas(self):
        d = self.admin.get("/api/library?type=runbook").json()
        edr = sum(1 for i in d["items"] if i["fields"]["ferramenta"] == "EDR")
        self.assertEqual(d["facets"]["ferramenta"]["values"].get("EDR"), edr)
        ids = [i["id"] for i in self.admin.get("/api/library?type=runbook&fields.ferramenta=EDR").json()["items"]]
        self.assertIn("RB-01", ids)
        self.assertEqual(len(ids), edr)

    def test_papel_que_edita_so_runbooks(self):
        key = self.admin.post("/api/roles", {"name": "Só runbooks", "permissions": ["runbook.view", "runbook.view_drafts", "runbook.edit",
                                                                                     "playbook.view", "doc.view"]}).json()["role"]["key"]
        c = self.app.make_user(key, login="so.runbooks")
        pb = c.get("/api/doc/RB-01").json()["playbook"]
        self.assertEqual(c.put("/api/doc/RB-01/doc", {"doc": pb["doc"], "rev": pb["rev"]}).status, 200)
        for pid in ("PB-01", "DOC-01"):
            self.assertEqual(c.put(f"/api/doc/{pid}/doc", {"doc": pb["doc"], "rev": "x"}).status, 403)
        self.assertEqual(c.post("/api/folders", {"type": "runbook", "name": "Não pode"}).status, 403)

    def test_exportar_e_importar_runbook_com_pasta_e_campos(self):
        f = self.admin.post("/api/folders", {"type": "runbook", "name": "Exportados"}).json()["folder"]
        self.admin.put("/api/doc/RB-01/folder", {"folder_id": f["id"]})
        text = self.admin.get("/api/doc/RB-01/export?fmt=medusa").body.decode()
        self.assertIn("type: runbook", text)
        self.assertIn("folder: Exportados", text)
        self.assertNotIn("medusa:flow", text)
        self.admin.delete(f"/api/folders/{f['id']}", {"moveTo": None})
        r = self.admin.post("/api/import", {"text": text, "id": "RB-05"})
        self.assertEqual(r.status, 200, r)
        new = {i["id"]: i for i in self.admin.get("/api/library?type=runbook").json()["items"]}["RB-05"]
        self.assertEqual(new["fields"]["ferramenta"], "EDR")
        self.assertEqual(self.admin.get("/api/folders?type=runbook").json()["folders"][-1]["name"], "Exportados")
        self.assertEqual(self.admin.post("/api/import", {"text": text, "id": "PB-09"}).status, 400)          # tipo do ID ≠ arquivo/template

    def test_templates_por_tipo(self):
        ts = {t["key"]: t for t in self.admin.get("/api/templates?kind=runbook").json()["templates"]}
        self.assertEqual(set(ts), {"runbook-padrao"})
        self.assertEqual(self.admin.delete("/api/templates/runbook-padrao").status, 400)
        r = self.admin.post("/api/templates", {"name": "Runbook de rede", "kind": "runbook"})
        t = r.json()["template"]
        self.assertEqual((t["kind"], t["hasFlow"]), ("runbook", False))
        r = self.admin.put(f"/api/templates/{t['key']}/meta", {"rev": t["rev"], "fields": [
            {"key": "vlan", "label": "VLAN", "type": "text"}, {"key": "zona", "label": "Zona", "type": "select", "options": ["DMZ", "Interna"], "filter": True}],
            "folders": ["Rede/Firewall", "Rede/Switch"]})
        self.assertEqual(r.status, 200, r)
        self.assertEqual([f["key"] for f in r.json()["template"]["fields"]], ["vlan", "zona"])
        bad = self.admin.put(f"/api/templates/{t['key']}/meta", {"rev": r.json()["template"]["rev"], "fields": [{"key": "1x", "label": "x"}]})
        self.assertEqual(bad.status, 400)
        self.assertEqual(self.admin.put(f"/api/templates/documento-padrao/flow", {"flow": ONE_LANE, "refs": {}, "rev": "x"}).status, 400)


class ArquivosAntigos(unittest.TestCase):
    def test_playbooks_existentes_nao_mudam_no_boot(self):
        app = H.TempApp().start()
        try:
            H.create_playbook(app.admin(), "PB-01", "Antigo")
            files = sorted((app.home / "playbooks").rglob("*.*"))
            h = lambda: {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
            before = h()
            app.stop(); app.start()
            self.assertEqual(app.client().get("/api/branding").status, 200)
            c = app.client(); c.login(H.ADMIN_LOGIN, app.admin_password)
            self.assertEqual(c.get("/api/pb/PB-01").status, 200)
            self.assertEqual(c.get("/api/doc/PB-01").status, 200)
            self.assertEqual(h(), before)
        finally:
            app.cleanup()


class MigracaoV5(unittest.TestCase):
    def test_banco_v4_vira_v5(self):
        d = Path(tempfile.mkdtemp())
        db = d / "playbooks.db"
        full = list(store.MIGRATIONS)
        try:
            store.MIGRATIONS[:] = full[:4]
            s4 = store.Store(db)
            s4.create_user("ana.teste", "Ana", "editor", "x", must_change=False)
        finally:
            store.MIGRATIONS[:] = full
        c = sqlite3.connect(db); self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 4); c.close()
        s5 = store.Store(db)
        self.assertEqual(s5.get_user("ana.teste")["role_id"], "editor")
        c = sqlite3.connect(db)
        self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 5)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM folders").fetchone()[0], 0)
        c.close()
        self.assertTrue(list((d / "backups").glob("playbooks.db.pre-v4-v5-*")))


if __name__ == "__main__":
    unittest.main()
