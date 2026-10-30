"""Papéis e permissões personalizados (Fase 2) e aprovação de Produção por outra pessoa."""
import os, subprocess, sys, unittest

import helpers as H

sys.path.insert(0, str(H.APP_DIR))
import sso  # noqa: E402

EDIT_ONLY = ["playbook.view", "playbook.view_drafts", "playbook.edit"]


def promote(c, admin, pid, status, approver=None):
    rev = admin.get(f"/api/pb/{pid}").json()["playbook"]["rev"]
    return c.put(f"/api/pb/{pid}/status", {"status": status, "rev": rev, **({"approver": approver} if approver else {})})


def save_doc(c, pid, text):
    pb = c.get(f"/api/pb/{pid}").json()["playbook"]
    doc = pb["doc"]; doc["sections"][1]["blocks"].append({"t": "p", "text": text})
    return c.put(f"/api/pb/{pid}/doc", {"doc": doc, "rev": pb["rev"]})


class Papeis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = H.TempApp().start()
        cls.admin = cls.app.admin()
        H.create_playbook(cls.admin, "PB-01", "Teste de papéis")

    @classmethod
    def tearDownClass(cls):
        cls.app.cleanup()

    def new_role(self, name, permissions, client=None):
        r = (client or self.admin).post("/api/roles", {"name": name, "permissions": permissions})
        self.assertEqual(r.status, 200, r)
        return r.json()["role"]["key"]

    def user_with(self, role, login):
        return self.app.make_user(role, login=login)

    def test_crud(self):
        key = self.new_role("Analista de teste", EDIT_ONLY)
        roles = {r["key"]: r for r in self.admin.get("/api/roles").json()["roles"]}
        self.assertEqual(roles[key]["permissions"], EDIT_ONLY)
        self.assertEqual(roles["admin"]["permissions"], "*")
        r = self.admin.put(f"/api/roles/{key}", {"name": "Analista N2", "permissions": EDIT_ONLY + ["playbook.export"]})
        self.assertEqual(r.json()["role"]["name"], "Analista N2")
        audit = self.admin.get("/api/audit?q=papel_alterado").json()["entries"]
        self.assertIn("playbook.export", audit[0]["adicionadas"])
        self.assertEqual(self.admin.delete(f"/api/roles/{key}").status, 200)
        self.assertNotIn(key, [r["key"] for r in self.admin.get("/api/roles").json()["roles"]])

    def test_admin_imutavel_e_papeis_do_sistema(self):
        self.assertEqual(self.admin.put("/api/roles/admin", {"name": "X"}).status, 400)
        self.assertEqual(self.admin.delete("/api/roles/admin").status, 400)
        self.assertEqual(self.admin.delete("/api/roles/editor").status, 400)
        r = self.admin.put("/api/roles/viewer", {"permissions": ["playbook.view"]})
        self.assertEqual(r.json()["role"]["permissions"], ["playbook.view"])
        r = self.admin.put("/api/roles/viewer", {"reset": True})
        self.assertIn("playbook.export", r.json()["role"]["permissions"])

    def test_sempre_um_administrador(self):
        r = self.admin.put(f"/api/users/{H.ADMIN_LOGIN}", {"role": "viewer"})
        self.assertEqual(r.status, 400)

    def test_papel_em_uso(self):
        key = self.new_role("Temporario", ["playbook.view"])
        self.user_with(key, "usuario.temp")
        r = self.admin.delete(f"/api/roles/{key}")
        self.assertEqual(r.status, 400)
        self.assertIn("1 usuário", r.json()["error"])
        self.assertEqual(self.admin.delete(f"/api/roles/{key}", {"reassign": "viewer"}).status, 200)
        u = next(x for x in self.admin.get("/api/users").json()["users"] if x["login"] == "usuario.temp")
        self.assertEqual((u["roleId"], u["role"]), ("viewer", "viewer"))

    def test_sem_escalada(self):
        key = self.new_role("Gestor de acesso", ["playbook.view", "users.manage", "roles.manage"])
        g = self.user_with(key, "gestor.acesso")
        self.assertEqual(g.post("/api/roles", {"name": "Mais forte", "permissions": ["playbook.edit"]}).status, 403)
        self.assertEqual(g.post("/api/roles", {"name": "Mais fraco", "permissions": ["playbook.view"]}).status, 200)
        self.assertEqual(g.post("/api/users", {"login": "novo.editor", "name": "Novo", "role": "editor"}).status, 403)
        self.assertEqual(g.post("/api/users", {"login": "novo.leitor", "name": "Novo", "role": "mais-fraco"}).status, 200)
        self.assertEqual(g.put("/api/roles/editor", {"permissions": ["playbook.view"]}).status, 403)
        self.assertEqual(g.put(f"/api/users/{H.ADMIN_LOGIN}", {"active": False}).status, 403)
        self.assertEqual(g.put(f"/api/roles/{key}", {"permissions": ["playbook.view", "users.manage", "roles.manage", "app.reset"]}).status, 403)

    def test_papel_que_edita_mas_nao_muda_status(self):
        key = self.new_role("So edita", EDIT_ONLY)
        c = self.user_with(key, "so.edita")
        self.assertEqual(save_doc(c, "PB-01", "Editado por papel personalizado.").status, 200)
        self.assertEqual(promote(c, self.admin, "PB-01", "Homologação").status, 403)
        self.assertEqual(c.get("/api/users").status, 403)
        self.assertEqual(c.delete("/api/pb/PB-01", {"confirm": "PB-01"}).status, 403)
        me = c.get("/api/me").json()["user"]
        self.assertEqual((me["roleId"], me["role"]), (key, "viewer"))      # espelho legado: Visualizador
        self.assertIn("playbook.edit", me["permissions"])

    def test_alterar_papel_vale_na_hora(self):
        key = self.new_role("Muda na hora", EDIT_ONLY)
        c = self.user_with(key, "muda.na.hora")
        self.assertEqual(c.get("/api/pb/PB-01").status, 200)
        self.admin.put(f"/api/roles/{key}", {"permissions": ["playbook.view"]})
        self.assertEqual(c.get("/api/pb/PB-01").status, 404)         # PB-01 em Desenvolvimento: sem ver rascunhos
        self.assertEqual(save_doc(self.admin, "PB-01", "x").status, 200)

    def test_aprovadores_respeitam_pode_aprovar(self):
        key = self.new_role("Muda status sem aprovar", EDIT_ONLY + ["playbook.status"])
        c = self.user_with(key, "sem.aprovar")
        logins = [a["login"] for a in c.get("/api/approvers?type=playbook").json()["approvers"]]
        self.assertNotIn("sem.aprovar", logins)
        self.assertIn(H.ADMIN_LOGIN, logins)

    def test_sso_por_prioridade(self):
        roles = {"admin": {"priority": 100}, "editor": {"priority": 50}, "analista": {"priority": 60}, "viewer": {"priority": 10}}
        cfg = {"role_claim": "groups", "role_map": {"analista": "soc-analistas", "editor": "soc", "viewer": "todos"}}
        self.assertEqual(sso.map_role({"groups": ["soc", "soc-analistas"]}, cfg, roles), "analista")
        self.assertEqual(sso.map_role({"groups": ["todos"]}, cfg, roles), "viewer")
        self.assertIsNone(sso.map_role({"groups": ["outro"]}, cfg, roles))

    def test_sso_valida_papeis(self):
        r = self.admin.put("/api/sso/config", {"role_map": {"nao-existe": "grupo"}})
        self.assertEqual(r.status, 400)

    def test_cli_adduser(self):
        key = self.new_role("Via terminal", ["playbook.view"])
        env = {**os.environ, "MEDUSA_HOME": str(self.app.home), "PYTHONDONTWRITEBYTECODE": "1"}
        run = lambda role: subprocess.run([sys.executable, "server.py", "adduser", "cli.teste", "--role", role], cwd=H.APP_DIR, env=env,
                                          input=f"{H.USER_PASSWORD}\n{H.USER_PASSWORD}\n", capture_output=True, text=True)
        bad = run("nao-existe")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("Papel inexistente", bad.stderr)
        ok = run(key)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(self.app.client().login("cli.teste", H.USER_PASSWORD)["roleId"], key)


class Aprovacao(unittest.TestCase):
    """Promover a Produção: o aprovador não pode ser quem promove nem quem fez a última alteração."""

    @classmethod
    def setUpClass(cls):
        cls.app = H.TempApp().start()
        cls.admin = cls.app.admin()
        cls.a = cls.app.make_user("editor", login="editor.a")
        cls.b = cls.app.make_user("editor", login="editor.b")
        cls.c = cls.app.make_user("editor", login="editor.c")

    @classmethod
    def tearDownClass(cls):
        cls.app.cleanup()

    def setUp(self):
        self.pid = f"PB-{10 + len(self.admin.get('/api/library').json()['items']):02d}"
        H.create_playbook(self.admin, self.pid, "Aprovação " + self._testMethodName[-20:])
        self.assertEqual(save_doc(self.a, self.pid, "Gravado por A.").status, 200)          # A é o último autor
        self.assertEqual(promote(self.b, self.admin, self.pid, "Homologação").status, 200)

    def tearDown(self):
        self.admin.put("/api/governance", {"require_distinct_approver": True})

    def test_ligada_por_padrao(self):
        self.assertTrue(self.admin.get("/api/governance").json()["governance"]["require_distinct_approver"])

    def test_quem_promove_nao_se_aprova(self):
        r = promote(self.b, self.admin, self.pid, "Produção", "editor.b")
        self.assertEqual(r.status, 400)
        self.assertIn("outra pessoa", r.json()["error"])

    def test_ultimo_autor_nao_aprova(self):
        r = promote(self.b, self.admin, self.pid, "Produção", "editor.a")
        self.assertEqual(r.status, 400)
        self.assertIn("última alteração", r.json()["error"])

    def test_terceira_pessoa_aprova(self):
        self.assertEqual(promote(self.b, self.admin, self.pid, "Produção", "editor.c").status, 200)
        pb = self.admin.get(f"/api/pb/{self.pid}").json()["playbook"]
        self.assertEqual((pb["gov"]["status"], pb["gov"]["approver"]), ("Produção", "Editor C"))
        ev = self.admin.get("/api/audit?q=status_alterado").json()["entries"][0]
        self.assertEqual(ev["aprovador_login"], "editor.c")

    def test_administrador_conta_como_aprovador(self):
        # instalação com um único editor (A grava e promove): o administrador aprova
        self.assertEqual(promote(self.a, self.admin, self.pid, "Produção", H.ADMIN_LOGIN).status, 200)

    def test_chave_desligada(self):
        self.admin.put("/api/governance", {"require_distinct_approver": False})
        self.assertEqual(promote(self.a, self.admin, self.pid, "Produção", "editor.a").status, 200)

    def test_aprovadores_marcam_os_excluidos(self):
        d = self.b.get(f"/api/approvers?type=playbook&pid={self.pid}").json()
        ex = {a["login"]: a.get("excluded") for a in d["approvers"]}
        self.assertEqual(ex["editor.b"], "é quem está publicando")
        self.assertEqual(ex["editor.a"], "fez a última alteração")
        self.assertIsNone(ex["editor.c"])
        self.assertEqual(d["lastAuthor"]["login"], "editor.a")

    def test_producao_continua_intacta(self):
        self.assertEqual(promote(self.b, self.admin, self.pid, "Produção", "editor.c").status, 200)
        self.admin.put("/api/governance", {"require_distinct_approver": True})
        self.assertEqual(self.admin.get(f"/api/pb/{self.pid}").json()["playbook"]["gov"]["status"], "Produção")


if __name__ == "__main__":
    unittest.main()
