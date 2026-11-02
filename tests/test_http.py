"""Camada HTTP e endurecimento (Fase 1): keep-alive, gzip, ETag/304, estáticos versionados, rotas novas,
revisão obrigatória, limites do fluxograma, sessão e importação com substituição."""
import gzip, http.client, json, re, time, unittest, urllib.parse

import helpers as H


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = H.TempApp().start()
        cls.admin = cls.app.admin()
        H.create_playbook(cls.admin, "PB-01", "Phishing de credenciais")
        H.create_playbook(cls.admin, "PB-02", "Malware")
        cls.viewer = cls.app.make_user("viewer")
        cls.editor = cls.app.make_user("editor")

    @classmethod
    def tearDownClass(cls):
        cls.app.cleanup()

    def test_keep_alive_e_content_length(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.app.port, timeout=5)
        for _ in range(3):
            conn.request("GET", "/api/branding")
            r = conn.getresponse(); body = r.read()
            self.assertEqual(r.status, 200)
            self.assertEqual(int(r.getheader("Content-Length")), len(body))
            self.assertFalse(r.will_close)
        conn.close()

    def test_gzip_e_etag_na_lista(self):
        r = self.admin.get("/api/library", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers.get("Content-Encoding"), "gzip")
        data = json.loads(gzip.decompress(r.body))
        self.assertEqual([i["id"] for i in data["items"]], ["PB-01", "PB-02"])
        self.assertEqual(set(data["items"][0]) >= {"id", "type", "slug", "name", "status", "version", "templateKey", "templateName",
                                                   "reviewed", "reviewer", "ramos", "steps", "rev", "gov"}, True)
        et = r.headers.get("ETag")
        r2 = self.admin.get("/api/library", headers={"If-None-Match": et})
        self.assertEqual(r2.status, 304)
        self.assertEqual(r2.body, b"")

    def test_etag_no_detalhe_muda_ao_gravar(self):
        r = self.admin.get("/api/doc/PB-02")
        et = r.headers.get("ETag")
        self.assertEqual(self.admin.get("/api/doc/PB-02", headers={"If-None-Match": et}).status, 304)
        pb = r.json()["playbook"]
        self.assertEqual(self.admin.put("/api/doc/PB-02/doc", {"doc": pb["doc"], "rev": pb["rev"]}).status, 200)
        self.assertEqual(self.admin.get("/api/doc/PB-02", headers={"If-None-Match": et}).status, 200)

    def test_bootstrap(self):
        b = self.viewer.get("/api/bootstrap").json()
        self.assertEqual(b["user"]["login"], "viewer.teste")
        self.assertTrue({"branding", "catalog", "statuses", "teams", "appVersion"} <= set(b))
        self.assertNotIn("playbooks", b)

    def test_login_avisa_antes_de_bloquear(self):
        c = self.app.client()
        msgs = [c.post("/api/login", {"login": "bloqueio.teste", "password": "errada"}) for _ in range(6)]
        self.assertEqual([r.status for r in msgs], [401, 401, 401, 401, 429, 429])
        self.assertNotIn("tentativa", msgs[1].json()["error"])
        self.assertIn("Mais 2 tentativas", msgs[2].json()["error"])
        self.assertIn("Mais 1 tentativa errada", msgs[3].json()["error"])
        self.assertIn("foi bloqueado por 5 min", msgs[4].json()["error"])
        self.assertIn("Tente de novo em", msgs[5].json()["error"])

    def test_contato_de_acesso_na_marca(self):
        self.assertEqual(self.admin.put("/api/branding", {"contact": "  Plantão SOC   ramal 4400 "}).status, 200)
        self.assertEqual(self.app.client().get("/api/branding").json()["contact"], "Plantão SOC ramal 4400")
        self.admin.put("/api/branding", {"name": "Outro nome"})              # sem contact no corpo: mantém o que havia
        self.assertEqual(self.app.client().get("/api/branding").json()["contact"], "Plantão SOC ramal 4400")
        self.admin.put("/api/branding", {"contact": "", "name": "Medusa Docs"})

    def test_visibilidade_na_lista_e_na_busca(self):
        self.assertEqual(self.viewer.get("/api/library").json()["items"], [])     # os dois em Desenvolvimento
        self.assertEqual(self.viewer.get("/api/search?q=phishing").json()["hits"], [])
        hits = self.editor.get("/api/search?q=phishing").json()["hits"]
        self.assertEqual(hits[0]["pid"], "PB-01")
        self.assertEqual(self.viewer.get("/api/doc/PB-01").status, 404)

    def test_busca_sem_acento_e_por_passo(self):
        hits = self.editor.get("/api/search?q=triagem").json()["hits"]
        self.assertTrue(any(h["kind"] == "secao" for h in hits))
        hits = self.editor.get("/api/search?q=CONFIRMAR%20ADERENCIA").json()["hits"]   # "Confirmar aderência" (T1)
        self.assertTrue(any(h["kind"] == "passo" and h["anchor"] == "T1" for h in hits), hits)

    def test_paginacao_e_filtros(self):
        d = self.editor.get("/api/library?limit=1").json()
        self.assertEqual((len(d["items"]), d["total"], d["nextCursor"]), (1, 2, "1"))
        d2 = self.editor.get("/api/library?limit=1&cursor=1").json()
        self.assertEqual((d2["items"][0]["id"], d2["nextCursor"]), ("PB-02", None))
        self.assertEqual(self.editor.get("/api/library?status=" + urllib.parse.quote("Produção")).json()["total"], 0)
        self.assertEqual(self.editor.get("/api/library?q=malware").json()["items"][0]["id"], "PB-02")
        self.assertEqual(self.editor.get("/api/library?sort=xyz").status, 400)

    def test_estaticos_versionados(self):
        r = self.app.client().get("/")
        html = r.body.decode()
        m = re.search(r'src="app\.js\?v=([\w.-]+)"', html)
        self.assertTrue(m, "index.html sem ?v= no app.js")
        self.assertIn("no-cache", r.headers.get("Cache-Control"))
        r2 = self.app.client().get(f"/app.js?v={m.group(1)}", headers={"Accept-Encoding": "gzip"})
        self.assertIn("immutable", r2.headers.get("Cache-Control"))
        self.assertEqual(r2.headers.get("Content-Encoding"), "gzip")

    def test_revisao_obrigatoria(self):
        pb = self.admin.get("/api/doc/PB-01").json()["playbook"]
        r = self.admin.put("/api/pb/PB-01/doc", {"doc": pb["doc"]})
        self.assertEqual(r.status, 400)
        self.assertIn("revisão", r.json()["error"])
        r = self.admin.put("/api/pb/PB-01/status", {"status": "Homologação"})
        self.assertEqual(r.status, 400)

    def test_limites_do_fluxograma(self):
        pb = self.admin.get("/api/doc/PB-01").json()["playbook"]
        flow = json.loads(json.dumps(pb["flow"]))
        flow["edges"][0].pop("id")
        r = self.admin.put("/api/pb/PB-01/flow", {"flow": flow, "refs": pb["refs"], "rev": pb["rev"]})
        self.assertEqual(r.status, 400)
        flow = json.loads(json.dumps(pb["flow"]))
        flow["nodes"][0]["lines"] = [{"t": "x" * 501, "s": "n"}]
        self.assertEqual(self.admin.put("/api/pb/PB-01/flow", {"flow": flow, "refs": pb["refs"], "rev": pb["rev"]}).status, 400)

    def test_content_length_negativo(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.app.port, timeout=5)
        conn.putrequest("POST", "/api/login"); conn.putheader("X-Requested-With", "playbooks"); conn.putheader("Content-Length", "-5")
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 400)
        conn.close()

    def test_cookie_renovado(self):
        c = self.app.client()
        c.login("viewer.teste", H.USER_PASSWORD)
        r1 = c.get("/api/me"); r2 = c.get("/api/me")
        self.assertRegex(r1.headers.get("Set-Cookie") or "", r"pbsid=.*Max-Age=\d+")
        self.assertIsNone(r2.headers.get("Set-Cookie"))     # no máximo a cada 10 min

    def test_importar_substituindo_exige_administrador(self):
        text = self.admin.get("/api/pb/PB-02/export?fmt=medusa").body.decode()
        r = self.editor.post("/api/import", {"text": text, "id": "PB-02", "mode": "replace", "template": "padrao"})
        self.assertEqual(r.status, 403)
        self.assertEqual(self.editor.post("/api/import", {"text": text, "id": "PB-02", "template": "padrao", "dryRun": True}).status, 200)

    def test_previa_da_retencao(self):
        r = self.admin.get("/api/logs/retention-preview?days=7")
        self.assertEqual(r.status, 200)
        self.assertEqual(set(r.json()), {"days", "events", "files"})
        self.assertEqual(r.json()["events"], 0)          # tudo o que existe foi registrado agora
        self.assertEqual(self.admin.get("/api/logs/retention-preview?days=x").status, 400)
        self.assertEqual(self.editor.get("/api/logs/retention-preview?days=7").status, 403)
        roles = self.admin.get("/api/users").json()["roleList"]
        self.assertTrue(all("priority" in r for r in roles))

    def test_auditoria_com_filtros(self):
        a = self.admin.get("/api/audit?days=0").json()
        self.assertGreaterEqual(a["total"], len(a["entries"]))
        self.assertTrue(a["entries"])
        u = self.admin.get("/api/audit?actions=login&days=1").json()
        self.assertTrue(u["entries"] and all(e["action"] == "login" for e in u["entries"]))
        self.assertEqual(u["total"], len(u["entries"]))
        ip = self.admin.get("/api/audit?q=127.0.0.1").json()           # o texto procura também nos detalhes (IP)
        self.assertTrue(ip["entries"])
        self.assertEqual(self.admin.get("/api/audit?q=nada-assim-existe").json()["total"], 0)
        self.assertEqual(self.admin.get("/api/audit?days=x").status, 400)
        ex = self.admin.get("/api/audit/export?days=1&actions=login")
        self.assertEqual(ex.status, 200)
        self.assertTrue(all('"login"' in l or "login" in l for l in ex.body.decode().strip().splitlines()))


class SessaoMaxima(unittest.TestCase):
    def test_sessao_expira_pela_duracao_maxima(self):
        with H.TempApp(env={"MEDUSA_SESSION_MAX_HOURS": "0.0005"}) as app:   # 1,8 s
            c = app.admin()
            self.assertEqual(c.get("/api/me").status, 200)
            time.sleep(2.2)
            self.assertEqual(c.get("/api/me").status, 401)


if __name__ == "__main__":
    unittest.main()
