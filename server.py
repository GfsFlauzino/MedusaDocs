#!/usr/bin/env python3
"""Servidor da ferramenta de playbooks: leitura, edição, ciclo de vida e controle de acesso.

  python3 server.py adduser <login> --role admin [--name "Nome"]   cria/atualiza usuário (pede a senha)
  python3 server.py [--host 127.0.0.1] [--port 8765] [--secure-cookies]

Variáveis de ambiente (usadas no Docker)
  MEDUSA_HOME            pasta de dados: playbooks/, templates/, data/ (banco), .backups/, mappings.json
  MEDUSA_HOST / MEDUSA_PORT / MEDUSA_SECURE_COOKIES=1
  MEDUSA_TRUST_PROXY=1   usa o IP do X-Forwarded-For (só atrás de proxy reverso confiável)
  MEDUSA_ADMIN_LOGIN     cria o primeiro administrador quando não há nenhum (senha temporária no log,
  MEDUSA_ADMIN_NAME      ou MEDUSA_ADMIN_PASSWORD; a troca é obrigatória no primeiro acesso)

Papéis
  viewer  (Visualizador)  lê playbooks em Homologação e Produção
  editor  (Editor)        lê, cria e edita todos; muda status; edita templates, times e tags
  admin   (Administrador) tudo do editor + usuários, exclusão de playbooks e auditoria

Usuários, sessões, tentativas de login, auditoria e configurações ficam no banco SQLite data/playbooks.db (store.py).
Só depende da biblioteca padrão. Para expor na rede, publique atrás de um proxy com HTTPS
e rode com --secure-cookies.
"""
import argparse, base64, difflib, getpass, hashlib, hmac, io, json, os, re, secrets, shutil, socket, sys, threading, time, urllib.parse, zipfile
from datetime import date, datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import bundle
import logfwd
import ramos
import sso
import flowdsl
import pbcore as core
import templates as tpl
from store import Store, StoreError

DATA_DIR = Path(os.environ.get("PB_DATA") or core.HOME / "data")
TRASH = DATA_DIR / "lixeira"
BACKUPS = Path(os.environ.get("PB_BACKUPS") or core.HOME / ".backups")

ROLES = {"viewer": 1, "editor": 2, "admin": 3}
ROLE_NAMES = {"viewer": "Visualizador", "editor": "Editor", "admin": "Administrador"}
VIEWER_STATUSES = {"Homologação", "Produção"}
SESSION_TTL = 8 * 3600          # inatividade máxima
PBKDF2_ITERS = 310_000
MIN_PASSWORD = 10
MAX_BODY = 8 * 1024 * 1024
APP_VERSION = "2.1.0"
LOGIN_RE = re.compile(r"^[a-z0-9._@-]{3,80}$")          # @ e até 80 caracteres: logins vindos do SSO (e-mail)
NO_PASSWORD = "!sso"                                      # hash impossível: conta só entra pelo SSO
TRUST_PROXY = os.environ.get("MEDUSA_TRUST_PROXY", "").lower() in ("1", "true", "yes", "sim")
REQ = threading.local()                                   # IP da requisição em andamento (para a auditoria)
STATIC = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/flow.js": "flow.js",
          "/editor.js": "editor.js", "/style.css": "style.css", "/theme.js": "theme.js", "/docs.js": "docs.js"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon", ".woff2": "font/woff2"}

LOGO_BGS = ("white", "transparent")       # fundo atrás da logo no topo: branco (legível em qualquer cor) ou transparente
DEFAULT_BRAND = {"name": "Medusa Docs", "color": "#3B5BDB", "logoBg": "white", "homeTitle": "Playbooks de resposta a incidentes",
                 "homeSubtitle": "Base interativa dos playbooks do time de segurança. Escolha um playbook, navegue pelo fluxograma e clique "
                                 "em qualquer caixa, ramo (R1…), passo (T0, A3…) ou time para ler o trecho da documentação."}
LOGO_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg", "image/webp": ".webp"}
MAX_LOGO = 512 * 1024
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
IMG_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
IMG_MIME = {v: k for k, v in IMG_TYPES.items()}
MAX_IMG = 3 * 1024 * 1024
RESET_WORD = "RESETAR"

LOCK = threading.RLock()        # serializa gravações nos arquivos dos playbooks
SECURE_COOKIES = False
DB: Store = None


def open_db():
    global DB
    if DB is None:
        DB = Store(DATA_DIR / "playbooks.db", session_ttl=SESSION_TTL)
        migrated = DB.import_legacy(DATA_DIR / "users.json", DATA_DIR / "audit.log")
        if migrated: print("Migrado para o banco:", ", ".join(migrated))
    return DB


class HttpError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg); self.status = status; self.msg = msg

# ───────────────────────── senhas ─────────────────────────

def hash_password(pw, salt=None):
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ITERS)
    return f"pbkdf2_sha256${PBKDF2_ITERS}${salt.hex()}${dk.hex()}"

def check_password(pw, stored):
    try:
        _, iters, salt, h = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), h)
    except (ValueError, AttributeError):
        return False

DUMMY_HASH = hash_password(secrets.token_hex(8))

def validate_password(pw):
    if not isinstance(pw, str) or len(pw) < MIN_PASSWORD:
        raise HttpError(400, f"A senha precisa ter pelo menos {MIN_PASSWORD} caracteres")
    if pw.isalpha() or pw.isdigit():
        raise HttpError(400, "Use letras e números (ou símbolos) na senha")

def temp_password():
    while True:                      # garante letras e números (passa na mesma regra das senhas definidas)
        pw = secrets.token_urlsafe(12)
        if any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw): return pw

def public_user(u):
    return {"login": u["login"], "name": u["name"], "role": u["role"], "roleName": ROLE_NAMES[u["role"]],
            "active": u["active"], "mustChange": u["must_change"], "created": u.get("created_at"),
            "lastLogin": u.get("last_login"), "sessions": u.get("sessions"), "auth": u.get("auth") or "local",
            "ssoLinked": bool(u.get("sso_subject"))}

_log_cfg = {"at": 0, "cfg": None}

def log_cfg():
    """Configuração de logs (encaminhamento e retenção), com cache de 5 s."""
    if time.time() - _log_cfg["at"] > 5:
        _log_cfg.update(at=time.time(), cfg=logfwd.merge(open_db().get_setting("logs")))
    return _log_cfg["cfg"]

FWD = None

def audit(user, action, target="", **detail):
    ip = detail.get("ip") or getattr(REQ, "ip", None)
    if ip and "ip" not in detail: detail["ip"] = ip
    open_db().audit(user, action, target, **detail)
    if FWD:
        FWD.enqueue(logfwd.make_event(datetime.now(), user, action, target, {k: v for k, v in detail.items() if k != "ip"}, ip,
                                      brand()["name"], APP_VERSION))

def retention_loop():
    while True:
        try:
            days = int(log_cfg()["retention_days"])
            n = open_db().purge(days)
            FWD.purge_files(days)
            if n: sys.stderr.write(f"Retenção: {n} evento(s) de auditoria com mais de {days} dias apagado(s)\n")
        except Exception as e:
            sys.stderr.write(f"ERRO retenção: {e!r}\n")
        time.sleep(6 * 3600)

# ───────────────────────── arquivos ─────────────────────────

def backup(pid, *files):
    dest = BACKUPS / pid / time.strftime("%Y%m%d-%H%M%S")
    for f in files:
        if f and Path(f).exists():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest / Path(f).name)

def save_refs(pid, refs):
    allm = core.read_json(core.MAPPINGS_FILE, {})
    if refs is None: allm.pop(pid, None)
    else: allm[pid] = refs
    core.MAPPINGS_FILE.write_text(json.dumps(allm, ensure_ascii=False, indent=2) + "\n", "utf-8")

# ───────────────────────── playbooks ─────────────────────────

def today(): return date.today().strftime("%d/%m/%Y")

def get_folder(pid):
    if not pid or not core.ID_RE.fullmatch(pid): raise HttpError(404, "playbook não encontrado")
    f = core.folder_of(pid)
    if not f: raise HttpError(404, "playbook não encontrado")
    return f

def check_rev(folder, rev):
    if rev and rev != core.revision(folder):
        raise HttpError(409, "Este playbook foi salvo por outra pessoa depois que você abriu. Recarregue para ver a versão atual.")

def visible(pb, user):
    return ROLES[user["role"]] >= ROLES["editor"] or pb["gov"]["status"] in VIEWER_STATUSES

def for_role(pb, user):
    if ROLES[user["role"]] < ROLES["editor"]:
        pb = {k: v for k, v in pb.items() if k not in ("doc", "folder")}
    return pb

def touch_review(doc, user, current_doc):
    gov = core.get_gov(current_doc)
    gov.update(reviewer=user["name"], reviewed=today())
    return core.set_gov(doc, gov)

def validate_flow(flow):
    lanes_list = flow.get("lanes")
    if not isinstance(lanes_list, list) or not lanes_list: raise HttpError(400, "o fluxograma precisa de pelo menos uma raia")
    if len(lanes_list) > core.MAX_LANES: raise HttpError(400, f"no máximo {core.MAX_LANES} raias")
    lanes = set()
    for l in lanes_list:
        if not isinstance(l, dict) or not core.LANE_KEY_RE.fullmatch(str(l.get("key", ""))) or l["key"] in lanes:
            raise HttpError(400, f"raia inválida: {l.get('key') if isinstance(l, dict) else l}")
        if not str(l.get("label", "")).strip() or len(str(l["label"])) > 60: raise HttpError(400, "nome de raia inválido")
        if not HEX_RE.fullmatch(str(l.get("color", ""))): raise HttpError(400, f"cor inválida na raia {l['label']}")
        l["kind"] = "support" if l.get("kind") == "support" else "team"
        l["team"] = None if l["kind"] == "support" else str(l.get("team") or l["label"])[:60]
        lanes.add(l["key"])
    ids = set()
    for n in flow.get("nodes", []):
        if n.get("lane") not in lanes or n.get("type") not in core.NODE_TYPES:
            raise HttpError(400, f"caixa inválida: {n.get('id')}")
        if not re.fullmatch(r"[\w-]{1,40}", str(n.get("id", ""))) or n["id"] in ids:
            raise HttpError(400, f"id de caixa inválido ou repetido: {n.get('id')}")
        ids.add(n["id"])
    for e in flow.get("edges", []):
        if e.get("from") not in ids or e.get("to") not in ids:
            raise HttpError(400, f"seta ligada a caixa inexistente: {e.get('id')}")
        if e.get("type") not in core.EDGE_TYPES:
            raise HttpError(400, f"tipo de seta inválido: {e.get('type')}")
        if e["id"] in ids:
            raise HttpError(400, f"seta com o mesmo id de uma caixa: {e['id']}")
        lp = e.get("lp")
        if lp is not None:
            try: e["lp"] = {"dx": max(-2000.0, min(2000.0, float(lp["dx"]))), "dy": max(-2000.0, min(2000.0, float(lp["dy"])))}
            except (TypeError, KeyError, ValueError): e.pop("lp", None)
            if e.get("lp") == {"dx": 0.0, "dy": 0.0}: e.pop("lp")

# ───────────────────────── HTTP ─────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "Playbooks"
    sys_version = ""

    def log_message(self, fmt, *args):
        if args and "/api/" in str(args[0]) and not (self.client_address[0] in ("127.0.0.1", "::1") and "/api/branding " in str(args[0])):
            if "/api/sso/callback" in str(args[0]): args = (re.sub(r"\?\S*", "?…", str(args[0])),) + args[1:]   # não registra code/state
            sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def headers_common(self, csp=None):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", csp or
                         "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; form-action 'self'")

    def send_json(self, obj, status=200, cookie=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cookie: self.send_header("Set-Cookie", cookie)
        self.headers_common()
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.headers_common()
        self.end_headers()
        self.wfile.write(data)

    def send_bytes(self, data, ctype, filename=None, sandbox=False):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if filename: self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.headers_common("default-src 'none'; style-src 'unsafe-inline'; sandbox" if sandbox else None)
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY: raise HttpError(413, "conteúdo grande demais")
        try:
            return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except (ValueError, UnicodeDecodeError):
            raise HttpError(400, "JSON inválido")

    def query(self):
        from urllib.parse import parse_qs, urlparse
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    # ── sessão
    def cookie_token(self):
        c = SimpleCookie(self.headers.get("Cookie", ""))
        return c["pbsid"].value if "pbsid" in c else None

    def session_cookie(self, token, max_age=SESSION_TTL):
        return (f"pbsid={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
                + ("; Secure" if SECURE_COOKIES else ""))

    def require(self, role="viewer", allow_must_change=False):
        u = open_db().session_user(self.cookie_token())
        if not u: raise HttpError(401, "Faça login para continuar")
        if u["must_change"] and not allow_must_change: raise HttpError(403, "Troque a senha temporária para continuar")
        if ROLES[u["role"]] < ROLES[role]: raise HttpError(403, "Seu perfil não tem permissão para esta ação")
        return u

    def csrf(self):
        # requisições que alteram estado precisam do cabeçalho; outro site não consegue enviá-lo sem CORS
        if self.headers.get("X-Requested-With") != "playbooks":
            raise HttpError(403, "requisição recusada")

    def client_ip(self):
        ip = self.client_address[0]
        if TRUST_PROXY:            # atrás de proxy reverso confiável: o IP real vem no X-Forwarded-For
            xff = [x.strip() for x in (self.headers.get("X-Forwarded-For") or "").split(",") if x.strip()]
            if xff: ip = xff[-1]
        return ip

    def send_redirect(self, location, cookies=()):
        self.send_response(302)
        self.send_header("Location", location)
        for c in cookies: self.send_header("Set-Cookie", c)
        self.send_header("Content-Length", "0")
        self.headers_common()
        self.end_headers()

    def send_html(self, html_text, cookies=()):
        body = html_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for c in cookies: self.send_header("Set-Cookie", c)
        self.headers_common("default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def handle_api(self, method):
        path = self.path.split("?")[0]
        REQ.ip = self.client_ip()
        try:
            if method != "GET": self.csrf()
            key = re.sub(r"/PB-\d{2,3}", "/{pb}", re.sub(r"^/api/users/[^/]+", "/api/users/{u}", path))
            key = re.sub(r"^(/api/pb/\{pb\}/ramos)/[^/]+$", r"\1/{r}", key)
            key = re.sub(r"^(/api/pb/\{pb\}/versions)/\d+", r"\1/{v}", key)
            key = re.sub(r"^(/api/pb/\{pb\}/img)/[^/]+$", r"\1/{f}", key)
            if not path.startswith("/api/templates/import"):
                key = re.sub(r"^/api/templates/[^/]+", "/api/templates/{t}", key)
            route = ROUTES.get((method, key))
            if not route: raise HttpError(404, "não encontrado")
            m = re.search(r"/(PB-\d{2,3})(?:/|$)", path); u = re.match(r"^/api/users/([^/]+)", path)
            t = re.match(r"^/api/templates/([^/]+)", path)
            return route(self, pid=m.group(1) if m else None, login=urllib.parse.unquote(u.group(1)) if u else None,
                         tkey=t.group(1) if t else None)
        except HttpError as e:
            return self.send_json({"error": e.msg}, e.status)
        except (StoreError, tpl.TemplateError) as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception as e:  # nunca expor stack trace
            sys.stderr.write(f"ERRO {method} {path}: {e!r}\n")
            return self.send_json({"error": "erro interno"}, 500)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/"): return self.handle_api("GET")
        if path in STATIC: return self.send_file(core.HERE / STATIC[path])
        m = re.fullmatch(r"/assets/([\w.-]+)", path)
        if m and (core.HERE / "assets" / m.group(1)).is_file() and Path(m.group(1)).suffix in TYPES:
            return self.send_file(core.HERE / "assets" / m.group(1))
        self.send_json({"error": "não encontrado"}, 404)

    def do_POST(self): self.handle_api("POST")
    def do_PUT(self): self.handle_api("PUT")
    def do_DELETE(self): self.handle_api("DELETE")

# ───────────────────────── rotas: sessão ─────────────────────────

def r_login(h, **_):
    db = open_db(); b = h.body()
    login, pw = str(b.get("login", "")).strip().lower(), str(b.get("password", ""))
    ip = h.client_ip(); key = f"{login}|{ip}"
    wait = db.locked_for(key)
    if wait: raise HttpError(429, f"Muitas tentativas. Tente de novo em {int(wait // 60) + 1} min.")
    u = db.get_user(login)
    if not (check_password(pw, u["hash"] if u else DUMMY_HASH) and u and u["active"]):
        db.register_fail(key)
        audit(login or "?", "login_falhou", ip=ip)
        raise HttpError(401, "Usuário ou senha inválidos" + (". Contas do SSO entram pelo botão de SSO." if u and u.get("auth") == "sso" else ""))
    cfg = sso_cfg()
    if cfg["enabled"] and cfg.get("local_login") == "admins" and u["role"] != "admin":
        audit(login, "login_falhou", ip=ip, motivo="login local restrito a administradores")
        raise HttpError(403, "O login por senha está desativado: use o SSO")
    db.clear_fails(key)
    token = db.create_session(login, ip, h.headers.get("User-Agent"))
    audit(login, "login", ip=ip)
    h.send_json({"user": public_user(db.get_user(login))}, cookie=h.session_cookie(token))

def r_logout(h, **_):
    tok = h.cookie_token()
    login = open_db().delete_session(tok) if tok else None
    if login: audit(login, "logout")
    h.send_json({"ok": True}, cookie=h.session_cookie("", 0))

def r_me(h, **_):
    h.send_json({"user": public_user(h.require(allow_must_change=True))})

def r_password(h, **_):
    u = h.require(allow_must_change=True); b = h.body()
    if u.get("auth") == "sso": raise HttpError(400, "A senha desta conta é gerenciada pelo provedor de SSO")
    if not check_password(str(b.get("current", "")), u["hash"]): raise HttpError(400, "Senha atual incorreta")
    validate_password(b.get("new"))
    if b["new"] == b.get("current"): raise HttpError(400, "A nova senha precisa ser diferente da atual")
    open_db().set_password(u["login"], hash_password(b["new"]), must_change=False, keep_token=h.cookie_token())
    audit(u["login"], "senha_alterada")
    h.send_json({"user": public_user(open_db().get_user(u["login"]))})

# ───────────────────────── rotas: playbooks ─────────────────────────

# Cada playbook pertence a um template, que define os times e tags dele (cores, responsabilidades).
# O vínculo fica no banco (configuração "pb_templates"); sem vínculo, vale o template Padrão.

def links():
    return open_db().get_setting("pb_templates") or {}

def set_link(pid, key):
    lk = links()
    if key: lk[pid] = key
    else: lk.pop(pid, None)
    open_db().set_setting("pb_templates", lk)

def template_of(pid, lk=None):
    k = (lk if lk is not None else links()).get(pid)
    return k if k and tpl.KEY_RE.fullmatch(k) and tpl.path_of(k).exists() else tpl.DEFAULT_KEY

def template_teams(key):
    f = tpl.path_of(key)
    teams = tpl.teams_of_file(f) if f.exists() else {}
    for n, t in teams.items(): t.setdefault("category", "central" if n in tpl.BASIC_TEAMS else "apoio")
    return teams

def template_name(key):
    f = tpl.path_of(key)
    if f.exists():
        with open(f, encoding="utf-8") as fh:
            for _, line in zip(range(12), fh):
                if line.startswith("name:"): return line[5:].strip()
    return key

def load_pb(folder, lk=None):
    pid = re.match(r"(PB-\d+)", folder.name).group(1)
    key = template_of(pid, lk)
    teams = template_teams(key)
    v = core.load_playbook(folder, teams)
    v.update(templateKey=key, templateName=template_name(key), teams=teams)
    return v

def add_template_teams(key, names_or_defs, union=None):
    """Acrescenta ao template times que o playbook passou a usar (vindos de outro template ou de um arquivo importado)."""
    t = tpl.load(key)
    union = union if union is not None else core.load_teams()
    tm, added = t.setdefault("teams", {}), []
    items = names_or_defs.items() if isinstance(names_or_defs, dict) else [(n, None) for n in names_or_defs]
    for n, d in items:
        d = d or union.get(n)
        if n not in tm and d:
            tm[n] = clean_team(n, {**d, "color": d.get("color") if HEX_RE.fullmatch(str(d.get("color", ""))) else "#5B6673"}); added.append(n)
    if added: tpl.save(key, t)
    return added

def r_data(h, **_):
    u = h.require()
    lk = links()
    pbs = [load_pb(f, lk) for f in core.all_folders()]
    h.send_json({"playbooks": [for_role(p, u) for p in pbs if visible(p, u)], "teams": core.load_teams(),
                 "catalog": core.CATALOG, "statuses": core.STATUSES})

def r_pb_get(h, pid, **_):
    u = h.require()
    pb = load_pb(get_folder(pid))
    if not visible(pb, u): raise HttpError(404, "playbook não encontrado")
    h.send_json({"playbook": for_role(pb, u)})

# ───────────────────────── versões ─────────────────────────
# Cada gravação gera uma versão (regras em pbcore.next_version) e guarda o conteúdo completo no banco
# (.md, .drawio e vínculos), para leitura, comparação e restauração pela aplicação.

SYSTEM_USER = {"login": "sistema", "name": "Sistema"}

def snapshot(folder, pid, u, kind, note=""):
    md, dio = core.files_of(folder)
    text = md.read_text("utf-8")
    doc = core.parse_md(text)
    return open_db().add_version(pid, core.fmt_version(core.get_version(doc)), core.get_gov(doc)["status"], u["login"], u["name"],
                                 kind, note, text, dio.read_text("utf-8") if dio else "",
                                 core.read_json(core.MAPPINGS_FILE, {}).get(pid, {}), template_of(pid))

def ensure_baseline(folder, pid):
    """Playbook sem histórico (anterior à 2.0): registra o estado atual antes da primeira alteração."""
    if not open_db().count_versions(pid): snapshot(folder, pid, SYSTEM_USER, "base", "Estado registrado ao ativar o histórico de versões")

def bump(doc, old_doc, publish=False):
    v = core.next_version(core.get_version(old_doc), core.get_gov(old_doc)["status"], publish)
    core.set_version(doc, v)
    return core.fmt_version(v)

def r_pb_doc(h, pid, **_):
    u = h.require("editor")
    folder = get_folder(pid); b = h.body()
    doc = b.get("doc")
    if not isinstance(doc, dict) or not str(doc.get("title", "")).strip() or not isinstance(doc.get("sections"), list):
        raise HttpError(400, "documento inválido")
    with LOCK:
        check_rev(folder, b.get("rev"))
        ensure_baseline(folder, pid)
        md, dio = core.files_of(folder)
        old = core.parse_md(md.read_text("utf-8"))
        touch_review(doc, u, old)
        doc = core.parse_md(core.doc_to_md(doc))          # mesma forma que será lida de volta
        ver = bump(doc, old)
        view = load_pb(folder)
        flow, refs = view["flow"], view["refs"]
        changes = ramos.sync_from_doc(flow, refs, old, doc)
        backup(pid, md, *( (dio, core.MAPPINGS_FILE) if changes else ()))
        md.write_text(core.doc_to_md(doc), "utf-8")
        if changes: write_flow(folder, pid, view["name"], flow, refs)
        snapshot(folder, pid, u, "documento", "; ".join(changes))
    audit(u["login"], "documento_salvo", pid, versao=ver, **({"ramos": "; ".join(changes)} if changes else {}))
    h.send_json({"ok": True, "playbook": load_pb(folder), "sync": changes, "version": ver})

def write_flow(folder, pid, name, flow, refs):
    _, dio = core.files_of(folder)
    target = dio or folder / f"{pid.lower()}-{core.slug(name)}.drawio"
    target.write_text(core.flow_to_drawio(flow, pid, name, dio), "utf-8")
    ids = {n["id"] for n in flow["nodes"]}
    save_refs(pid, {k: [str(x) for x in v] for k, v in refs.items() if k in ids and isinstance(v, list) and v})

def r_pb_flow(h, pid, **_):
    u = h.require("editor")
    folder = get_folder(pid); b = h.body()
    flow, refs = b.get("flow") or {}, b.get("refs") or {}
    validate_flow(flow)
    refs = {k: [str(x) for x in v] for k, v in refs.items() if isinstance(v, list)}
    with LOCK:
        check_rev(folder, b.get("rev"))
        ensure_baseline(folder, pid)
        md, dio = core.files_of(folder)
        view = load_pb(folder)
        backup(pid, dio, md, core.MAPPINGS_FILE)
        doc = core.parse_md(md.read_text("utf-8")); old = core.clone_doc(doc)
        changes = ramos.sync_from_flow(doc, view["flow"], view["refs"], flow, refs)
        write_flow(folder, pid, view["name"], flow, refs)
        touch_review(doc, u, doc); ver = bump(doc, old)
        md.write_text(core.doc_to_md(doc), "utf-8")
        new_teams = add_template_teams(view["templateKey"], sorted(tpl.used_teams(flow) - set(view["teams"])))
        snapshot(folder, pid, u, "fluxograma", "; ".join(changes))
    audit(u["login"], "fluxograma_salvo", pid, versao=ver, **({"ramos": "; ".join(changes)} if changes else {}),
          **({"times_no_template": ", ".join(new_teams)} if new_teams else {}))
    h.send_json({"ok": True, "playbook": load_pb(folder), "sync": changes, "version": ver})

def r_pb_ramo_add(h, pid, **_):
    u = h.require("editor")
    folder = get_folder(pid); b = h.body()
    name, q = str(b.get("name", "")).strip()[:80], str(b.get("q", "")).strip()[:200]
    if not name: raise HttpError(400, "Informe o nome do ramo")
    with LOCK:
        check_rev(folder, b.get("rev"))
        ensure_baseline(folder, pid)
        md, dio = core.files_of(folder)
        view = load_pb(folder)
        doc, flow, refs = core.parse_md(md.read_text("utf-8")), view["flow"], view["refs"]
        old = core.clone_doc(doc)
        k = ramos.next_key(doc, flow, refs)
        backup(pid, md, dio, core.MAPPINGS_FILE)
        ramos.add(doc, flow, refs, k, name, q)
        write_flow(folder, pid, view["name"], flow, refs)
        touch_review(doc, u, doc); ver = bump(doc, old)
        md.write_text(core.doc_to_md(doc), "utf-8")
        snapshot(folder, pid, u, "ramo", f"R{k} {name} criado")
    audit(u["login"], "ramo_criado", pid, ramo=f"R{k} {name}", versao=ver)
    h.send_json({"ok": True, "playbook": load_pb(folder), "ramo": f"R{k}"})

def r_pb_ramo_delete(h, pid, **_):
    u = h.require("editor")
    folder = get_folder(pid); b = h.body()
    k = ramos.ref_key(h.path.split("?")[0].rsplit("/", 1)[-1])
    if not k or k == ramos.PROTO: raise HttpError(404, "ramo não encontrado")
    with LOCK:
        check_rev(folder, b.get("rev"))
        md, dio = core.files_of(folder)
        view = load_pb(folder)
        doc, flow, refs = core.parse_md(md.read_text("utf-8")), view["flow"], view["refs"]
        if k not in ramos.doc_ramos(doc) and k not in ramos.flow_ramos(flow, refs): raise HttpError(404, "ramo não encontrado")
        ensure_baseline(folder, pid)
        old = core.clone_doc(doc)
        backup(pid, md, dio, core.MAPPINGS_FILE)
        ramos.remove(doc, flow, refs, k)
        write_flow(folder, pid, view["name"], flow, refs)
        touch_review(doc, u, doc); ver = bump(doc, old)
        md.write_text(core.doc_to_md(doc), "utf-8")
        snapshot(folder, pid, u, "ramo", f"R{k} excluído")
    audit(u["login"], "ramo_excluido", pid, ramo=f"R{k}", versao=ver)
    h.send_json({"ok": True, "playbook": load_pb(folder)})

def r_pb_status(h, pid, **_):
    u = h.require("editor")
    folder = get_folder(pid); b = h.body()
    status = b.get("status")
    if status not in core.STATUSES: raise HttpError(400, "status inválido")
    with LOCK:
        check_rev(folder, b.get("rev"))
        md, _ = core.files_of(folder)
        doc = core.parse_md(md.read_text("utf-8")); old = core.clone_doc(doc)
        gov = core.get_gov(doc); before = gov["status"]
        if status == before: raise HttpError(400, f"O playbook já está em {status}")
        if status == "Produção":
            ap = open_db().get_user(str(b.get("approver", "")))
            if not ap or not ap["active"] or ROLES[ap["role"]] < ROLES["editor"]:
                raise HttpError(400, "Escolha um aprovador (editor ou administrador ativo)")
            gov["approver"] = ap["name"]
        ensure_baseline(folder, pid)
        gov["status"] = status
        core.set_gov(doc, gov)
        ver = bump(doc, old, publish=True) if status == "Produção" else core.fmt_version(core.get_version(doc))
        backup(pid, md)
        md.write_text(core.doc_to_md(doc), "utf-8")
        note = str(b.get("note", ""))[:300]
        snapshot(folder, pid, u, "status", f"{before} → {status}" + (f" · aprovado por {gov['approver']}" if status == "Produção" else "") + (f" · {note}" if note else ""))
    audit(u["login"], "status_alterado", pid, de=before, para=status, versao=ver, aprovador=gov.get("approver", "") if status == "Produção" else "",
          nota=str(b.get("note", ""))[:500])
    h.send_json({"ok": True, "playbook": load_pb(folder)})

def mitre_text(ids):
    by = {t["id"]: t for t in core.MITRE["tactics"]}
    bad = [i for i in ids if i not in by]
    if bad: raise HttpError(400, f"Tática MITRE desconhecida: {', '.join(bad)}")
    return " · ".join(f"{i} {by[i]['name']}" for i in ids)

def r_pb_create(h, **_):
    u = h.require("editor")
    m = h.body()
    pid = str(m.get("id", "")).strip().upper(); name = str(m.get("name", "")).strip()[:100]
    if not core.ID_RE.fullmatch(pid): raise HttpError(400, "ID deve ter o formato PB-00")
    if not name: raise HttpError(400, "informe o nome do playbook")
    author = open_db().get_user(str(m.get("author") or u["login"]))
    if not author or not author["active"]: raise HttpError(400, "Escolha um autor entre os usuários ativos")
    t = tpl.load(str(m.get("template") or tpl.DEFAULT_KEY))
    mitre = mitre_text([str(x) for x in (m.get("mitre") or [])][:20])
    with LOCK:
        if core.folder_of(pid): raise HttpError(400, f"{pid} já existe")
        doc, flow, refs, tdefs = tpl.instantiate(t, {
            "id": pid, "name": name, "author": author["name"], "date": today(), "owner": str(m.get("owner", ""))[:80],
            "nist": str(m.get("nist", ""))[:200], "mitre": mitre, "objective": str(m.get("objective", ""))[:3000],
            "question": str(m.get("question", ""))[:300], "ramos": [r for r in (m.get("ramos") or [])][:20]})
        validate_flow(flow)
        base = f"{pid}-{core.slug(name).title()}"
        folder = core.SRC / base
        folder.mkdir(parents=True)
        doc = core.set_gov(doc, {"status": "Desenvolvimento", "approver": "", "reviewer": u["name"], "reviewed": today()})
        core.set_version(doc, (0, 1))
        (folder / f"{base}.md").write_text(core.doc_to_md(doc), "utf-8")
        (folder / f"{pid.lower()}-{core.slug(name)}.drawio").write_text(core.flow_to_drawio(flow, pid, name), "utf-8")
        save_refs(pid, refs)
        set_link(pid, t["key"])
        snapshot(folder, pid, u, "criacao", f"Criado com o template {t['name']}")
    audit(u["login"], "playbook_criado", pid, nome=name, template=t["name"], autor=author["login"])
    h.send_json({"ok": True, "playbook": load_pb(folder), "teams": core.load_teams()})

def r_pb_delete(h, pid, **_):
    u = h.require("admin")
    folder = get_folder(pid); b = h.body()
    if b.get("confirm") != pid: raise HttpError(400, f"Para confirmar, digite {pid}")
    with LOCK:
        dest = TRASH / f"{folder.name}__{time.strftime('%Y%m%d-%H%M%S')}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        refs = core.read_json(core.MAPPINGS_FILE, {}).get(pid)
        backup(pid, core.MAPPINGS_FILE)
        shutil.move(str(folder), str(dest))
        if refs: (dest / "mappings.json").write_text(json.dumps({pid: refs}, ensure_ascii=False, indent=2), "utf-8")
        save_refs(pid, None)
        if links().get(pid): (dest / "template.txt").write_text(links()[pid], "utf-8")
        set_link(pid, None)
        open_db().archive_versions(pid, dest.name)
    audit(u["login"], "playbook_excluido", pid, lixeira=dest.name)
    h.send_json({"ok": True, "trash": dest.name})

# ───────────────────────── imagens do documento ─────────────────────────
# Arquivos em <pasta do playbook>/imagens/, com nome pelo hash do conteúdo: nunca são sobrescritos, então
# versões antigas do documento continuam mostrando as imagens que tinham.

def decode_image(data_url, what="Imagem"):
    """data:image/...;base64 → (extensão, bytes). Confere o tipo declarado com a assinatura do arquivo."""
    m = re.fullmatch(r"data:([\w/+.-]+);base64,([A-Za-z0-9+/=\s]+)", str(data_url or ""))
    if not m or m.group(1) not in IMG_TYPES: raise HttpError(400, f"{what}: envie PNG, JPG, WEBP ou GIF")
    try: data = base64.b64decode(m.group(2), validate=False)
    except ValueError: raise HttpError(400, f"{what}: arquivo ilegível")
    if len(data) > MAX_IMG: raise HttpError(400, f"{what} grande demais (máx. {MAX_IMG // 1024 // 1024} MB)")
    ext = IMG_TYPES[m.group(1)]
    ok = {"png": data[:8] == b"\x89PNG\r\n\x1a\n", "jpg": data[:3] == b"\xff\xd8\xff",
          "gif": data[:6] in (b"GIF87a", b"GIF89a"), "webp": data[:4] == b"RIFF" and data[8:12] == b"WEBP"}[ext]
    if not ok: raise HttpError(400, f"{what}: o conteúdo não é um {ext.upper()} válido")
    return ext, data

def store_image(folder, ext, data):
    name = f"img-{hashlib.sha256(data).hexdigest()[:16]}.{ext}"
    d = folder / core.IMG_DIR
    d.mkdir(exist_ok=True)
    if not (d / name).exists(): (d / name).write_bytes(data)
    return name

def pb_images(folder, doc):
    """Imagens citadas no documento, como data URL (para o pacote .medusa.md)."""
    out = {}
    for n in sorted(core.images_of(doc)):
        f = folder / core.IMG_DIR / n
        if core.IMG_NAME_RE.fullmatch(n) and f.is_file():
            out[n] = f"data:{IMG_MIME[n.rsplit('.', 1)[1]]};base64," + base64.b64encode(f.read_bytes()).decode()
    return out

def r_pb_img_post(h, pid, **_):
    u = h.require("editor")
    folder = get_folder(pid)
    ext, data = decode_image(h.body().get("dataUrl"))
    with LOCK: name = store_image(folder, ext, data)
    audit(u["login"], "imagem_enviada", pid, arquivo=name, tamanho_kb=round(len(data) / 1024))
    h.send_json({"ok": True, "src": f"{core.IMG_DIR}/{name}", "url": f"api/pb/{pid}/img/{name}"})

def r_pb_img_get(h, pid, **_):
    u = h.require()
    folder = get_folder(pid)
    name = h.path.split("?")[0].rsplit("/", 1)[-1]
    f = folder / core.IMG_DIR / name
    if not core.IMG_NAME_RE.fullmatch(name) or not f.is_file(): raise HttpError(404, "imagem não encontrada")
    if ROLES[u["role"]] < ROLES["editor"]:
        md, _ = core.files_of(folder)
        if core.get_gov(core.parse_md(md.read_text("utf-8")))["status"] not in VIEWER_STATUSES: raise HttpError(404, "imagem não encontrada")
    h.send_bytes(f.read_bytes(), IMG_MIME[name.rsplit(".", 1)[1]], sandbox=True)

def team_usage(tkey):
    """Onde cada time do template aparece: no fluxograma modelo e nos playbooks que usam o template."""
    use, lk = {}, links()
    t = tpl.load(tkey)
    for n in tpl.used_teams(t["flow"]): use.setdefault(n, set()).add("fluxograma do template")
    for f in core.all_folders():
        pid = re.match(r"(PB-\d+)", f.name).group(1)
        if template_of(pid, lk) != tkey: continue
        _, dio = core.files_of(f)
        if not dio: continue
        for n in tpl.used_teams(core.drawio_to_flow(dio)): use.setdefault(n, set()).add(pid)
    return use

def clean_team(name, t):
    if not re.fullmatch(r"[\w ./&()-]{1,40}", name, re.U): raise HttpError(400, f"Nome de time inválido: {name}")
    if not HEX_RE.fullmatch(str(t.get("color", ""))): raise HttpError(400, f"Cor inválida no time {name}")
    lst = lambda v: [str(x)[:300] for x in v][:30] if isinstance(v, list) else []
    return {"color": t["color"].upper(), "kind": str(t.get("kind", ""))[:80], "summary": str(t.get("summary", ""))[:1500],
            "does": lst(t.get("does")), "never": lst(t.get("never")),
            "category": "central" if t.get("category") == "central" else "apoio"}

# ───────────────────────── rotas: exportar / importar ─────────────────────────

def brand():
    return {**DEFAULT_BRAND, **(open_db().get_setting("branding") or {})}

EXPORT_FMTS = {"medusa": "pacote", "md": "documento", "drawio": "fluxograma drawio", "mmd": "fluxograma mermaid"}

def r_pb_export(h, pid, **_):
    u = h.require()
    folder = get_folder(pid)
    view = load_pb(folder)
    if not visible(view, u): raise HttpError(404, "playbook não encontrado")
    fmt = h.query().get("fmt", "medusa")
    if fmt not in EXPORT_FMTS: raise HttpError(400, "formato inválido")
    base = view["folder"].lower()
    if fmt == "medusa":
        data, ctype, fname = (bundle.export(view, {**core.load_teams(), **view["teams"]}, u["name"], brand()["name"], pb_images(folder, view["doc"])).encode(),
                              "text/markdown; charset=utf-8", f"{base}.medusa.md")
    elif fmt == "md":
        data, ctype, fname = core.doc_to_md(view["doc"]).encode(), "text/markdown; charset=utf-8", f"{base}.md"
        imgs = [folder / core.IMG_DIR / n for n in sorted(core.images_of(view["doc"]))]
        if any(f.is_file() for f in imgs):        # com imagens: .zip com o .md e a pasta imagens/ (os links relativos continuam valendo)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr(fname, data)
                for f in imgs:
                    if f.is_file(): z.write(f, f"{core.IMG_DIR}/{f.name}")
            data, ctype, fname = buf.getvalue(), "application/zip", f"{base}.zip"
    elif fmt == "drawio":
        _, dio = core.files_of(folder)
        data = dio.read_bytes() if dio else core.flow_to_drawio(view["flow"], pid, view["name"]).encode()
        ctype, fname = "application/xml; charset=utf-8", f"{base}.drawio"
    else:
        data, ctype, fname = flowdsl.render(view["flow"], view["refs"]).encode(), "text/plain; charset=utf-8", f"{base}.mmd"
    audit(u["login"], "playbook_exportado", pid, formato=EXPORT_FMTS[fmt])
    h.send_bytes(data, ctype, fname)

def r_export_all(h, **_):
    u = h.require()
    buf, union, name, lk = io.BytesIO(), core.load_teams(), brand()["name"], links()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in core.all_folders():
            v = load_pb(f, lk)
            if not visible(v, u): continue
            z.writestr(f"{f.name.lower()}.medusa.md", bundle.export(v, {**union, **v["teams"]}, u["name"], name, pb_images(f, v["doc"])))
    audit(u["login"], "playbooks_exportados")
    h.send_bytes(buf.getvalue(), "application/zip", f"playbooks-{date.today().isoformat()}.zip")

def r_import(h, **_):
    u = h.require("editor"); b = h.body()
    tkey = str(b.get("template") or tpl.DEFAULT_KEY)
    if not tpl.KEY_RE.fullmatch(tkey) or not tpl.path_of(tkey).exists(): raise HttpError(400, "Escolha um template existente")
    union, teams = core.load_teams(), template_teams(tkey)
    try:
        p = bundle.parse(str(b.get("text", "")), teams)
    except bundle.BundleError as e:
        raise HttpError(400, str(e))
    for n in p["createTeams"]:      # time que já existe em outro template: leva a definição de lá
        if n not in p["teamDefs"] and n in union: p["createTeams"][n] = {**union[n], "category": p["createTeams"][n]["category"]}
    pid = str(b.get("id") or p["id"]).strip().upper()
    if not core.ID_RE.fullmatch(pid): raise HttpError(400, "Defina um ID no formato PB-00")
    existing = core.folder_of(pid)
    summary = {"id": pid, "originalId": p["id"], "name": p["name"], "exists": bool(existing),
               "sections": len(p["doc"]["sections"]), "nodes": len(p["flow"]["nodes"]), "edges": len(p["flow"]["edges"]),
               "lanes": [l["label"] for l in p["flow"]["lanes"]], "createTeams": sorted(p["createTeams"]),
               "warnings": p["warnings"], "origin": p["meta"], "template": tpl.load(tkey)["name"]}
    images = {}
    for n, durl in p["images"].items():
        if not core.IMG_NAME_RE.fullmatch(n): p["warnings"].append(f"Imagem com nome inválido ignorada: {n[:60]}"); continue
        try: images[n] = decode_image(durl, f"Imagem {n}")[1]
        except HttpError as e: p["warnings"].append(e.msg + " (ignorada)")
    missing = sorted(core.images_of(p["doc"]) - set(images))
    if missing: p["warnings"].append(f"{len(missing)} imagem(ns) citada(s) no documento não vieram no arquivo: {', '.join(missing[:5])}")
    summary["images"] = len(images)
    if b.get("dryRun"): return h.send_json({"preview": summary})
    if existing and b.get("mode") != "replace":
        raise HttpError(409, f"{pid} já existe. Escolha substituir ou importe com outro ID.")
    validate_flow(p["flow"])
    doc = p["doc"]
    if p["id"] and p["id"] != pid and doc["title"].startswith(p["id"]): doc["title"] = pid + doc["title"][len(p["id"]):]
    core.set_gov(doc, {"status": "Desenvolvimento", "approver": "", "reviewer": u["name"], "reviewed": today()})
    with LOCK:
        if existing:
            dest = TRASH / f"{existing.name}__substituido__{time.strftime('%Y%m%d-%H%M%S')}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            backup(pid, core.MAPPINGS_FILE)
            shutil.move(str(existing), str(dest))
            open_db().archive_versions(pid, dest.name)
        if p["createTeams"]: add_template_teams(tkey, p["createTeams"], union)
        name = p["name"][:100]
        base = f"{pid}-{core.slug(name).title()}"
        folder = core.SRC / base
        folder.mkdir(parents=True)
        (folder / f"{base}.md").write_text(core.doc_to_md(doc), "utf-8")
        (folder / f"{pid.lower()}-{core.slug(name)}.drawio").write_text(core.flow_to_drawio(p["flow"], pid, name), "utf-8")
        for n, data in images.items():
            (folder / core.IMG_DIR).mkdir(exist_ok=True); (folder / core.IMG_DIR / n).write_bytes(data)
        save_refs(pid, p["refs"])
        set_link(pid, tkey)
        snapshot(folder, pid, u, "importacao", f"Importado de {p['meta'].get('gerado_por') or 'arquivo'}" + (f" ({p['id']})" if p["id"] and p["id"] != pid else ""))
    audit(u["login"], "playbook_importado", pid, origem=p["meta"].get("gerado_por", ""), id_original=p["id"], template=tkey,
          substituiu="sim" if existing else "", times_no_template=", ".join(sorted(p["createTeams"])))
    h.send_json({"ok": True, "playbook": load_pb(folder), "teams": core.load_teams(), "summary": summary})

def r_flow_parse(h, **_):
    h.require("editor"); b = h.body()
    try:
        flow, refs, warns = flowdsl.parse(str(b.get("text", ""))[:300_000], core.load_teams())
    except flowdsl.FlowSyntaxError as e:
        raise HttpError(400, str(e))
    validate_flow(flow)
    h.send_json({"flow": flow, "refs": refs, "warnings": warns})

def r_flow_render(h, **_):
    h.require("editor"); b = h.body()
    flow = b.get("flow") or {}
    validate_flow(flow)
    h.send_json({"text": flowdsl.render(flow, b.get("refs") or {}, positions=b.get("positions", True))})

# ───────────────────────── rotas: marca ─────────────────────────

def r_brand_get(h, **_):
    logo = open_db().get_setting("logo")
    h.send_json({**brand(), "logo": logo["v"] if logo else None, "appVersion": APP_VERSION})

def r_brand_put(h, **_):
    u = h.require("admin"); b = h.body()
    cur = brand()
    name = str(b.get("name", cur["name"])).strip()[:40] or DEFAULT_BRAND["name"]
    color = str(b.get("color", cur["color"])).strip().upper() or DEFAULT_BRAND["color"]
    if not HEX_RE.fullmatch(color): raise HttpError(400, "Cor inválida: use #RRGGBB")
    title = " ".join(str(b.get("homeTitle") or cur["homeTitle"]).split())[:120] or DEFAULT_BRAND["homeTitle"]
    sub = " ".join(str(b.get("homeSubtitle", cur["homeSubtitle"]) or "").split())[:600]
    if b.get("homeReset"): title, sub = DEFAULT_BRAND["homeTitle"], DEFAULT_BRAND["homeSubtitle"]
    logo_bg = str(b.get("logoBg", cur["logoBg"]))
    if logo_bg not in LOGO_BGS: raise HttpError(400, "Fundo da logo inválido: use branco ou transparente")
    open_db().set_setting("branding", {"name": name, "color": color, "logoBg": logo_bg, "homeTitle": title, "homeSubtitle": sub}, by=u["login"])
    audit(u["login"], "marca_alterada", nome=name, cor=color, fundo_logo=logo_bg, titulo_inicio=title)
    r_brand_get(h)

def r_logo_put(h, **_):
    u = h.require("admin"); b = h.body()
    m = re.fullmatch(r"data:([\w/+.-]+);base64,([A-Za-z0-9+/=\s]+)", str(b.get("dataUrl", "")))
    if not m or m.group(1) not in LOGO_TYPES: raise HttpError(400, "Envie PNG, JPG, SVG ou WEBP")
    data = base64.b64decode(m.group(2))
    if len(data) > MAX_LOGO: raise HttpError(400, "Logo grande demais (máx. 512 KB)")
    if m.group(1) == "image/svg+xml" and re.search(rb"<script|on\w+\s*=|javascript:", data, re.I):
        raise HttpError(400, "SVG com script não é aceito")
    open_db().set_setting("logo", {"mime": m.group(1), "data": base64.b64encode(data).decode(), "v": secrets.token_hex(4)}, by=u["login"])
    audit(u["login"], "logo_alterada")
    r_brand_get(h)

def r_logo_delete(h, **_):
    u = h.require("admin")
    open_db().set_setting("logo", None)
    audit(u["login"], "logo_removida")
    r_brand_get(h)

def r_logo_get(h, **_):
    logo = open_db().get_setting("logo")
    if not logo: raise HttpError(404, "sem logo")
    h.send_bytes(base64.b64decode(logo["data"]), logo["mime"], sandbox=True)

# ───────────────────────── rotas: reset da aplicação ─────────────────────────
# Volta a instalação ao estado de recém-configurada. Nada é apagado de verdade: o conteúdo vai para
# data/lixeira/reset__<data>/ (playbooks, templates, vínculos, backups e uma cópia do banco).

def r_admin_summary(h, **_):
    h.require("admin")
    db = open_db()
    h.send_json({"playbooks": len(core.all_folders()), "templates": len(tpl._files()), "users": len(db.list_users()),
                 "versions": db.count_all_versions(), "audit": db.count_audit(), "word": RESET_WORD})

def r_admin_reset(h, **_):
    u = h.require("admin"); b = h.body()
    if str(b.get("confirm", "")).strip().upper() != RESET_WORD: raise HttpError(400, f"Para confirmar, digite {RESET_WORD}")
    opts = {k: bool(b.get(k)) for k in ("settings", "users", "audit")}
    if opts["settings"] and (u.get("auth") or "local") == "sso":
        raise HttpError(400, "Sua conta entra pelo SSO e restaurar as configurações desliga o SSO. Use uma conta de administrador com senha local "
                             "ou desmarque “Configurações”.")
    db = open_db()
    with LOCK:
        dest, i = TRASH / f"reset__{time.strftime('%Y%m%d-%H%M%S')}", 1
        while dest.exists(): i += 1; dest = dest.with_name(f"reset__{time.strftime('%Y%m%d-%H%M%S')}-{i}")
        dest.mkdir(parents=True)
        db.backup_to(dest / "playbooks.db")
        moved = []
        for src, name in ((core.SRC, "playbooks"), (tpl.TPL_DIR, "templates"), (core.MAPPINGS_FILE, "mappings.json"), (BACKUPS, ".backups"),
                          *(((DATA_DIR / "logs", "logs"),) if opts["audit"] else ())):
            if Path(src).exists(): shutil.move(str(src), str(dest / name)); moved.append(name)
        core.SRC.mkdir(parents=True, exist_ok=True)
        tpl.ensure_seed()
        db.reset(u["login"], **opts)
        _log_cfg["at"] = 0
        (dest / "LEIA-ME.txt").write_text(
            f"Reset da aplicação feito por {u['login']} em {datetime.now().isoformat(timespec='seconds')}.\n"
            f"Conteúdo guardado: {', '.join(moved + ['playbooks.db (cópia do banco antes do reset)'])}.\n"
            "Para voltar ao estado anterior: pare o servidor, copie estes itens de volta para a pasta de dados\n"
            "(playbooks.db vai em data/) e inicie de novo.\n", "utf-8")
    audit(u["login"], "aplicacao_resetada", lixeira=dest.name, configuracoes="sim" if opts["settings"] else "não",
          usuarios="sim" if opts["users"] else "não", auditoria="sim" if opts["audit"] else "não")
    h.send_json({"ok": True, "archive": dest.name})

# ───────────────────────── rotas: templates ─────────────────────────

def r_tpl_list(h, **_):
    h.require("editor")
    h.send_json({"templates": tpl.list_all(core.load_teams()), "variables": tpl.VARIABLES})

def r_tpl_get(h, tkey, **_):
    h.require("editor")
    cat = core.load_teams()
    h.send_json({"template": tpl.view(tpl.load(tkey, cat), cat), "allTeams": cat})

def _tpl_save(h, u, tkey, t, action, sync=None, **detail):
    with LOCK:
        tpl.save(tkey, {**t, "updated_by": u["name"]})
    if sync: detail["ramos"] = "; ".join(sync)
    audit(u["login"], action, f"template:{tkey}", **detail)
    cat = core.load_teams()
    h.send_json({"ok": True, "template": tpl.view(tpl.load(tkey, cat), cat), "sync": sync or [], "allTeams": cat})

def _tpl_check(t, rev):
    if rev and rev != t["rev"]:
        raise HttpError(409, "Este template foi salvo por outra pessoa depois que você abriu. Recarregue para ver a versão atual.")

def r_tpl_doc(h, tkey, **_):
    u = h.require("editor"); b = h.body()
    doc = b.get("doc")
    if not isinstance(doc, dict) or not str(doc.get("title", "")).strip() or not isinstance(doc.get("sections"), list):
        raise HttpError(400, "documento inválido")
    t = tpl.load(tkey); _tpl_check(t, b.get("rev"))
    old, t["doc"] = t["doc"], core.parse_md(core.doc_to_md(doc))
    changes = ramos.sync_from_doc(t["flow"], t.setdefault("refs", {}), old, t["doc"])
    _tpl_save(h, u, tkey, t, "template_documento_salvo", sync=changes)

def r_tpl_flow(h, tkey, **_):
    u = h.require("editor"); b = h.body()
    flow, refs = b.get("flow") or {}, b.get("refs") or {}
    validate_flow(flow)
    t = tpl.load(tkey); _tpl_check(t, b.get("rev"))
    ids = {n["id"] for n in flow["nodes"]}
    refs = {k: [str(x) for x in v] for k, v in refs.items() if k in ids and isinstance(v, list) and v}
    changes = ramos.sync_from_flow(t["doc"], t["flow"], t.get("refs", {}), flow, refs)
    t["flow"], t["refs"] = flow, refs
    added = tpl.sync_teams(t, core.load_teams())
    _tpl_save(h, u, tkey, t, "template_fluxograma_salvo", sync=changes, **({"times_adicionados": ", ".join(added)} if added else {}))

def r_tpl_ramos(h, tkey, **_):
    u = h.require("editor"); b = h.body()
    t = tpl.load(tkey); _tpl_check(t, b.get("rev"))
    if tpl.has_ramos(t): raise HttpError(400, "Este template já tem ramos")
    tpl.add_ramos(t)
    _tpl_save(h, u, tkey, t, "template_ramos_adicionados", sync=["ramo-protótipo criado no documento e no fluxograma"])

def r_tpl_meta(h, tkey, **_):
    u = h.require("editor"); b = h.body()
    t = tpl.load(tkey); _tpl_check(t, b.get("rev"))
    name = str(b.get("name", t["name"])).strip()[:60]
    if not name: raise HttpError(400, "informe o nome do template")
    t.update(name=name, description=str(b.get("description", t.get("description", "")))[:300],
             owner=str(b.get("owner", t.get("owner", "")))[:60], nist=str(b.get("nist", t.get("nist", "")))[:200])
    _tpl_save(h, u, tkey, t, "template_alterado")

def r_tpl_teams(h, tkey, **_):
    """Times e tags do template (lista completa). Não deixa tirar um time em uso no template ou nos playbooks dele."""
    u = h.require("editor"); b = h.body()
    teams = b.get("teams")
    if not isinstance(teams, dict) or not all(isinstance(v, dict) for v in teams.values()): raise HttpError(400, "times inválidos")
    if len(teams) > 80: raise HttpError(400, "no máximo 80 times por template")
    teams = {str(k).strip(): clean_team(str(k).strip(), v) for k, v in teams.items()}
    with LOCK:
        t = tpl.load(tkey); _tpl_check(t, b.get("rev"))
        removed = set(t.get("teams", {})) - set(teams)
        if removed:
            use = team_usage(tkey)
            busy = {n: sorted(use[n]) for n in removed if n in use}
            if busy:
                raise HttpError(400, "Time em uso, não pode ser retirado: " + "; ".join(f"{n} ({', '.join(w)})" for n, w in busy.items()))
        t["teams"] = teams
    _tpl_save(h, u, tkey, t, "template_times_salvos", removidos=", ".join(sorted(removed)))

def r_tpl_create(h, **_):
    u = h.require("editor"); b = h.body()
    name = str(b.get("name", "")).strip()[:60]
    if not name: raise HttpError(400, "informe o nome do template")
    base = tpl.load(b["from"]) if b.get("from") else tpl.blank(name)
    t = {k: v for k, v in base.items() if k not in ("key", "rev")}
    t.update(name=name, description=str(b.get("description", "")).strip()[:300] or (f"Cópia de {base['name']}" if b.get("from") else ""))
    key = tpl.key_for(name)
    _tpl_save(h, u, key, t, "template_criado", base=b.get("from") or "em branco")

def r_tpl_delete(h, tkey, **_):
    u = h.require("admin")
    f = tpl.path_of(tkey)
    if not f.exists(): raise HttpError(404, "template não encontrado")
    if tkey == tpl.DEFAULT_KEY: raise HttpError(400, "O template Padrão não pode ser excluído (é o template inicial da instalação)")
    with LOCK:
        # playbooks do template excluído passam para o Padrão, que recebe os times e tags que faltarem
        lk, moved = links(), []
        for pid, k in list(lk.items()):
            if k == tkey: lk[pid] = tpl.DEFAULT_KEY; moved.append(pid)
        if moved: add_template_teams(tpl.DEFAULT_KEY, tpl.teams_of_file(f))
        open_db().set_setting("pb_templates", lk)
        dest = TRASH / "templates"; dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), str(dest / f"{f.name}__{time.strftime('%Y%m%d-%H%M%S')}"))
    audit(u["login"], "template_excluido", f"template:{tkey}", playbooks_movidos_para_padrao=", ".join(moved))
    h.send_json({"ok": True, "moved": moved})

def r_tpl_export(h, tkey, **_):
    u = h.require("editor")
    f = tpl.path_of(tkey)
    if not f.exists(): raise HttpError(404, "template não encontrado")
    audit(u["login"], "template_exportado", f"template:{tkey}")
    h.send_bytes(f.read_bytes(), "text/markdown; charset=utf-8", f.name)

def r_tpl_import(h, **_):
    u = h.require("editor"); b = h.body()
    try:
        t = tpl.from_text(str(b.get("text", "")), core.load_teams())
    except (bundle.BundleError, tpl.TemplateError) as e:
        raise HttpError(400, str(e))
    validate_flow(t["flow"])
    warns = t.pop("warnings", [])
    if b.get("dryRun"):
        return h.send_json({"preview": {"name": t["name"], "description": t["description"], "sections": len(t["doc"]["sections"]),
                                        "nodes": len(t["flow"]["nodes"]), "lanes": [l["label"] for l in t["flow"]["lanes"]],
                                        "teams": sorted(t["teams"]), "warnings": warns,
                                        "exists": any(x["name"] == t["name"] for x in tpl.list_all())}})
    if any(x["name"] == t["name"] for x in tpl.list_all()): t["name"] = f"{t['name']} (importado)"
    _tpl_save(h, u, tpl.key_for(t["name"]), t, "template_importado")

def r_people(h, **_):
    h.require("editor")
    h.send_json({"people": [{"login": x["login"], "name": x["name"], "roleName": ROLE_NAMES[x["role"]]}
                            for x in open_db().list_users() if x["active"]]})

# ───────────────────────── rotas: usuários ─────────────────────────

def r_approvers(h, **_):
    h.require("editor")
    h.send_json({"approvers": [{"login": a["login"], "name": a["name"], "roleName": ROLE_NAMES[a["role"]]} for a in open_db().approvers()]})

def r_users(h, **_):
    h.require("admin")
    h.send_json({"users": [public_user(x) for x in open_db().list_users()], "roles": ROLE_NAMES})

def r_user_create(h, **_):
    u = h.require("admin"); b = h.body()
    login = str(b.get("login", "")).strip().lower(); role = b.get("role")
    if not LOGIN_RE.fullmatch(login): raise HttpError(400, "Login: 3 a 80 caracteres (letras minúsculas, números, ponto, hífen, sublinhado ou @)")
    if role not in ROLES: raise HttpError(400, "perfil inválido")
    name = str(b.get("name", "")).strip()[:80] or login
    if b.get("auth") == "sso":     # pré-cadastro: o usuário entra pelo SSO com este login (e-mail ou usuário do provedor)
        new = open_db().create_user(login, name, role, NO_PASSWORD, must_change=False, auth="sso")
        audit(u["login"], "usuario_criado", login, perfil=role, autenticacao="sso")
        return h.send_json({"user": public_user(new), "tempPassword": None})
    pw = temp_password()
    new = open_db().create_user(login, name, role, hash_password(pw), must_change=True)
    audit(u["login"], "usuario_criado", login, perfil=role)
    h.send_json({"user": public_user(new), "tempPassword": pw})

def r_user_update(h, login, **_):
    u = h.require("admin"); b = h.body()
    if login == u["login"] and ("role" in b or b.get("active") is False):
        raise HttpError(400, "Você não pode alterar o próprio perfil nem se desativar")
    if login == u["login"] and "auth" in b: raise HttpError(400, "Você não pode alterar a própria forma de autenticação")
    auth = b.get("auth") if b.get("auth") in ("local", "sso") else None
    name = str(b["name"]).strip()[:80] or login if "name" in b else None
    db = open_db()
    before = db.get_user(login)
    rec = db.update_user(login, name=name, role=b.get("role"), active=b.get("active"), auth=auth)
    pw = None
    if auth == "sso":
        db.set_password(login, NO_PASSWORD, must_change=False)
    elif auth == "local" and before and before.get("auth") == "sso":   # volta a usar senha: gera uma temporária
        pw = temp_password(); db.set_password(login, hash_password(pw), must_change=True)
    audit(u["login"], "usuario_alterado", login, **{k: v for k, v in (("perfil", b.get("role")), ("ativo", b.get("active")), ("autenticacao", auth)) if v is not None})
    h.send_json({"user": public_user(db.get_user(login)), "tempPassword": pw})

def r_user_reset(h, login, **_):
    u = h.require("admin"); db = open_db()
    target = db.get_user(login)
    if not target: raise HttpError(404, "usuário não encontrado")
    if target.get("auth") == "sso": raise HttpError(400, "Conta do SSO: a senha é gerenciada pelo provedor")
    pw = temp_password()
    db.set_password(login, hash_password(pw), must_change=True)
    audit(u["login"], "senha_redefinida", login)
    h.send_json({"user": public_user(db.get_user(login)), "tempPassword": pw})

def r_user_logout(h, login, **_):
    u = h.require("admin")
    n = open_db().delete_user_sessions(login)
    audit(u["login"], "sessoes_encerradas", login, sessoes=n)
    h.send_json({"ok": True, "closed": n})

def r_user_delete(h, login, **_):
    u = h.require("admin")
    if login == u["login"]: raise HttpError(400, "Você não pode excluir o próprio usuário")
    open_db().delete_user(login)
    audit(u["login"], "usuario_excluido", login)
    h.send_json({"ok": True})

def r_audit(h, **_):
    h.require("admin")
    q = h.query()
    h.send_json({"entries": open_db().read_audit(limit=min(int(q.get("limit", 500) or 500), 5000), q=q.get("q", ""))})

# ───────────────────────── rotas: logs (encaminhamento e retenção) ─────────────────────────

SECRET_MASK = "••••••••"

def public_log_cfg(c):
    c = json.loads(json.dumps(c))
    c["http"]["auth_value_set"] = bool(c["http"].get("auth_value")); c["http"]["auth_value"] = ""
    return c

def clean_log_cfg(b, cur):
    c = logfwd.merge(cur)
    try: c["retention_days"] = max(1, min(3650, int(b.get("retention_days", c["retention_days"]))))
    except (TypeError, ValueError): raise HttpError(400, "Retenção inválida")
    # seção não enviada mantém o que está salvo (PUT parcial, ex.: só a retenção)
    hb, sb, fb = b.get("http"), b.get("syslog"), b.get("file")
    hb = hb if isinstance(hb, dict) else {"enabled": c["http"]["enabled"]}
    sb = sb if isinstance(sb, dict) else {"enabled": c["syslog"]["enabled"]}
    fb = fb if isinstance(fb, dict) else {"enabled": c["file"]["enabled"]}
    url = str(hb.get("url", c["http"]["url"])).strip()[:500]
    if hb.get("enabled") and not re.match(r"^https?://[^\s/]+", url, re.I): raise HttpError(400, "URL do HTTP inválida (http:// ou https://)")
    header = str(hb.get("auth_header", c["http"]["auth_header"])).strip()[:80]
    if header and not re.fullmatch(r"[A-Za-z0-9-]+", header): raise HttpError(400, "Nome de cabeçalho inválido")
    c["http"].update(enabled=bool(hb.get("enabled")), url=url, auth_header=header)
    if hb.get("auth_value"): c["http"]["auth_value"] = str(hb["auth_value"])[:2000]
    if hb.get("clear_auth"): c["http"]["auth_value"] = ""
    host = str(sb.get("host", c["syslog"]["host"])).strip()[:255]
    if sb.get("enabled") and not re.fullmatch(r"[A-Za-z0-9.:_-]+", host or ""): raise HttpError(400, "Host do syslog inválido")
    try: port = int(sb.get("port", c["syslog"]["port"]))
    except (TypeError, ValueError): raise HttpError(400, "Porta do syslog inválida")
    if not 1 <= port <= 65535: raise HttpError(400, "Porta do syslog inválida")
    c["syslog"].update(enabled=bool(sb.get("enabled")), host=host, port=port, proto="tcp" if sb.get("proto") == "tcp" else "udp",
                       facility=max(0, min(23, int(sb.get("facility", c["syslog"]["facility"]) or 16))))
    c["file"]["enabled"] = bool(fb.get("enabled"))
    return c

def r_logs_get(h, **_):
    h.require("admin")
    h.send_json({"config": public_log_cfg(log_cfg()), "status": FWD.status(), "logDir": str(DATA_DIR / "logs"),
                 "sample": logfwd.make_event(datetime.now(), "maria.souza", "documento_salvo", "PB-01", {"versao": "0.2"}, "10.0.0.15",
                                             brand()["name"], APP_VERSION)})

def r_logs_put(h, **_):
    u = h.require("admin"); b = h.body()
    c = clean_log_cfg(b, open_db().get_setting("logs"))
    open_db().set_setting("logs", c, by=u["login"]); _log_cfg["at"] = 0
    audit(u["login"], "logs_configurados", retencao_dias=c["retention_days"], http=c["http"]["enabled"], syslog=c["syslog"]["enabled"],
          arquivo=c["file"]["enabled"])
    threading.Thread(target=lambda: (open_db().purge(c["retention_days"]), FWD.purge_files(c["retention_days"])), daemon=True).start()
    r_logs_get(h)

def r_logs_test(h, **_):
    u = h.require("admin"); b = h.body()
    dest = b.get("dest")
    if dest not in ("http", "syslog", "file"): raise HttpError(400, "destino inválido")
    cfg = clean_log_cfg({**(b.get("config") or {}), **{dest: {**((b.get("config") or {}).get(dest) or {}), "enabled": True}}},
                        open_db().get_setting("logs"))
    ev = logfwd.make_event(datetime.now(), u["login"], "teste_de_log", "", {"mensagem": "Evento de teste do Medusa Docs"}, h.client_ip(),
                           brand()["name"], APP_VERSION)
    r = FWD.test(cfg, dest, ev)
    audit(u["login"], "logs_testados", destino=dest, resultado="ok" if r["ok"] else r["message"])
    h.send_json(r)

def r_audit_export(h, **_):
    """Auditoria em JSON Lines (mesmo formato do encaminhamento), dos últimos N dias."""
    u = h.require("admin")
    try: days = max(1, min(3650, int(h.query().get("days", 30))))
    except ValueError: raise HttpError(400, "dias inválidos")
    name, lines = brand()["name"], []
    for r in open_db().audit_since(days):
        d = r["detail"]; ip = d.pop("ip", None)
        lines.append(json.dumps(logfwd.make_event(datetime.fromisoformat(r["ts"]), r["user"], r["action"], r["target"], d, ip, name, APP_VERSION),
                                ensure_ascii=False))
    audit(u["login"], "auditoria_exportada", dias=days, eventos=len(lines))
    h.send_bytes(("\n".join(lines) + "\n").encode("utf-8"), "application/x-ndjson; charset=utf-8", f"auditoria-{date.today().isoformat()}.jsonl")

# ───────────────────────── rotas: SSO (OpenID Connect) ─────────────────────────

SSO_DEFAULT = {"enabled": False, "label": "Entrar com SSO", "issuer": "", "client_id": "", "client_secret": "", "scopes": "openid email profile",
               "public_url": "", "login_claim": "preferred_username", "name_claim": "name", "email_claim": "email",
               "role_claim": "groups", "role_map": {"admin": "", "editor": "", "viewer": ""}, "default_role": "viewer",
               "auto_create": True, "allowed_domains": "", "local_login": "all"}

def sso_cfg():
    c = json.loads(json.dumps(SSO_DEFAULT)); c.update(open_db().get_setting("sso") or {})
    return c

def r_sso_status(h, **_):
    c = sso_cfg()
    h.send_json({"enabled": bool(c["enabled"]), "label": c["label"] or "Entrar com SSO", "localLogin": c["local_login"]})

def r_sso_get(h, **_):
    h.require("admin")
    c = sso_cfg(); c["client_secret_set"] = bool(c.pop("client_secret"))
    h.send_json({"config": c, "redirectUri": sso.redirect_uri(c["public_url"]) if c["public_url"] else ""})

def r_sso_put(h, **_):
    u = h.require("admin"); b = h.body(); c = sso_cfg()
    s = lambda k, n=300: str(b.get(k, c[k]) or "").strip()[:n]
    c.update(label=s("label", 60) or "Entrar com SSO", issuer=s("issuer", 500).rstrip("/"), client_id=s("client_id", 300),
             scopes=s("scopes") or "openid email profile", public_url=s("public_url", 500).rstrip("/"),
             login_claim=s("login_claim", 80) or "preferred_username", name_claim=s("name_claim", 80) or "name",
             email_claim=s("email_claim", 80) or "email", role_claim=s("role_claim", 120), allowed_domains=s("allowed_domains", 500).lower(),
             auto_create=bool(b.get("auto_create", c["auto_create"])), enabled=bool(b.get("enabled")),
             local_login="admins" if b.get("local_login") == "admins" else "all",
             default_role=b.get("default_role") if b.get("default_role") in ("", "viewer", "editor") else "viewer")
    rm = b.get("role_map") if isinstance(b.get("role_map"), dict) else {}
    c["role_map"] = {r: str(rm.get(r, "") or "")[:1000] for r in ("admin", "editor", "viewer")}
    if b.get("client_secret"): c["client_secret"] = str(b["client_secret"])[:2000]
    if b.get("clear_secret"): c["client_secret"] = ""
    if "openid" not in c["scopes"].split(): raise HttpError(400, "Os escopos precisam incluir openid")
    if c["enabled"]:
        if not c["issuer"].lower().startswith("https://") and not c["issuer"].lower().startswith(("http://localhost", "http://127.0.0.1")):
            raise HttpError(400, "O emissor (issuer) precisa ser uma URL https://")
        if not c["client_id"]: raise HttpError(400, "Informe o client ID")
        if not re.match(r"^https?://[^\s/]+", c["public_url"]): raise HttpError(400, "Informe a URL pública da aplicação (ex.: https://playbooks.empresa.com)")
        try: sso.discover(c["issuer"], force=True)
        except sso.SSOError as e: raise HttpError(400, f"Não consegui ler a configuração do provedor: {e}")
    open_db().set_setting("sso", c, by=u["login"])
    audit(u["login"], "sso_configurado", ativo=c["enabled"], emissor=c["issuer"], login_local=c["local_login"])
    r_sso_get(h)

def r_sso_test(h, **_):
    h.require("admin"); b = h.body()
    try:
        d = sso.discover(str(b.get("issuer", "")).strip().rstrip("/"), force=True)
    except sso.SSOError as e:
        return h.send_json({"ok": False, "message": str(e)})
    h.send_json({"ok": True, "issuer": d["issuer"], "authorization_endpoint": d["authorization_endpoint"], "token_endpoint": d["token_endpoint"],
                 "userinfo_endpoint": d.get("userinfo_endpoint", ""), "algs": d.get("id_token_signing_alg_values_supported", [])})

def _sso_cookie(h, value, max_age=600):
    return (f"pbsso={value}; Path=/api/sso; HttpOnly; SameSite=Lax; Max-Age={max_age}" + ("; Secure" if SECURE_COOKIES else ""))

def r_sso_login(h, **_):
    c = sso_cfg()
    if not c["enabled"]: return h.send_redirect("/?sso_error=" + urllib.parse.quote("SSO desativado"))
    try:
        url, state, nonce, verifier = sso.start(c)
    except sso.SSOError as e:
        audit("?", "sso_falhou", motivo=str(e))
        return h.send_redirect("/?sso_error=" + urllib.parse.quote("Provedor de SSO indisponível"))
    open_db().put_sso_state(state, nonce, verifier)
    h.send_redirect(url, [_sso_cookie(h, state)])

def sso_user(c, claims):
    """Encontra, vincula ou cria o usuário do SSO e aplica o perfil. Retorna o registro ou levanta SSOError."""
    db = open_db()
    subject = f"{claims['iss']}|{claims['sub']}"
    email = str(sso.claim(claims, c["email_claim"]) or "").strip().lower()
    raw = str(sso.claim(claims, c["login_claim"]) or email or "").strip().lower()
    login = re.sub(r"[^a-z0-9._@-]", "", raw)[:80]
    name = str(sso.claim(claims, c["name_claim"]) or raw or login).strip()[:80]
    domains = [d.strip().lstrip("@") for d in c["allowed_domains"].split(",") if d.strip()]
    if domains and not any(email.endswith("@" + d) for d in domains): raise sso.SSOError(f"Domínio de e-mail não autorizado ({email or 'sem e-mail'})")
    mapped = sso.map_role(claims, c) if c["role_claim"] else None
    has_rules = bool(c["role_claim"]) and any(str(v).strip() for v in c["role_map"].values())
    u = db.user_by_subject(subject)
    if not u:
        if not LOGIN_RE.fullmatch(login or ""): raise sso.SSOError("O provedor não enviou um login válido (ajuste a claim de login)")
        u = db.get_user(login)
        if u and u.get("auth") != "sso":
            raise sso.SSOError(f"Já existe uma conta local \"{login}\". Peça a um administrador para convertê-la em conta SSO")
        if u and u.get("sso_subject") and u["sso_subject"] != subject: raise sso.SSOError("Esta conta já está vinculada a outra identidade do provedor")
        if u:
            db.bind_subject(login, subject, name); u = db.get_user(login)
        else:
            role = mapped or (c["default_role"] if not has_rules or c["default_role"] else None)
            if not c["auto_create"]: raise sso.SSOError("Usuário não cadastrado. Peça acesso a um administrador")
            if not role: raise sso.SSOError("Seu usuário não pertence a nenhum grupo autorizado")
            u = db.create_user(login, name, role, NO_PASSWORD, must_change=False, auth="sso", sso_subject=subject)
            audit("sistema", "usuario_criado", login, perfil=role, autenticacao="sso")
    if not u["active"]: raise sso.SSOError("Usuário desativado")
    if has_rules:
        role = mapped or c["default_role"]
        if not role: raise sso.SSOError("Seu usuário não pertence a nenhum grupo autorizado")
        if role != u["role"]:
            try:
                db.update_user(u["login"], role=role); audit("sistema", "usuario_alterado", u["login"], perfil=role, origem="grupos do SSO")
            except StoreError:
                pass    # não rebaixa o último administrador ativo
    return db.get_user(u["login"])

def r_sso_callback(h, **_):
    c, q = sso_cfg(), h.query()
    fail = lambda msg, internal=None: (audit("?", "sso_falhou", motivo=internal or msg),
                                       h.send_redirect("/?sso_error=" + urllib.parse.quote(msg), [_sso_cookie(h, "", 0)]))
    if not c["enabled"]: return fail("SSO desativado")
    if q.get("error"): return fail("O provedor recusou o login", f"{q.get('error')}: {q.get('error_description', '')[:200]}")
    st = q.get("state", "")
    ck = SimpleCookie(h.headers.get("Cookie", ""))
    if not st or "pbsso" not in ck or not hmac.compare_digest(ck["pbsso"].value, st): return fail("Sessão de login expirada; tente de novo", "state ausente ou diferente do cookie")
    saved = open_db().pop_sso_state(st)
    if not saved or not q.get("code"): return fail("Sessão de login expirada; tente de novo", "state desconhecido ou vencido")
    try:
        tok, d = sso.exchange(c, q["code"], saved["verifier"])
        claims = sso.validate_id_token(tok["id_token"], d, c["client_id"], saved["nonce"])
        claims = {**sso.userinfo(d, tok.get("access_token"), claims["sub"]), **claims}
        u = sso_user(c, claims)
    except (sso.SSOError, StoreError) as e:
        return fail(str(e))
    db = open_db()
    token = db.create_session(u["login"], h.client_ip(), h.headers.get("User-Agent"))
    audit(u["login"], "login", metodo="sso")
    # página intermediária: a navegação seguinte parte do próprio site, e o cookie de sessão (SameSite=Strict) vale nela
    h.send_html('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=/#/"><title>Entrando…</title>'
                '<p style="font:15px system-ui;margin:40px">Entrando… <a href="/#/">continuar</a></p>',
                [h.session_cookie(token), _sso_cookie(h, "", 0)])

# ───────────────────────── rotas: versões ─────────────────────────

KIND_NAMES = {"base": "Registro inicial", "criacao": "Criação", "importacao": "Importação", "documento": "Documento",
              "fluxograma": "Fluxograma", "ramo": "Ramos", "status": "Status", "restauracao": "Restauração"}

def version_id(h):
    m = re.search(r"/versions/(\d+)", h.path.split("?")[0])
    if not m: raise HttpError(404, "versão não encontrada")
    return int(m.group(1))

def can_see_version(v, u):
    return ROLES[u["role"]] >= ROLES["editor"] or v["status"] in VIEWER_STATUSES

def version_meta(v):
    return {k: v[k] for k in ("id", "version", "status", "created_at", "author", "author_name", "kind", "note", "template")} | \
           {"kindName": KIND_NAMES.get(v["kind"], v["kind"])}

def version_view(folder, pid, v):
    doc = core.parse_md(v["md"])
    flow = core.drawio_to_flow(v["drawio"]) if v["drawio"].strip() else {"subtitle": "", "lanes": core.lanes_of({}), "nodes": [], "edges": []}
    key = v.get("template") if v.get("template") and tpl.KEY_RE.fullmatch(v["template"]) and tpl.path_of(v["template"]).exists() else template_of(pid)
    teams = template_teams(key)
    view = core.build_view(pid, folder.name, doc, flow, v["refs"], teams)
    view.update(teams=teams, templateKey=key, templateName=template_name(key))
    return view

def r_versions(h, pid, **_):
    u = h.require()
    folder = get_folder(pid)
    cur = load_pb(folder)
    if not visible(cur, u): raise HttpError(404, "playbook não encontrado")
    vs = [version_meta(v) for v in open_db().list_versions(pid) if can_see_version(v, u)]
    h.send_json({"versions": vs, "current": core.fmt_version(core.get_version(cur["doc"])), "currentStatus": cur["gov"]["status"]})

def _version(h, pid, u, vid):
    folder = get_folder(pid)
    v = open_db().get_version(pid, vid)
    if not v or not can_see_version(v, u) or not visible(load_pb(folder), u): raise HttpError(404, "versão não encontrada")
    return folder, v

def r_version_get(h, pid, **_):
    u = h.require()
    folder, v = _version(h, pid, u, version_id(h))
    h.send_json({"version": version_meta(v), "playbook": for_role(version_view(folder, pid, v), u)})

def _flow_lines(flow, refs):
    """Fluxograma em linhas comparáveis: uma por caixa e uma por seta (ignora posição)."""
    lanes = {l["key"]: l["label"] for l in core.lanes_of(flow)}
    label = lambda n: " / ".join(l["t"] for l in n.get("lines", []))
    nodes = {n["id"]: n for n in flow["nodes"]}
    out = [f"Raia: {l}" for l in lanes.values()]
    out += [f"[{lanes.get(n['lane'], n['lane'])}] {core.NODE_TYPES.get(n['type'], {}).get('label', n['type'])}: {label(n)}"
            + (f"  → {', '.join(refs.get(n['id'], []))}" if refs.get(n["id"]) else "") for n in flow["nodes"]]
    out += [f"Seta: {label(nodes[e['from']])} → {label(nodes[e['to']])}" + (f" ({e['label']})" if e.get("label") else "")
            for e in flow["edges"] if e["from"] in nodes and e["to"] in nodes]
    return sorted(out)

def _diff(a, b):
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            ops += [{"t": "eq", "text": x} for x in a[i1:i2]]
        else:
            ops += [{"t": "del", "text": x} for x in a[i1:i2]] + [{"t": "add", "text": x} for x in b[j1:j2]]
    return ops

def r_version_diff(h, pid, **_):
    """Compara a versão {v} com outra (?with=<id>) ou com a atual (?with=atual)."""
    u = h.require()
    folder, v = _version(h, pid, u, version_id(h))
    w = h.query().get("with", "atual")
    if w == "atual":
        md, dio = core.files_of(folder)
        other = {"id": None, "version": core.fmt_version(core.get_version(core.parse_md(md.read_text("utf-8")))) + " (atual)",
                 "status": "", "created_at": "", "author": "", "author_name": "", "kind": "atual", "note": "", "template": None,
                 "md": md.read_text("utf-8"), "drawio": dio.read_text("utf-8") if dio else "",
                 "refs": core.read_json(core.MAPPINGS_FILE, {}).get(pid, {})}
    else:
        if not w.isdigit(): raise HttpError(400, "versão de comparação inválida")
        _, other = _version(h, pid, u, int(w))
    a, b = (v, other) if (other["id"] is None or other["id"] > v["id"]) else (other, v)   # sempre da mais antiga para a mais nova
    fl = lambda x: _flow_lines(core.drawio_to_flow(x["drawio"]), x["refs"]) if x["drawio"].strip() else []
    doc_ops, flow_ops = _diff(a["md"].splitlines(), b["md"].splitlines()), _diff(fl(a), fl(b))
    meta = lambda x: version_meta(x) if x["id"] else {"id": None, "version": x["version"], "kindName": "Versão atual"}
    h.send_json({"from": meta(a), "to": meta(b), "doc": doc_ops, "flow": [o for o in flow_ops if o["t"] != "eq"],
                 "stats": {"added": sum(o["t"] == "add" for o in doc_ops), "removed": sum(o["t"] == "del" for o in doc_ops),
                           "flowChanges": sum(o["t"] != "eq" for o in flow_ops)}})

def r_version_restore(h, pid, **_):
    """Volta o conteúdo (documento, fluxograma e vínculos) ao da versão escolhida. Status, aprovador e
    o próprio histórico não mudam: a restauração vira uma nova versão."""
    u = h.require("editor"); b = h.body()
    folder, v = _version(h, pid, u, version_id(h))
    with LOCK:
        check_rev(folder, b.get("rev"))
        ensure_baseline(folder, pid)
        md, dio = core.files_of(folder)
        cur = core.parse_md(md.read_text("utf-8"))
        doc = core.set_gov(core.parse_md(v["md"]), core.get_gov(cur))
        touch_review(doc, u, cur); ver = bump(doc, cur)
        backup(pid, md, dio, core.MAPPINGS_FILE)
        md.write_text(core.doc_to_md(doc), "utf-8")
        if v["drawio"].strip():
            view = load_pb(folder)
            write_flow(folder, pid, view["name"], core.drawio_to_flow(v["drawio"]), dict(v["refs"]))
        snapshot(folder, pid, u, "restauracao", f"Conteúdo da versão {v['version']} ({v['created_at'][:10]})")
    audit(u["login"], "versao_restaurada", pid, de=v["version"], nova=ver)
    h.send_json({"ok": True, "playbook": load_pb(folder), "version": ver})

ROUTES = {
    ("POST", "/api/login"): r_login, ("POST", "/api/logout"): r_logout,
    ("GET", "/api/me"): r_me, ("POST", "/api/me/password"): r_password,
    ("GET", "/api/data"): r_data, ("GET", "/api/pb/{pb}"): r_pb_get,
    ("PUT", "/api/pb/{pb}/doc"): r_pb_doc, ("PUT", "/api/pb/{pb}/flow"): r_pb_flow, ("PUT", "/api/pb/{pb}/status"): r_pb_status,
    ("POST", "/api/pb"): r_pb_create, ("DELETE", "/api/pb/{pb}"): r_pb_delete,
    ("GET", "/api/pb/{pb}/versions"): r_versions, ("GET", "/api/pb/{pb}/versions/{v}"): r_version_get,
    ("GET", "/api/pb/{pb}/versions/{v}/diff"): r_version_diff, ("POST", "/api/pb/{pb}/versions/{v}/restore"): r_version_restore,
    ("POST", "/api/pb/{pb}/img"): r_pb_img_post, ("GET", "/api/pb/{pb}/img/{f}"): r_pb_img_get,
    ("GET", "/api/admin/summary"): r_admin_summary, ("POST", "/api/admin/reset"): r_admin_reset,
    ("POST", "/api/pb/{pb}/ramos"): r_pb_ramo_add, ("DELETE", "/api/pb/{pb}/ramos/{r}"): r_pb_ramo_delete,
    ("POST", "/api/templates/{t}/ramos"): r_tpl_ramos,
    ("GET", "/api/approvers"): r_approvers, ("PUT", "/api/templates/{t}/teams"): r_tpl_teams,
    ("GET", "/api/users"): r_users, ("POST", "/api/users"): r_user_create,
    ("PUT", "/api/users/{u}"): r_user_update, ("DELETE", "/api/users/{u}"): r_user_delete,
    ("POST", "/api/users/{u}/reset"): r_user_reset, ("POST", "/api/users/{u}/logout"): r_user_logout,
    ("GET", "/api/audit"): r_audit, ("GET", "/api/audit/export"): r_audit_export,
    ("GET", "/api/logs"): r_logs_get, ("PUT", "/api/logs"): r_logs_put, ("POST", "/api/logs/test"): r_logs_test,
    ("GET", "/api/sso/status"): r_sso_status, ("GET", "/api/sso/login"): r_sso_login, ("GET", "/api/sso/callback"): r_sso_callback,
    ("GET", "/api/sso/config"): r_sso_get, ("PUT", "/api/sso/config"): r_sso_put, ("POST", "/api/sso/test"): r_sso_test,
    ("GET", "/api/templates"): r_tpl_list, ("POST", "/api/templates"): r_tpl_create, ("POST", "/api/templates/import"): r_tpl_import,
    ("GET", "/api/templates/{t}"): r_tpl_get, ("DELETE", "/api/templates/{t}"): r_tpl_delete, ("GET", "/api/templates/{t}/export"): r_tpl_export,
    ("PUT", "/api/templates/{t}/doc"): r_tpl_doc, ("PUT", "/api/templates/{t}/flow"): r_tpl_flow, ("PUT", "/api/templates/{t}/meta"): r_tpl_meta,
    ("GET", "/api/people"): r_people,
    ("GET", "/api/pb/{pb}/export"): r_pb_export, ("GET", "/api/export"): r_export_all, ("POST", "/api/import"): r_import,
    ("POST", "/api/flow/parse"): r_flow_parse, ("POST", "/api/flow/render"): r_flow_render,
    ("GET", "/api/branding"): r_brand_get, ("PUT", "/api/branding"): r_brand_put,
    ("GET", "/api/branding/logo"): r_logo_get, ("PUT", "/api/branding/logo"): r_logo_put, ("DELETE", "/api/branding/logo"): r_logo_delete,
}

# ───────────────────────── linha de comando ─────────────────────────

def cmd_adduser(args):
    login = args.login.strip().lower()
    if not LOGIN_RE.fullmatch(login): sys.exit("Login inválido (3 a 40: letras minúsculas, números, . _ -)")
    pw = getpass.getpass(f"Senha para {login}: ")
    if getpass.getpass("Repita a senha: ") != pw: sys.exit("As senhas não conferem.")
    try: validate_password(pw)
    except HttpError as e: sys.exit(e.msg)
    db = open_db()
    old = db.get_user(login)
    db.upsert_user(login, args.name or (old and old["name"]) or login, args.role, hash_password(pw))
    audit("cli", "usuario_cli", login, perfil=args.role)
    print(f"Usuário {login} salvo com perfil {ROLE_NAMES[args.role]} em {DB.path}")

def bootstrap_admin():
    """Primeira subida (ex.: Docker): cria o administrador indicado em MEDUSA_ADMIN_LOGIN se ainda não há nenhum.
    Sem MEDUSA_ADMIN_PASSWORD, gera uma senha temporária e a mostra uma única vez no log; a troca é obrigatória."""
    db = open_db()
    login = os.environ.get("MEDUSA_ADMIN_LOGIN", "").strip().lower()
    if db.count_active_admins() >= 1 or not login: return
    if not LOGIN_RE.fullmatch(login): sys.exit("MEDUSA_ADMIN_LOGIN inválido (3 a 40: letras minúsculas, números, . _ -)")
    pw = os.environ.get("MEDUSA_ADMIN_PASSWORD") or ""
    generated = not pw
    if generated: pw = temp_password()
    try: validate_password(pw)
    except HttpError as e: sys.exit(f"MEDUSA_ADMIN_PASSWORD: {e.msg}")
    name, hsh = (os.environ.get("MEDUSA_ADMIN_NAME") or "Administrador").strip()[:80], hash_password(pw)
    if db.get_user(login): db.upsert_user(login, name, "admin", hsh)
    else: db.create_user(login, name, "admin", hsh, must_change=True)
    db.set_password(login, hsh, True)
    audit("sistema", "admin_inicial", login)
    print("=" * 64)
    print(f"Administrador inicial criado: {login}")
    print(f"Senha temporária: {pw}" if generated else "Senha: a definida em MEDUSA_ADMIN_PASSWORD")
    print("A troca de senha é obrigatória no primeiro acesso.")
    print("=" * 64, flush=True)

def main():
    global SECURE_COOKIES
    if len(sys.argv) > 1 and sys.argv[1] == "adduser":
        p = argparse.ArgumentParser(prog="server.py adduser")
        p.add_argument("cmd"); p.add_argument("login")
        p.add_argument("--role", choices=list(ROLES), default="viewer"); p.add_argument("--name")
        return cmd_adduser(p.parse_args())
    p = argparse.ArgumentParser(description="Servidor da ferramenta de playbooks")
    p.add_argument("port_pos", nargs="?", type=int, help=argparse.SUPPRESS)
    env = os.environ.get
    p.add_argument("--host", default=env("MEDUSA_HOST", "127.0.0.1"), help="use 0.0.0.0 para expor na rede (atrás de proxy HTTPS)")
    p.add_argument("--port", type=int, default=int(env("MEDUSA_PORT", "8765")))
    p.add_argument("--secure-cookies", action="store_true", default=env("MEDUSA_SECURE_COOKIES", "").lower() in ("1", "true", "yes", "sim"),
                   help="marca o cookie como Secure (use com HTTPS)")
    a = p.parse_args()
    SECURE_COOKIES = a.secure_cookies
    port = a.port_pos or a.port
    if tpl.ensure_seed():
        print("Template \"Padrão\" criado em", tpl.TPL_DIR)
    core.SRC.mkdir(parents=True, exist_ok=True)
    bootstrap_admin()
    global FWD
    FWD = logfwd.Forwarder(log_cfg, DATA_DIR / "logs")
    threading.Thread(target=retention_loop, name="retention", daemon=True).start()
    if open_db().count_active_admins() < 1:
        sys.exit("Nenhum administrador cadastrado. Crie o primeiro com:\n"
                 f"  python3 {Path(__file__).name} adduser <login> --role admin --name \"Seu Nome\"\n"
                 "ou defina MEDUSA_ADMIN_LOGIN para criá-lo com senha temporária (ver INSTALACAO-DOCKER.md).")
    srv = ThreadingHTTPServer((a.host, port), Handler)
    print(f"Playbooks em http://{'localhost' if a.host in ('127.0.0.1', '::1') else a.host}:{port}  (Ctrl+C para parar)")
    print(f"Banco de dados: {DB.path}")
    if a.host not in ("127.0.0.1", "::1", "localhost") and not a.secure_cookies:
        print("Atenção: exposto na rede sem --secure-cookies. Use um proxy com HTTPS.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
