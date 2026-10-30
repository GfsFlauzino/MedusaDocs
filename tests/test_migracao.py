"""Migração do banco: o código atual abre um banco gerado pela tag base (v3) sem perder nada, e o código da
tag base continua abrindo o banco já migrado (rollback)."""
import json, shutil, sqlite3, tempfile, time, unittest
from pathlib import Path

import helpers as H

FIX = Path(__file__).resolve().parent / "fixtures"


def counts(db):
    c = sqlite3.connect(db)
    try: return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("users", "audit", "pb_versions", "settings")}
    finally: c.close()


class Migracao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta = json.loads((FIX / "playbooks-v3.json").read_text("utf-8"))
        cls.tmp = Path(tempfile.mkdtemp(prefix="medusa-migracao-"))
        cls.home = cls.tmp / "home"
        (cls.home / "data").mkdir(parents=True)
        cls.db = cls.home / "data" / "playbooks.db"
        shutil.copy2(FIX / "playbooks-v3.db", cls.db)
        c = sqlite3.connect(cls.db)          # sessão da fixture "usada agora" (senão já teria vencido por inatividade)
        c.execute("UPDATE sessions SET seen_at = ?", (time.time(),)); c.commit(); c.close()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_1_codigo_atual_abre_o_banco_v3(self):
        app = H.TempApp(home=self.home).start()
        try:
            c = app.client()
            c.set_token(self.meta["viewer_token"])
            r = c.get("/api/me")
            self.assertEqual(r.status, 200, "a sessão aberta antes da migração deveria continuar válida")
            self.assertEqual(r.json()["user"]["login"], "viewer.teste")
            for login, pw in self.meta["logins"].items():
                u = app.client().login(login, pw)
                self.assertEqual(u["role"], self.meta["roles"][login])
                self.assertEqual(u["roleId"], self.meta["roles"][login])
            # papel personalizado, para o teste de rollback (a 2.x deve ver esse usuário como Visualizador)
            admin = app.client(); admin.login(*next((l, p) for l, p in self.meta["logins"].items() if self.meta["roles"][l] == "admin"))
            r = admin.post("/api/roles", {"name": "Analista migrado", "permissions": ["playbook.view", "playbook.view_drafts", "playbook.edit"]})
            self.assertEqual(r.status, 200, r)
            r = admin.post("/api/users", {"login": "analista.migrado", "name": "Analista", "role": r.json()["role"]["key"]})
            c = app.client(); c.login("analista.migrado", r.json()["tempPassword"])
            self.assertEqual(c.post("/api/me/password", {"current": r.json()["tempPassword"], "new": H.USER_PASSWORD}).status, 200)
        finally:
            app.stop()
        backups = list((self.home / "data" / "backups").glob("playbooks.db.pre-v3-v*"))
        self.assertEqual(len(backups), 1, "cópia do banco antes da migração")
        self.assertEqual(oct(backups[0].stat().st_mode & 0o777), "0o600")
        now, before = counts(self.db), self.meta["counts"]
        self.assertEqual(now["users"], before["users"] + 1)      # + o analista criado acima
        self.assertEqual(now["pb_versions"], before["pb_versions"])
        self.assertEqual(now["settings"], before["settings"])
        self.assertGreaterEqual(now["audit"], before["audit"])

    def test_2_rollback_para_a_tag_base(self):
        base = H.git_worktree(H.BASE_TAG, self.tmp / "base")
        if not base: self.skipTest("git ou a tag base indisponível")
        try:
            app = H.TempApp(app_dir=base, home=self.home).start()
            try:
                for login, pw in self.meta["logins"].items():
                    app.client().login(login, pw)
                self.assertEqual(app.client().login("analista.migrado", H.USER_PASSWORD)["role"], "viewer")
            finally:
                app.stop()
        finally:
            H.git_worktree_remove(base)


if __name__ == "__main__":
    unittest.main()
