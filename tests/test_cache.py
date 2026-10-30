"""Cache de documentos (library.py): conteúdo novo aparece após edição externa, gravação pela API e gravações
concorrentes."""
import threading, time, unittest

import helpers as H


class Cache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = H.TempApp().start()
        cls.admin = cls.app.admin()
        H.create_playbook(cls.admin, "PB-01", "Teste de cache")

    @classmethod
    def tearDownClass(cls):
        cls.app.cleanup()

    def pb(self):
        return self.admin.get("/api/doc/PB-01").json()["playbook"]

    def test_edicao_externa_aparece_em_ate_2s(self):
        md = next((self.app.home / "playbooks").glob("PB-01-*/*.md"))
        self.pb()                                               # aquece o cache
        text = md.read_text("utf-8")
        md.write_text("# PB-01 — Editado por fora\n" + text.split("\n", 1)[1], "utf-8")
        deadline, name = time.time() + 2.0, None
        while time.time() < deadline:
            name = self.pb()["name"]
            if name == "Editado por fora": break
            time.sleep(0.1)
        self.assertEqual(name, "Editado por fora")
        items = self.admin.get("/api/library").json()["items"]
        self.assertEqual(items[0]["name"], "Editado por fora")
        md.write_text(text, "utf-8")
        time.sleep(1.1)

    def test_gravacao_pela_api_aparece_na_hora(self):
        pb = self.pb()
        doc = pb["doc"]; doc["title"] = "PB-01 — Gravado pela API"
        r = self.admin.put("/api/pb/PB-01/doc", {"doc": doc, "rev": pb["rev"]})
        self.assertEqual(r.status, 200, r)
        self.assertEqual(self.pb()["name"], "Gravado pela API")
        self.assertEqual(self.admin.get("/api/library").json()["items"][0]["name"], "Gravado pela API")
        hits = self.admin.get("/api/search?q=gravado%20pela%20api").json()["hits"]
        self.assertTrue(any(h["pid"] == "PB-01" and h["kind"] == "documento" for h in hits))

    def test_dois_clientes_gravando_ao_mesmo_tempo(self):
        ed = self.app.make_user("editor", login="editor.cache")
        pb = self.pb()
        res = []
        def save(c, title):
            doc = dict(pb["doc"]); doc["title"] = f"PB-01 — {title}"
            res.append((title, c.put("/api/pb/PB-01/doc", {"doc": doc, "rev": pb["rev"]}).status))
        ts = [threading.Thread(target=save, args=(c, t)) for c, t in ((self.admin, "Cliente A"), (ed, "Cliente B"))]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual(sorted(st for _, st in res), [200, 409], res)
        winner = next(t for t, st in res if st == 200)
        self.assertEqual(self.pb()["name"], winner)
        self.assertEqual(self.admin.get("/api/library").json()["items"][0]["name"], winner)


if __name__ == "__main__":
    unittest.main()
