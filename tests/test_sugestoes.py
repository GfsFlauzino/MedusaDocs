"""Sugestões de alteração: quem lê propõe, quem edita aceita (aplicando no documento) ou recusa."""
import unittest

import helpers as H


def rev(c, pid):
    return c.get(f"/api/doc/{pid}").json()["playbook"]["rev"]


class Sugestoes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = H.TempApp().start()
        cls.admin = cls.app.admin()
        cls.viewer = cls.app.make_user("viewer")
        cls.editor = cls.app.make_user("editor")
        H.create_playbook(cls.admin, "PB-01", "Phishing")
        pb = cls.admin.get("/api/doc/PB-01").json()["playbook"]
        doc = pb["doc"]
        cls.sec = next(s for s in doc["sections"] if s["title"].startswith("Objetivo"))
        cls.sec["blocks"].append({"t": "p", "text": "Isolar o **host afetado** antes de coletar evidências."})
        assert cls.admin.put("/api/doc/PB-01/doc", {"doc": doc, "rev": pb["rev"]}).status == 200
        assert cls.admin.put("/api/doc/PB-01/status", {"status": "Homologação", "rev": rev(cls.admin, "PB-01")}).status == 200
        cls.anchor = "objetivo-e-escopo"

    @classmethod
    def tearDownClass(cls):
        cls.app.cleanup()

    def suggest(self, c=None, **body):
        return (c or self.viewer).post("/api/doc/PB-01/suggestions", {"anchor": self.anchor, **body})

    def test_aceitar_aplica_mesmo_com_formatacao(self):
        r = self.suggest(quote="host afetado antes", proposal="servidor afetado e a conta antes", comment="Inclui a conta")
        self.assertEqual(r.status, 200, r)
        sid = r.json()["suggestion"]["id"]
        self.assertEqual(self.viewer.post(f"/api/doc/PB-01/suggestions/{sid}/accept", {"apply": True}).status, 403)
        r = self.editor.post(f"/api/doc/PB-01/suggestions/{sid}/accept", {"apply": True, "rev": rev(self.editor, "PB-01")})
        self.assertEqual(r.status, 200, r)
        md = self.admin.get("/api/doc/PB-01/export?fmt=md").body.decode()
        self.assertIn("Isolar o **servidor afetado e a conta antes de coletar evidências.", md)
        vs = self.admin.get("/api/doc/PB-01/versions").json()["versions"]
        self.assertEqual(vs[0]["kind"], "sugestao")
        self.assertIn(f"Sugestão #{sid}", vs[0]["note"])
        self.assertEqual(self.editor.post(f"/api/doc/PB-01/suggestions/{sid}/reject", {}).status, 409)     # já resolvida

    def test_acrescentar_no_fim_da_secao(self):
        sid = self.suggest(proposal="1. Avisar o gestor do usuário.\n2. Registrar no caso.").json()["suggestion"]["id"]
        r = self.admin.post(f"/api/doc/PB-01/suggestions/{sid}/accept", {"apply": True, "rev": rev(self.admin, "PB-01")})
        self.assertEqual(r.status, 200, r)
        sec = next(s for s in r.json()["playbook"]["doc"]["sections"] if s["title"].startswith("Objetivo"))
        self.assertEqual(sec["blocks"][-1]["t"], "ol")

    def test_trecho_que_nao_existe_ou_repete(self):
        sid = self.suggest(quote="texto que não está lá", proposal="x").json()["suggestion"]["id"]
        r = self.editor.post(f"/api/doc/PB-01/suggestions/{sid}/accept", {"apply": True, "rev": rev(self.editor, "PB-01")})
        self.assertEqual(r.status, 409)
        self.assertEqual(self.editor.post(f"/api/doc/PB-01/suggestions/{sid}/accept", {"note": "Aplico à mão"}).status, 200)

    def test_recusar_e_retirar(self):
        a = self.suggest(comment="Faltou citar o RB do EDR").json()["suggestion"]["id"]
        self.assertEqual(self.editor.post(f"/api/doc/PB-01/suggestions/{a}/reject", {"note": "Já está no PB-02"}).status, 200)
        b = self.suggest(comment="Rascunho").json()["suggestion"]["id"]
        self.assertEqual(self.editor.post(f"/api/doc/PB-01/suggestions/{b}/withdraw", {}).status, 403)      # não é o autor
        self.assertEqual(self.viewer.post(f"/api/doc/PB-01/suggestions/{b}/withdraw", {}).status, 200)
        todas = {x["id"]: x for x in self.viewer.get("/api/doc/PB-01/suggestions?status=todas").json()["suggestions"]}
        self.assertEqual((todas[a]["status"], todas[a]["resolution_note"]), ("recusada", "Já está no PB-02"))
        self.assertEqual(todas[b]["status"], "retirada")
        abertas = [x["id"] for x in self.viewer.get("/api/doc/PB-01/suggestions").json()["suggestions"]]
        self.assertNotIn(a, abertas)

    def test_validacoes_e_permissoes(self):
        self.assertEqual(self.suggest().status, 400)                                        # nem texto nem comentário
        self.assertEqual(self.suggest(anchor="nao-existe", comment="x").status, 400)
        key = self.admin.post("/api/roles", {"name": "Só lê", "permissions": ["playbook.view"]}).json()["role"]["key"]
        c = self.app.make_user(key, login="so.le")
        self.assertEqual(self.suggest(c, comment="x").status, 403)
        lib = {i["id"]: i for i in self.editor.get("/api/library").json()["items"]}
        self.assertGreaterEqual(lib["PB-01"]["suggestions"], 0)


if __name__ == "__main__":
    unittest.main()
