"""Citações entre documentos ("Referenciado por") e verificação de pendências do playbook (Fase 7)."""
import unittest

import helpers as H


class Citacoes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = H.TempApp().start()
        cls.admin = cls.app.admin()
        cls.viewer = cls.app.make_user("viewer")
        H.create_playbook(cls.admin, "PB-01", "Phishing")
        H.create_playbook(cls.admin, "PB-02", "Malware")
        pb = cls.admin.get("/api/doc/PB-02").json()["playbook"]
        doc = pb["doc"]; doc["sections"][2]["blocks"].append({"t": "p", "text": "Ver também PB-01 e o PB-99, que ainda não existe."})
        assert cls.admin.put("/api/doc/PB-02/doc", {"doc": doc, "rev": pb["rev"]}).status == 200
        rev = cls.admin.get("/api/doc/PB-01").json()["playbook"]["rev"]
        assert cls.admin.put("/api/doc/PB-01/status", {"status": "Homologação", "rev": rev}).status == 200

    @classmethod
    def tearDownClass(cls):
        cls.app.cleanup()

    def test_links_nos_dois_sentidos(self):
        out = self.admin.get("/api/doc/PB-02/links").json()["out"]
        self.assertEqual([x["id"] for x in out], ["PB-01", "PB-99"])
        self.assertTrue(out[1]["missing"])
        inc = self.admin.get("/api/doc/PB-01/links").json()["in"]
        self.assertEqual([x["id"] for x in inc], ["PB-02"])

    def test_links_respeitam_a_visibilidade(self):
        self.assertEqual(self.viewer.get("/api/doc/PB-01/links").json()["in"], [])      # PB-02 em Desenvolvimento
        self.assertEqual(self.viewer.get("/api/doc/PB-02/links").status, 404)

    def test_lint(self):
        d = self.admin.get("/api/doc/PB-02/lint").json()
        self.assertEqual(d["count"], len(d["issues"]))
        self.assertIn(("ref", "PB-99"), [(i["kind"], i.get("ref")) for i in d["issues"]])
        self.assertEqual(self.viewer.get("/api/doc/PB-01/lint").status, 403)


if __name__ == "__main__":
    unittest.main()
