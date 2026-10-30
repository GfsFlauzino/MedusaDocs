"""Apoio dos testes: sobe o servidor de verdade (subprocesso) numa pasta de dados temporária.

Nunca usa os dados do usuário: cada TempApp tem o próprio MEDUSA_HOME, apagado no fim.
Só biblioteca padrão.
"""
import http.cookiejar, json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
ADMIN_LOGIN = "admin.teste"
# senhas só destas instalações temporárias (passam na regra: 10+ caracteres, letras e números)
ADMIN_PASSWORD = "Teste-admin-2026"
USER_PASSWORD = "Teste-usuario-2026"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None     # 302 volta como resposta (SSO)


class Response:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    def json(self):
        return json.loads(self.body.decode("utf-8")) if self.body else None

    def __repr__(self):
        return f"<{self.status} {self.body[:120]!r}>"


class Client:
    """Navegador mínimo: guarda o cookie de sessão e manda o cabeçalho anti-CSRF do front."""

    def __init__(self, base):
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect())

    def req(self, method, path, body=None, headers=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
        h = {"X-Requested-With": "playbooks", **({"Content-Type": "application/json"} if data is not None else {}), **(headers or {})}
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with self.opener.open(r, timeout=60) as resp:
                return Response(resp.status, resp.headers, resp.read())
        except urllib.error.HTTPError as e:
            return Response(e.code, e.headers, e.read())

    def get(self, path, **k): return self.req("GET", path, **k)
    def post(self, path, body=None, **k): return self.req("POST", path, {} if body is None else body, **k)
    def put(self, path, body=None, **k): return self.req("PUT", path, {} if body is None else body, **k)
    def delete(self, path, body=None, **k): return self.req("DELETE", path, {} if body is None else body, **k)

    def login(self, login, password):
        r = self.post("/api/login", {"login": login, "password": password})
        if r.status != 200: raise AssertionError(f"login de {login} falhou: {r}")
        return r.json()["user"]

    def token(self):
        return next((c.value for c in self.jar if c.name == "pbsid"), None)

    def set_token(self, token):
        """Usa um token de sessão conhecido (ex.: gravado numa fixture de banco)."""
        host = self.base.split("//", 1)[1].split(":")[0]
        self.jar.set_cookie(http.cookiejar.Cookie(0, "pbsid", token, None, False, host, False, False, "/", True, False, None, False,
                                                  None, None, {}))


class TempApp:
    """Servidor numa porta livre com MEDUSA_HOME temporário (ou o indicado, que não é apagado)."""

    def __init__(self, app_dir=APP_DIR, home=None, env=None, keep=False):
        self.app_dir = Path(app_dir)
        self.own_home = home is None
        self.home = Path(home or tempfile.mkdtemp(prefix="medusa-teste-"))
        self.keep, self.extra_env = keep, env or {}
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc = None
        self._admin = None

    def start(self):
        env = {**os.environ, "MEDUSA_HOME": str(self.home), "MEDUSA_ADMIN_LOGIN": ADMIN_LOGIN, "MEDUSA_ADMIN_PASSWORD": ADMIN_PASSWORD,
               "MEDUSA_ADMIN_NAME": "Admin Teste", "PYTHONDONTWRITEBYTECODE": "1", **self.extra_env}
        for k in ("PB_SRC", "PB_DATA", "PB_BACKUPS", "PB_TEMPLATES", "PB_MAPPINGS"): env.pop(k, None)
        self.log = open(self.home / "servidor.log", "ab")
        self.proc = subprocess.Popen([sys.executable, "server.py", "--host", "127.0.0.1", "--port", str(self.port)], cwd=self.app_dir, env=env,
                                     stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"servidor saiu com código {self.proc.returncode}: {self.read_log()[-2000:]}")
            try:
                urllib.request.urlopen(self.base + "/api/branding", timeout=1).read()
                return self
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("servidor não respondeu: " + self.read_log()[-2000:])

    def read_log(self):
        try: return (self.home / "servidor.log").read_text("utf-8", "replace")
        except OSError: return ""

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(10)
            except subprocess.TimeoutExpired: self.proc.kill(); self.proc.wait()
        if getattr(self, "log", None): self.log.close()
        self.proc = None

    def cleanup(self):
        self.stop()
        if self.own_home and not self.keep: shutil.rmtree(self.home, ignore_errors=True)

    def __enter__(self): return self.start()
    def __exit__(self, *exc): self.cleanup()

    def client(self):
        return Client(self.base)

    def admin(self):
        """Cliente do administrador inicial (troca a senha temporária na primeira vez)."""
        if self._admin is None:
            c = self.client()
            u = c.login(ADMIN_LOGIN, ADMIN_PASSWORD)
            if u["mustChange"]:
                new = ADMIN_PASSWORD + "!"
                r = c.post("/api/me/password", {"current": ADMIN_PASSWORD, "new": new})
                if r.status != 200: raise AssertionError(f"troca de senha do admin falhou: {r}")
                self.admin_password = new
            else:
                self.admin_password = ADMIN_PASSWORD
            self._admin = c
        return self._admin

    def make_user(self, role, login=None, name=None):
        """Cria o usuário pela API (como admin), entra e troca a senha temporária. Devolve o cliente já logado."""
        login = login or f"{role}.teste"
        r = self.admin().post("/api/users", {"login": login, "name": name or login.replace(".", " ").title(), "role": role})
        if r.status != 200: raise AssertionError(f"criação de {login} falhou: {r}")
        c = self.client()
        c.login(login, r.json()["tempPassword"])
        r2 = c.post("/api/me/password", {"current": r.json()["tempPassword"], "new": USER_PASSWORD})
        if r2.status != 200: raise AssertionError(f"troca de senha de {login} falhou: {r2}")
        c.login_name = login
        return c


def create_playbook(admin, pid="PB-01", name="Teste de phishing", ramos=("Credencial", "Anexo")):
    r = admin.post("/api/pb", {"id": pid, "name": name, "template": "padrao", "ramos": [{"name": x, "q": "?"} for x in ramos]})
    if r.status != 200: raise AssertionError(f"criação de {pid} falhou: {r}")
    return r.json()["playbook"]


def git_worktree(ref, dest):
    """Cópia do código de uma tag (ex.: a base v2.1.x-base) para testes de compatibilidade. None se não houver git."""
    try:
        subprocess.run(["git", "-C", str(APP_DIR), "rev-parse", "--verify", "--quiet", ref + "^{commit}"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(APP_DIR), "worktree", "add", "--detach", str(dest), ref], check=True, capture_output=True)
        return Path(dest)
    except (OSError, subprocess.CalledProcessError):
        return None


def git_worktree_remove(dest):
    subprocess.run(["git", "-C", str(APP_DIR), "worktree", "remove", "--force", str(dest)], capture_output=True)


BASE_TAG = "v2.1.x-base"
