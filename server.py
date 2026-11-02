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

Roles e permissões (perms.py)
  Cada usuário tem uma role (users.role_id) e cada role uma lista de permissões "área.ação" (playbook.edit,
  users.manage…). As roles do sistema reproduzem os perfis da 2.x: Visualizador (lê Homologação e Produção),
  Editor (lê, cria e edita; muda status; edita templates) e Administrador (tudo). O administrador cria outros.

Usuários, sessões, tentativas de login, auditoria e configurações ficam no banco SQLite data/playbooks.db (store.py).
Só depende da biblioteca padrão. Para expor na rede, publique atrás de um proxy com HTTPS
e rode com --secure-cookies.
"""
import argparse, base64, difflib, getpass, gzip, hashlib, hmac, io, json, os, re, secrets, shutil, signal, socket, sys, threading, time, urllib.parse, zipfile
from datetime import date, datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import bundle
import doctypes as DT
import library
import logfwd
import ramos
import sso
import flowdsl
import pbcore as core
import perms as P
import templates as tpl
from store import Store, StoreError

DATA_DIR = Path(os.environ.get("PB_DATA") or core.HOME / "data")
TRASH = DATA_DIR / "lixeira"
BACKUPS = Path(os.environ.get("PB_BACKUPS") or core.HOME / ".backups")

ROLE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")
VIEWER_STATUSES = {"Homologação", "Produção"}
SESSION_TTL = int(float(os.environ.get("MEDUSA_SESSION_IDLE_HOURS") or 8) * 3600)    # inatividade máxima
SESSION_MAX = int(float(os.environ.get("MEDUSA_SESSION_MAX_HOURS") or 24) * 3600)    # duração máxima, mesmo em uso
COOKIE_RENEW = 600              # o cookie é reemitido (prazo renovado) no máximo a cada 10 min de uso
MAX_THREADS = 32                # requisições processadas ao mesmo tempo; as demais esperam a vez
PBKDF2_ITERS = 310_000
MIN_PASSWORD = 10
MAX_BODY = 8 * 1024 * 1024
APP_VERSION = "3.2.0"
LOGIN_RE = re.compile(r"^[a-z0-9._@-]{3,80}$")          # @ e até 80 caracteres: logins vindos do SSO (e-mail)
NO_PASSWORD = "!sso"                                      # hash impossível: conta só entra pelo SSO
TRUST_PROXY = os.environ.get("MEDUSA_TRUST_PROXY", "").lower() in ("1", "true", "yes", "sim")
REQ = threading.local()                                   # IP da requisição em andamento (para a auditoria)
STATIC = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/flow.js": "flow.js",
          "/editor.js": "editor.js", "/style.css": "style.css", "/theme.js": "theme.js", "/docs.js": "docs.js",
          "/icons.js": "icons.js"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon", ".woff2": "font/woff2"}

LOGO_BGS = ("white", "transparent")       # fundo atrás da logo no topo: branco (legível em qualquer cor) ou transparente
DEFAULT_BRAND = {"name": "Medusa Docs", "color": "#3B5BDB", "logoBg": "white", "contact": "", "homeTitle": "Playbooks de resposta a incidentes",
                 "homeSubtitle": "Base interativa dos playbooks do time de segurança. Escolha um playbook, navegue pelo fluxograma e clique "
                                 "em qualquer caixa, ramo (R1…), passo (T0, A3…) ou time para ler o trecho da documentação."}
LOGO_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg", "image/webp": ".webp"}
MAX_LOGO = 512 * 1024
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
IMG_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
IMG_MIME = {v: k for k, v in IMG_TYPES.items()}
MAX_IMG = 3 * 1024 * 1024
RESET_WORD = "RESETAR"

MAX_NODES, MAX_EDGES, MAX_LINE = 400, 800, 500

LOCK = threading.RLock()        # serializa gravações nos arquivos dos playbooks
SECURE_COOKIES = False
DB: Store = None


def open_db():
    global DB
    if DB is None:
        DB = Store(DATA_DIR / "playbooks.db", session_ttl=SESSION_TTL, session_max=SESSION_MAX)
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
    """role: valor legado (viewer/editor/admin), mantido para quem já lê a API; roleId é o papel de verdade."""
    return {"login": u["login"], "name": u["name"], "role": u["role"], "roleId": u["role_id"], "roleName": u["role_name"],
            "permissions": sorted(u["perms"]),
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
    core.atomic_write(core.MAPPINGS_FILE, json.dumps(allm, ensure_ascii=False, indent=2) + "\n")

# ───────────────────────── playbooks ─────────────────────────

def today(): return date.today().strftime("%d/%m/%Y")

def not_found_msg(pid):
    t = DT.type_of(pid)
    return f"{DT.info(t)['label'].lower() if t else 'documento'} não encontrado"

def get_folder(pid):
    if not pid or not core.ID_RE.fullmatch(pid): raise HttpError(404, not_found_msg(pid))
    f = core.folder_of(pid)
    if not f: raise HttpError(404, not_found_msg(pid))
    return f

def check_rev(folder, rev):
    if not rev: raise HttpError(400, "Informe a revisão do documento (recarregue a página e tente de novo)")
    if rev != core.revision(folder):
        raise HttpError(409, "Este documento foi salvo por outra pessoa depois que você abriu. Recarregue para ver a versão atual.")

# ───────────────────────── permissões ─────────────────────────

def doc_type(pid):
    """Tipo do documento pelo prefixo do ID (PB → playbook, RB → runbook, DOC → doc)."""
    return DT.type_of(pid) or "playbook"

def type_info(pid):
    return DT.info(doc_type(pid))

def doc_perm(pid, action):
    return f"{doc_type(pid)}.{action}"

def any_type(action):
    return tuple(f"{t}.{action}" for t in P.TYPES)

def can(u, perm):
    return perm in u["perms"]

def is_admin(u):
    return u["role_id"] == "admin"

def can_view_status(u, t, status):
    """Ver um documento (ou versão) do tipo t neste status: Homologação/Produção com t.view; Desenvolvimento também com t.view_drafts."""
    return can(u, f"{t}.view") and (can(u, f"{t}.view_drafts") or status in VIEWER_STATUSES)

def visible(pb, user):
    return can_view_status(user, doc_type(pb["id"]), pb["gov"]["status"])

def for_role(pb, user):
    if not can(user, doc_perm(pb["id"], "edit")):
        pb = {k: v for k, v in pb.items() if k not in ("doc", "folder")}
    return pb

def perms_tag(u):
    """Identifica o conjunto de permissões (entra no ETag: papéis diferentes veem respostas diferentes)."""
    return hashlib.sha1(",".join(sorted(u["perms"])).encode()).hexdigest()[:12]

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
    nodes, edges = flow.get("nodes", []), flow.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list): raise HttpError(400, "fluxograma inválido")
    if len(nodes) > MAX_NODES: raise HttpError(400, f"no máximo {MAX_NODES} caixas por fluxograma")
    if len(edges) > MAX_EDGES: raise HttpError(400, f"no máximo {MAX_EDGES} setas por fluxograma")
    ids = set()
    for n in nodes:
        if not isinstance(n, dict): raise HttpError(400, "caixa inválida")
        if n.get("lane") not in lanes or n.get("type") not in core.NODE_TYPES:
            raise HttpError(400, f"caixa inválida: {n.get('id')}")
        if not re.fullmatch(r"[\w-]{1,40}", str(n.get("id", ""))) or n["id"] in ids:
            raise HttpError(400, f"id de caixa inválido ou repetido: {n.get('id')}")
        lines = n.get("lines", [])
        if not isinstance(lines, list) or any(not isinstance(l, dict) or len(str(l.get("t", ""))) > MAX_LINE for l in lines):
            raise HttpError(400, f"texto inválido ou longo demais na caixa {n['id']} (máx. {MAX_LINE} caracteres por linha)")
        ids.add(n["id"])
    for e in edges:
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not e["id"].strip() or len(e["id"]) > 80:
            raise HttpError(400, "seta sem id")
        if e.get("from") not in ids or e.get("to") not in ids:
            raise HttpError(400, f"seta ligada a caixa inexistente: {e.get('id')}")
        if e.get("type") not in core.EDGE_TYPES:
            raise HttpError(400, f"tipo de seta inválido: {e.get('type')}")
        if e["id"] in ids:
            raise HttpError(400, f"seta com o mesmo id de uma caixa: {e['id']}")
        if e.get("lock"): e["lock"] = True
        else: e.pop("lock", None)
        lp = e.get("lp")
        if lp is not None:
            try: e["lp"] = {"dx": max(-2000.0, min(2000.0, float(lp["dx"]))), "dy": max(-2000.0, min(2000.0, float(lp["dy"])))}
            except (TypeError, KeyError, ValueError): e.pop("lp", None)
            if e.get("lp") == {"dx": 0.0, "dy": 0.0}: e.pop("lp")

# ───────────────────────── HTTP ─────────────────────────
# HTTP/1.1 com keep-alive, gzip para respostas de texto acima de 1 KB, ETag/304 nas leituras que mudam pouco
# e estáticos versionados (?v=<versão>-<hash>) com cache longo. O index.html é sempre revalidado.

GZIP_MIN = 1024
COMPRESSIBLE = ("application/json", "text/", "image/svg+xml", "application/xml", "application/x-ndjson")
SLOTS = threading.BoundedSemaphore(MAX_THREADS)
STATIC_VERSIONED = "public, max-age=31536000, immutable"
_static, _build = {}, {"sig": None, "id": APP_VERSION}
_cookie_at = {}                 # hash do token → quando o cookie foi emitido pela última vez (renovação)


def build_id():
    """Versão dos estáticos: APP_VERSION + hash curto do conteúdo de todos eles (muda a cada alteração)."""
    files = sorted(set(STATIC.values()) - {"index.html"})
    sig = tuple((f, (core.HERE / f).stat().st_mtime_ns, (core.HERE / f).stat().st_size) for f in files)
    if sig != _build["sig"]:
        h = hashlib.sha1()
        for f in files: h.update((core.HERE / f).read_bytes())
        _build.update(sig=sig, id=f"{APP_VERSION}-{h.hexdigest()[:10]}")
    return _build["id"]


def render_index(data):
    """index.html com ?v=<build> nos <script> e <link> locais: o navegador nunca mistura JS antigo com API nova."""
    v = build_id()
    names = "|".join(re.escape(f) for f in set(STATIC.values()) - {"index.html"})
    return re.sub(rf'((?:src|href)=")({names})(")', lambda m: f"{m.group(1)}{m.group(2)}?v={v}{m.group(3)}", data.decode("utf-8")).encode("utf-8")


def static_entry(path):
    """(bytes, gzip ou None, ETag) de um arquivo estático, comprimido uma vez e guardado até o arquivo mudar."""
    st = path.stat()
    sig = (st.st_mtime_ns, st.st_size, build_id() if path.name == "index.html" else None)
    c = _static.get(path)
    if c and c[0] == sig: return c[1:]
    data = path.read_bytes()
    if path.name == "index.html": data = render_index(data)
    gz = gzip.compress(data, 9) if path.suffix in (".js", ".css", ".html", ".svg", ".txt") and len(data) > GZIP_MIN else None
    c = _static[path] = (sig, data, gz, '"' + hashlib.sha1(data).hexdigest()[:16] + '"')
    return c[1:]


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128


class Handler(BaseHTTPRequestHandler):
    server_version = "Playbooks"
    sys_version = ""
    protocol_version = "HTTP/1.1"      # keep-alive; toda resposta leva Content-Length
    timeout = 30                       # conexão parada (ou lenta demais) é encerrada

    def log_message(self, fmt, *args):
        if args and "/api/" in str(args[0]) and not (self.client_address[0] in ("127.0.0.1", "::1") and "/api/branding " in str(args[0])):
            if "/api/sso/callback" in str(args[0]): args = (re.sub(r"\?\S*", "?…", str(args[0])),) + args[1:]   # não registra code/state
            sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def headers_common(self, csp=None, cache=None):
        renew = getattr(REQ, "cookie", None)
        if renew: self.send_header("Set-Cookie", renew); REQ.cookie = None
        self.send_header("Cache-Control", cache or "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", csp or
                         "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; form-action 'self'")

    def accepts_gzip(self):
        return "gzip" in (self.headers.get("Accept-Encoding") or "").lower()

    def not_modified(self, etag):
        inm = self.headers.get("If-None-Match") or ""
        return bool(etag) and (inm.strip() == "*" or etag in [x.strip() for x in inm.split(",")])

    def send_body(self, body, ctype, status=200, cookie=None, etag=None, cache=None, csp=None, gz=None, extra=()):
        """Envia a resposta: 304 se o ETag confere; gzip quando o cliente aceita e o corpo é texto > 1 KB."""
        if etag and status == 200 and self.not_modified(etag):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Content-Length", "0")
            self.headers_common(csp, cache)
            self.end_headers()
            return
        enc = None
        if self.accepts_gzip():
            if gz is not None: body, enc = gz, "gzip"
            elif len(body) > GZIP_MIN and ctype.startswith(COMPRESSIBLE): body, enc = gzip.compress(body, 5), "gzip"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if enc: self.send_header("Content-Encoding", enc)
        if ctype.startswith(COMPRESSIBLE): self.send_header("Vary", "Accept-Encoding")
        if etag: self.send_header("ETag", etag)
        if cookie: self.send_header("Set-Cookie", cookie)
        for k, v in extra: self.send_header(k, v)
        self.headers_common(csp, cache)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj, status=200, cookie=None, etag=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_body(body, "application/json; charset=utf-8", status, cookie=cookie, etag=etag, cache="private, no-cache")

    def send_file(self, path, cache=None):
        data, gz, etag = static_entry(path)
        self.send_body(data, TYPES.get(path.suffix, "application/octet-stream"), etag=etag, cache=cache or "no-cache", gz=gz)

    def send_bytes(self, data, ctype, filename=None, sandbox=False, etag=None, cache=None):
        self.send_body(data, ctype, etag=etag, cache=cache, csp="default-src 'none'; style-src 'unsafe-inline'; sandbox" if sandbox else None,
                       extra=[("Content-Disposition", f'attachment; filename="{filename}"')] if filename else ())

    def body(self):
        try: n = int(self.headers.get("Content-Length") or 0)
        except ValueError: raise HttpError(400, "Content-Length inválido")
        if n < 0: raise HttpError(400, "Content-Length inválido")
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

    def require(self, perm=None, *, any_of=(), allow_must_change=False):
        """Usuário da sessão; 401 sem sessão, 403 sem a permissão (perm) ou sem nenhuma de any_of."""
        tok = self.cookie_token()
        u = open_db().session_user(tok)
        if not u: raise HttpError(401, "Faça login para continuar")
        self.renew_cookie(tok, u)
        if u["must_change"] and not allow_must_change: raise HttpError(403, "Troque a senha temporária para continuar")
        if (perm and perm not in u["perms"]) or (any_of and not any(p in u["perms"] for p in any_of)):
            raise HttpError(403, "Seu perfil não tem permissão para esta ação")
        return u

    def renew_cookie(self, tok, u):
        """Sessão em uso: reemite o cookie (no máximo a cada 10 min) para o prazo de inatividade recomeçar.
        O prazo nunca passa da duração máxima da sessão (MEDUSA_SESSION_MAX_HOURS)."""
        th, now = hashlib.sha256(tok.encode()).hexdigest(), time.time()
        if now - _cookie_at.get(th, 0) < COOKIE_RENEW: return
        if len(_cookie_at) > 10000: _cookie_at.clear()
        _cookie_at[th] = now
        left = int((u.get("session_created") or now) + SESSION_MAX - now)
        if left > 0: REQ.cookie = self.session_cookie(tok, min(SESSION_TTL, left))

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
        REQ.cookie = None
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
        # /api/doc/{id}[/...] é sinônimo de /api/pb/{id}[/...] (a API nova; a antiga continua valendo)
        path = re.sub(rf"^/api/doc/(?={DT.PID_IN_PATH}(?:/|$))", "/api/pb/", self.path.split("?")[0])
        REQ.ip, REQ.cookie = self.client_ip(), None
        try:
            if method != "GET": self.csrf()
            key = re.sub(rf"/{DT.PID_IN_PATH}(?=/|$)", "/{pb}", re.sub(r"^/api/users/[^/]+", "/api/users/{u}", path))
            key = re.sub(r"^/api/folders/\d+$", "/api/folders/{f}", key)
            key = re.sub(r"^(/api/pb/\{pb\}/ramos)/[^/]+$", r"\1/{r}", key)
            key = re.sub(r"^(/api/pb/\{pb\}/versions)/\d+", r"\1/{v}", key)
            key = re.sub(r"^(/api/pb/\{pb\}/img)/[^/]+$", r"\1/{f}", key)
            if not path.startswith("/api/templates/import"):
                key = re.sub(r"^/api/templates/[^/]+", "/api/templates/{t}", key)
            key = re.sub(r"^/api/roles/[^/]+$", "/api/roles/{role}", key)
            key = re.sub(r"^(/api/pb/\{pb\}/suggestions)/\d+", r"\1/{s}", key)
            route = ROUTES.get((method, key))
            if not route: raise HttpError(404, "não encontrado")
            m = re.search(rf"/({DT.PID_IN_PATH})(?:/|$)", path); u = re.match(r"^/api/users/([^/]+)", path)
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
        with SLOTS:
            path, _, qs = self.path.partition("?")
            if path.startswith("/api/"): return self.handle_api("GET")
            REQ.cookie = None
            if path in STATIC:
                versioned = STATIC[path] != "index.html" and re.search(r"(^|&)v=", qs)
                return self.send_file(core.HERE / STATIC[path], cache=STATIC_VERSIONED if versioned else "no-cache")
            m = re.fullmatch(r"/assets/([\w.-]+)", path)
            if m and (core.HERE / "assets" / m.group(1)).is_file() and Path(m.group(1)).suffix in TYPES:
                return self.send_file(core.HERE / "assets" / m.group(1), cache="public, max-age=604800")   # fontes e imagens fixas
            self.send_json({"error": "não encontrado"}, 404)

    def do_POST(self):
        with SLOTS: self.handle_api("POST")

    def do_PUT(self):
        with SLOTS: self.handle_api("PUT")

    def do_DELETE(self):
        with SLOTS: self.handle_api("DELETE")

# ───────────────────────── rotas: sessão ─────────────────────────

def r_login(h, **_):
    db = open_db(); b = h.body()
    login, pw = str(b.get("login", "")).strip().lower()[:80], str(b.get("password", ""))
    ip = h.client_ip(); key = f"{login}|{ip}"
    wait = db.locked_for(key)
    if wait: raise HttpError(429, f"Acesso bloqueado por segurança após várias tentativas. Tente de novo em {int(wait // 60) + 1} min.")
    u = db.get_user(login)
    if not (check_password(pw, u["hash"] if u else DUMMY_HASH) and u and u["active"]):
        left = db.register_fail(key)
        audit(login or "?", "login_falhou", ip=ip)
        msg = "Usuário ou senha incorretos." + (" Contas do SSO entram pelo botão de SSO." if u and u.get("auth") == "sso" else "")
        lock_min = db.lock_seconds // 60
        # o aviso vem antes do bloqueio, para quem está digitando sob pressão (Caps Lock, teclado trocado) não ser pego de surpresa
        if not left: raise HttpError(429, f"{msg} Por segurança, o acesso foi bloqueado por {lock_min} min.")
        if left <= 2: msg += f" Mais {left} tentativa{'s' if left > 1 else ''} errada{'s' if left > 1 else ''} e o acesso fica bloqueado por {lock_min} min."
        raise HttpError(401, msg)
    cfg = sso_cfg()
    if cfg["enabled"] and cfg.get("local_login") == "admins" and u["role_id"] != "admin":
        audit(login, "login_falhou", ip=ip, motivo="login local restrito a administradores")
        raise HttpError(403, "O login por senha está desativado. Use o botão de SSO.")
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
    """Template do documento (vínculo no banco); sem vínculo, ou se o template sumiu, o padrão do tipo."""
    k = (lk if lk is not None else links()).get(pid)
    t = doc_type(pid)
    return k if k and tpl.KEY_RE.fullmatch(k) and tpl.path_of(k).exists() and tpl.kind_for(k) == t else tpl.default_key(t)

def template_teams(key):
    """Times do template (cache por arquivo; somente leitura)."""
    return tpl.teams_for(key)

def template_name(key):
    return tpl.name_for(key)

def pid_of(folder):
    return core.pid_of_folder(folder)

def load_pb_fresh(folder, lk=None):
    """Lê direto do disco, sem cache: usado nas gravações, que precisam do estado do arquivo neste instante."""
    pid = pid_of(folder)
    key = template_of(pid, lk)
    teams = template_teams(key)
    v = core.load_playbook(folder, teams)
    v.update(templateKey=key, templateName=template_name(key), teams=teams)
    return v

def load_pb(folder, lk=None):
    """Documento completo pelo cache (library.py). Somente leitura: quem for alterar usa load_pb_fresh."""
    return LIB.view(pid_of(folder)) or load_pb_fresh(folder, lk)

LIB = library.Library(core, tpl, links=lambda: links(), template_of=lambda pid, lk: template_of(pid, lk),
                      cache_file=DATA_DIR / "cache" / "biblioteca.json")

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
    """Lista completa (formato da 2.1). Deprecada: o front usa /api/bootstrap, /api/library e /api/doc/{id}. Sai na 3.1."""
    u = h.require()
    pbs = [v for v in (LIB.view(pid) for pid in LIB.pids()) if v]
    h.send_json({"playbooks": [for_role(p, u) for p in pbs if visible(p, u)], "teams": core.load_teams(),
                 "catalog": core.CATALOG, "statuses": core.STATUSES})

def doc_etag(pb, u):
    sig = tpl.file_sig(pb.get("templateKey") or tpl.DEFAULT_KEY)
    return '"' + hashlib.sha1(json.dumps([pb.get("rev"), sig, perms_tag(u)]).encode()).hexdigest()[:20] + '"'

def r_pb_get(h, pid, **_):
    u = h.require()
    pb = load_pb(get_folder(pid))
    if not visible(pb, u): raise HttpError(404, "playbook não encontrado")
    h.send_json({"playbook": for_role(pb, u)}, etag=doc_etag(pb, u))

def summary_visible(u):
    return lambda s: can_view_status(u, s["type"], s["status"])

def r_bootstrap(h, **_):
    """Tudo o que o front precisa para abrir, sem a lista de documentos."""
    u = h.require()
    logo = open_db().get_setting("logo")
    h.send_json({"user": public_user(u), "branding": {**brand(), "logo": logo["v"] if logo else None}, "catalog": core.CATALOG,
                 "statuses": core.STATUSES, "teams": core.load_teams(), "appVersion": APP_VERSION,
                 "types": DT.public(), "enabledTypes": list(P.ENABLED_TYPES)})

LIBRARY_SORTS = {"id": lambda s: core.sort_key(s["id"]), "name": lambda s: library.norm(s["name"]),
                 "status": lambda s: (core.STATUSES.index(s["status"]), core.sort_key(s["id"]))}

def folder_descendants(dtype, fid):
    kids = {}
    for f in open_db().folders(dtype): kids.setdefault(f["parent_id"], []).append(f["id"])
    out, stack = set(), [fid]
    while stack:
        x = stack.pop(); out.add(x); stack += kids.get(x, [])
    return out

def r_library(h, **_):
    """Lista leve, filtrada e paginada: ?type=&status=&q=&sort=id|name|status&limit=&cursor=
    &folder=<id>|none (&recursive=1) &fields.<chave>=a,b. Devolve também contagens por status e "facets" dos campos
    marcados como filtro no template (contagem por valor, sobre o que passou pelos demais filtros)."""
    u = h.require(); q = h.query()
    typ, status, text, sort = q.get("type") or "", q.get("status") or "", q.get("q", "").strip()[:200], q.get("sort") or "id"
    if typ and typ not in DT.TYPES: raise HttpError(400, "tipo de documento inválido")
    if status and status not in core.STATUSES: raise HttpError(400, "status inválido")
    if sort not in LIBRARY_SORTS: raise HttpError(400, "ordenação inválida")
    try: limit, offset = max(1, min(500, int(q.get("limit") or 100))), max(0, int(q.get("cursor") or 0))
    except ValueError: raise HttpError(400, "paginação inválida")
    folder = q.get("folder") or ""
    if folder and folder != "none" and not folder.isdigit(): raise HttpError(400, "pasta inválida")
    ffilters = {k[7:]: [x for x in v.split(",") if x] for k, v in q.items() if k.startswith("fields.") and v}
    LIB.scan()
    etag = '"' + hashlib.sha1(json.dumps([BOOT_ID, LIB.generation, FOLDER_GEN[0], SUGG_GEN[0], typ, status, text, sort, limit, offset, folder, q.get("recursive"),
                                         sorted(ffilters.items()), perms_tag(u)]).encode()).hexdigest()[:20] + '"'
    if h.not_modified(etag): return h.send_json({}, etag=etag)
    fmap, scount = open_db().doc_folders(typ or None), open_db().open_suggestion_counts()
    items = [{**s, "folderId": fmap.get(s["id"]), "suggestions": scount.get(s["id"], 0)} for s in LIB.summaries(summary_visible(u), dtype=typ or None)]
    counts = {st: sum(1 for s in items if s["status"] == st) for st in core.STATUSES}
    if status: items = [s for s in items if s["status"] == status]
    if text:
        words = library.norm(text).split()
        items = [s for s in items if all(w in library.norm(f"{s['id']} {s['name']} {s['subtitle']}") for w in words)]
    if folder == "none":
        items = [s for s in items if s["folderId"] is None]
    elif folder:
        if not typ: raise HttpError(400, "informe o tipo para filtrar por pasta")
        ids = folder_descendants(typ, int(folder)) if q.get("recursive") in ("1", "true") else {int(folder)}
        items = [s for s in items if s["folderId"] in ids]
    schema = {f["key"]: f for key in {s["templateKey"] for s in items} for f in tpl.fields_for(key)} if typ else {}
    facets = {}
    for k, f in schema.items():
        if not f.get("filter"): continue
        cnt = {}
        for s in items:
            v = s["fields"].get(k)
            for x in (v if isinstance(v, list) else [v] if v else []): cnt[x] = cnt.get(x, 0) + 1
        facets[k] = {"label": f["label"], "values": cnt}
    for k, wanted in ffilters.items():
        items = [s for s in items if set(s["fields"].get(k) if isinstance(s["fields"].get(k), list) else [s["fields"].get(k)]) & set(wanted)]
    items = sorted(items, key=LIBRARY_SORTS[sort])
    end = offset + limit
    h.send_json({"items": items[offset:end], "total": len(items), "nextCursor": str(end) if end < len(items) else None,
                 "counts": counts, "all": sum(counts.values()), "facets": facets}, etag=etag)

def r_search(h, **_):
    u = h.require(); q = h.query()
    try: limit = max(1, min(100, int(q.get("limit") or 30)))
    except ValueError: raise HttpError(400, "limite inválido")
    h.send_json({"hits": LIB.search(q.get("q", "")[:200], summary_visible(u), limit)})

# ───────────────────────── sugestões de alteração ─────────────────────────
# Quem lê (permissão <tipo>.suggest) seleciona um trecho e propõe um texto novo, ou só comenta, ou sugere um acréscimo
# no fim de uma seção. Quem edita aceita (aplicando no documento, o que gera uma versão) ou recusa. O trecho é procurado
# no texto da seção mesmo com formatação no meio (negrito, código, links): a seleção na tela vem sem os marcadores.

SUGG_GEN = [0]
MAX_QUOTE, MAX_PROPOSAL, MAX_COMMENT = 2000, 4000, 2000

def _plain_map(raw):
    """Texto sem marcadores de Markdown inline + posição de cada caractere no original."""
    out, idx, i = [], [], 0
    while i < len(raw):
        m = core.LINK_RE.match(raw, i)
        if m:
            for k in range(len(m.group(1))): out.append(m.group(1)[k]); idx.append(m.start(1) + k)
            i = m.end(); continue
        if raw.startswith("**", i): i += 2; continue
        if raw[i] in "*`": i += 1; continue
        out.append(" " if raw[i] == "\n" else raw[i]); idx.append(i); i += 1
    return "".join(out), idx

def _text_slots(blocks):
    """(get, set) de cada texto editável dos blocos: parágrafos, destaques, itens, células, código e legendas."""
    for b in blocks:
        t = b.get("t")
        if t in ("p", "quote", "code"):
            yield (lambda b=b: b.get("text", ""), lambda v, b=b: b.__setitem__("text", v), t == "code")
        elif t in ("ul", "ol"):
            for i in range(len(b.get("items", []))):
                yield (lambda b=b, i=i: b["items"][i], lambda v, b=b, i=i: b["items"].__setitem__(i, v.replace("\n", " ")), False)
        elif t == "table":
            for i in range(len(b.get("head", []))):
                yield (lambda b=b, i=i: b["head"][i], lambda v, b=b, i=i: b["head"].__setitem__(i, v.replace("\n", " ")), False)
            for r in b.get("rows", []):
                for i in range(len(r)):
                    yield (lambda r=r, i=i: r[i], lambda v, r=r, i=i: r.__setitem__(i, v.replace("\n", " ")), False)
        elif t == "img":
            yield (lambda b=b: b.get("alt", ""), lambda v, b=b: b.__setitem__("alt", v.replace("\n", " ")), False)

def suggestion_scope(doc, anchor):
    """Blocos onde a sugestão vale: a seção (com as subseções), a introdução ("intro") ou o documento todo ("")."""
    if anchor == "intro": return [doc.setdefault("intro", [])], None
    secs = doc.get("sections", [])
    if anchor:
        for sec in secs:
            if core.slug(sec["title"]) == anchor: return [sec["blocks"]] + [x["blocks"] for x in sec.get("subs", [])], sec
        raise HttpError(409, "A seção desta sugestão não existe mais no documento. Aplique manualmente ou marque como aceita.")
    return [doc.get("intro") or []] + [bl for sec in secs for bl in [sec["blocks"]] + [x["blocks"] for x in sec.get("subs", [])]], None

def apply_suggestion(doc, s):
    """Aplica a proposta no doc (altera no lugar). Sem trecho, acrescenta a proposta no fim da seção."""
    scopes, sec = suggestion_scope(doc, s["anchor"])
    if not s["quote"]:
        if sec is None and s["anchor"] != "intro": raise HttpError(400, "Sugestão sem trecho precisa de uma seção")
        target = scopes[0]
        target.extend(core.parse_blocks(s["proposal"].replace("\r\n", "\n").split("\n")))
        return
    quote = " ".join(s["quote"].split())
    hits = []
    for bl in scopes:
        for get, put, literal in _text_slots(bl):
            raw = get()
            if literal:                                      # código: comparação direta, sem tirar marcadores
                plain, idx = raw.replace("\n", " "), list(range(len(raw)))
            else:
                plain, idx = _plain_map(raw)
            plain = re.sub(r"\s", " ", plain)
            start = plain.find(quote)
            while start >= 0:
                hits.append((get, put, idx[start], idx[start + len(quote) - 1] + 1))
                start = plain.find(quote, start + 1)
    if not hits: raise HttpError(409, "O trecho sugerido não foi encontrado: o texto mudou depois da sugestão. Aplique manualmente ou marque como aceita.")
    if len(hits) > 1: raise HttpError(409, f"O trecho aparece {len(hits)} vezes na seção: aplique manualmente ou marque como aceita.")
    get, put, a, z = hits[0]
    raw = get()
    put(raw[:a] + s["proposal"] + raw[z:])

def public_suggestion(x, u):
    out = {k: x[k] for k in ("id", "anchor", "anchor_title", "quote", "proposal", "comment", "status", "author_name", "created_at",
                             "base_version", "resolved_name", "resolved_at", "resolution_note")}
    out.update(applied=bool(x["applied"]), mine=x["author"] == u["login"])
    return out

def r_suggestions(h, pid, **_):
    u = h.require(doc_perm(pid, "view"))
    pb = load_pb(get_folder(pid))
    if not visible(pb, u): raise HttpError(404, not_found_msg(pid))
    xs = open_db().suggestions(pid, only_open=h.query().get("status") != "todas")
    h.send_json({"suggestions": [public_suggestion(x, u) for x in xs], "canResolve": can(u, doc_perm(pid, "edit")),
                 "canSuggest": can(u, doc_perm(pid, "suggest"))})

def r_suggestion_create(h, pid, **_):
    u = h.require(doc_perm(pid, "suggest")); b = h.body()
    pb = load_pb(get_folder(pid))
    if not visible(pb, u): raise HttpError(404, not_found_msg(pid))
    quote, proposal = str(b.get("quote") or "").strip(), b.get("proposal")
    proposal = None if proposal is None or not str(proposal).strip() else str(proposal).strip()
    comment, anchor = str(b.get("comment") or "").strip(), str(b.get("anchor") or "")
    if len(quote) > MAX_QUOTE or (proposal and len(proposal) > MAX_PROPOSAL) or len(comment) > MAX_COMMENT:
        raise HttpError(400, "Sugestão longa demais (trecho até 2.000 caracteres, texto novo até 4.000, comentário até 2.000)")
    if not proposal and not comment: raise HttpError(400, "Escreva o texto sugerido ou um comentário")
    if proposal and not quote and not anchor: raise HttpError(400, "Para acrescentar texto, indique a seção")
    titles = {"intro": "Introdução", "": "Documento todo"}
    titles.update({core.slug(s["title"]): s["title"] for s in pb["doc"]["sections"]})
    if anchor not in titles: raise HttpError(400, "Seção inválida")
    sub_title = str(b.get("anchor_title") or "")[:200]
    sid = open_db().add_suggestion(pid, anchor, sub_title if sub_title else titles[anchor], quote, proposal, comment, u["login"], u["name"],
                                   core.fmt_version(core.get_version(pb["doc"])))
    SUGG_GEN[0] += 1
    audit(u["login"], "sugestao_criada", pid, sugestao=sid, secao=titles[anchor], tem_texto="sim" if proposal else "não")
    h.send_json({"suggestion": public_suggestion(open_db().suggestion(pid, sid), u)})

def suggestion_id(h, pid):
    m = re.search(r"/suggestions/(\d+)", h.path)
    x = open_db().suggestion(pid, int(m.group(1))) if m else None
    if not x: raise HttpError(404, "sugestão não encontrada")
    if x["status"] != "aberta": raise HttpError(409, "Esta sugestão já foi resolvida")
    return x

def r_suggestion_accept(h, pid, **_):
    """Aceita: com "apply" e texto sugerido, aplica no documento (nova versão, tipo "sugestao"); sem, só marca."""
    u = h.require(doc_perm(pid, "edit")); b = h.body()
    folder = get_folder(pid)
    x = suggestion_id(h, pid)
    applied, ver, note = False, None, str(b.get("note") or "").strip()[:500]
    if b.get("apply"):
        if not x["proposal"]: raise HttpError(400, "Esta sugestão é só um comentário: marque como aceita")
        with LOCK:
            check_rev(folder, b.get("rev"))
            old = core.parse_md(core.files_of(folder)[0].read_text("utf-8"))
            change = prod_change(b, old)
            doc = core.clone_doc(old)
            apply_suggestion(doc, x)
            ver, _ = save_doc(folder, pid, u, doc, old, change, kind="sugestao", note=f"Sugestão #{x['id']} de {x['author_name']}")
            open_db().resolve_suggestion(x["id"], "aceita", u["login"], u["name"], note, applied=True)
        applied = True
    else:
        open_db().resolve_suggestion(x["id"], "aceita", u["login"], u["name"], note)
    SUGG_GEN[0] += 1
    audit(u["login"], "sugestao_aceita", pid, sugestao=x["id"], autor=x["author"], aplicada="sim" if applied else "não", **({"versao": ver} if ver else {}))
    h.send_json({"ok": True, "applied": applied, "version": ver, "playbook": load_pb(folder)})

def r_suggestion_reject(h, pid, **_):
    u = h.require(doc_perm(pid, "edit")); b = h.body()
    x = suggestion_id(h, pid)
    open_db().resolve_suggestion(x["id"], "recusada", u["login"], u["name"], str(b.get("note") or "").strip()[:500])
    SUGG_GEN[0] += 1
    audit(u["login"], "sugestao_recusada", pid, sugestao=x["id"], autor=x["author"])
    h.send_json({"ok": True})

def r_suggestion_withdraw(h, pid, **_):
    u = h.require(doc_perm(pid, "view"))
    x = suggestion_id(h, pid)
    if x["author"] != u["login"]: raise HttpError(403, "Só quem sugeriu pode retirar a sugestão")
    open_db().resolve_suggestion(x["id"], "retirada", u["login"], u["name"])
    SUGG_GEN[0] += 1
    audit(u["login"], "sugestao_retirada", pid, sugestao=x["id"])
    h.send_json({"ok": True})

# ───────────────────────── citações e verificação (lint) ─────────────────────────

def r_doc_links(h, pid, **_):
    """Quem este documento cita e quem cita ele (painel "Referenciado por")."""
    u = h.require(doc_perm(pid, "view"))
    pb = load_pb(get_folder(pid))
    if not visible(pb, u): raise HttpError(404, not_found_msg(pid))
    h.send_json(LIB.citations(pid, summary_visible(u)))

def lint(pb):
    """Pendências de um documento: referências a documentos inexistentes e, nos playbooks, caixas sem "ao clicar",
    passos sem caixa, IDs de passo repetidos e ramos só no documento ou só no fluxograma."""
    issues = []
    existing = set(LIB.pids())
    e = LIB.entry(pb["id"])
    for x in (e.links if e else ()):
        if x not in existing: issues.append({"kind": "ref", "ref": x, "message": f"Cita {x}, que não existe"})
    if pb.get("type", "playbook") != "playbook": return issues
    flow, refs = pb["flow"], pb["refs"]
    step_ids = [s["id"] for s in pb["steps"]]
    for sid in sorted({x for x in step_ids if step_ids.count(x) > 1}):
        issues.append({"kind": "step-dup", "ref": sid, "message": f"O passo {sid} aparece mais de uma vez"})
    linked = {r for v in refs.values() for r in v}
    for n in flow["nodes"]:
        label = " / ".join(l["t"] for l in n.get("lines", []))
        if n["type"] in ("support", "start") or MENTION_FALLBACK.search(label): continue
        if not refs.get(n["id"]):
            issues.append({"kind": "node-norefs", "ref": n["id"], "message": f"Caixa sem \"ao clicar\": {label[:80]}"})
    for sid in dict.fromkeys(step_ids):
        if sid not in linked: issues.append({"kind": "step-nonode", "ref": sid, "message": f"O passo {sid} não está em nenhuma caixa do fluxograma"})
    dr, fr = ramos.doc_ramos(pb["doc"]), ramos.flow_ramos(flow, refs)
    for k in sorted(set(dr) - set(fr), key=ramos.sort_key):
        issues.append({"kind": "ramo-nobox", "ref": f"R{k}", "message": f"O ramo R{k} não tem caixa no fluxograma"})
    for k in sorted(set(fr) - set(dr), key=ramos.sort_key):
        issues.append({"kind": "ramo-nosub", "ref": f"R{k}", "message": f"O ramo R{k} não tem subseção no documento"})
    return issues

MENTION_FALLBACK = re.compile(r"(?<![\w-])(?:PB|RB|DOC)-\d{2,4}(?!\w)")

def r_doc_lint(h, pid, **_):
    u = h.require(doc_perm(pid, "edit"))
    pb = load_pb(get_folder(pid))
    issues = lint(pb)
    h.send_json({"issues": issues, "count": len(issues)}, etag=doc_etag(pb, u).rstrip('"') + f"-lint{BOOT_ID}{LIB.generation}" + '"')

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

def bump(doc, old_doc, publish=False, change=None):
    v = core.next_version(core.get_version(old_doc), core.get_gov(old_doc)["status"], publish, change and change["type"])
    core.set_version(doc, v)
    return core.fmt_version(v)

CHANGE_TYPES = {"major": "Major", "minor": "Minor"}

def prod_change(b, old_doc):
    """Playbook em Produção: a gravação precisa dizer o tipo da atualização (major/minor) e descrever o que mudou.
    Fora de Produção não pede nada (a versão segue 0.1 → 0.2). Retorna None ou {"type", "note"}."""
    if core.get_gov(old_doc)["status"] != "Produção": return None
    c = b.get("change") if isinstance(b.get("change"), dict) else {}
    t, note = str(c.get("type", "")).lower(), " ".join(str(c.get("note", "")).split())[:500]
    if t not in CHANGE_TYPES: raise HttpError(400, "Playbook em Produção: escolha o tipo da atualização (Major ou Minor)")
    if len(note) < 5: raise HttpError(400, "Playbook em Produção: descreva as alterações realizadas")
    return {"type": t, "note": note}

def change_note(change, extra=""):
    parts = ([f"{CHANGE_TYPES[change['type']]}: {change['note']}"] if change else []) + ([extra] if extra else [])
    return " · ".join(parts)

def change_audit(change):
    return {"tipo_atualizacao": CHANGE_TYPES[change["type"]], "descricao": change["note"]} if change else {}

def r_pb_doc(h, pid, **_):
    u = h.require(doc_perm(pid, "edit"))
    folder = get_folder(pid); b = h.body()
    doc = b.get("doc")
    if not isinstance(doc, dict) or not str(doc.get("title", "")).strip() or not isinstance(doc.get("sections"), list):
        raise HttpError(400, "documento inválido")
    with LOCK:
        check_rev(folder, b.get("rev"))
        old = core.parse_md(core.files_of(folder)[0].read_text("utf-8"))
        change = prod_change(b, old)
        ver, changes = save_doc(folder, pid, u, doc, old, change)
    audit(u["login"], "documento_salvo", pid, versao=ver, **change_audit(change), **({"ramos": "; ".join(changes)} if changes else {}))
    h.send_json({"ok": True, "playbook": load_pb(folder), "sync": changes, "version": ver})

def save_doc(folder, pid, u, doc, old, change, kind="documento", note=""):
    """Grava o documento (dentro do LOCK, revisão já conferida): revisor, versão, ramos sincronizados com o fluxograma,
    backup, escrita atômica e versão no histórico. Devolve (versão, mudanças nos ramos)."""
    ensure_baseline(folder, pid)
    md, dio = core.files_of(folder)
    touch_review(doc, u, old)
    doc = core.parse_md(core.doc_to_md(doc))          # mesma forma que será lida de volta
    ver = bump(doc, old, change=change)
    view = load_pb_fresh(folder)
    flow, refs = view["flow"], view["refs"]
    changes = ramos.sync_from_doc(flow, refs, old, doc) if type_info(pid)["ramos"] and view["hasFlow"] else []
    backup(pid, md, *( (dio, core.MAPPINGS_FILE) if changes else ()))
    core.atomic_write(md, core.doc_to_md(doc))
    if changes: write_flow(folder, pid, view["name"], flow, refs)
    snapshot(folder, pid, u, kind, change_note(change, "; ".join(x for x in [note] + changes if x)))
    LIB.invalidate(pid)
    return ver, changes

def write_flow(folder, pid, name, flow, refs):
    _, dio = core.files_of(folder)
    target = dio or folder / f"{pid.lower()}-{core.slug(name)}.drawio"
    core.atomic_write(target, core.flow_to_drawio(flow, pid, name, dio))
    ids = {n["id"] for n in flow["nodes"]}
    save_refs(pid, {k: [str(x) for x in v] for k, v in refs.items() if k in ids and isinstance(v, list) and v})

def r_pb_flow(h, pid, **_):
    u = h.require(doc_perm(pid, "edit"))
    folder = get_folder(pid); b = h.body()
    if type_info(pid)["flow"] == "none": raise HttpError(400, f"{type_info(pid)['plural']} não têm fluxograma")
    flow, refs = b.get("flow") or {}, b.get("refs") or {}
    validate_flow(flow)
    refs = {k: [str(x) for x in v] for k, v in refs.items() if isinstance(v, list)}
    with LOCK:
        check_rev(folder, b.get("rev"))
        ensure_baseline(folder, pid)
        md, dio = core.files_of(folder)
        view = load_pb_fresh(folder)
        backup(pid, dio, md, core.MAPPINGS_FILE)
        doc = core.parse_md(md.read_text("utf-8")); old = core.clone_doc(doc)
        change = prod_change(b, old)
        changes = ramos.sync_from_flow(doc, view["flow"], view["refs"], flow, refs) if type_info(pid)["ramos"] else []
        write_flow(folder, pid, view["name"], flow, refs)
        touch_review(doc, u, doc); ver = bump(doc, old, change=change)
        core.atomic_write(md, core.doc_to_md(doc))
        new_teams = add_template_teams(view["templateKey"], sorted(tpl.used_teams(flow) - set(view["teams"])))
        snapshot(folder, pid, u, "fluxograma", change_note(change, "; ".join(changes)))
        LIB.invalidate(pid)
    audit(u["login"], "fluxograma_salvo", pid, versao=ver, **change_audit(change), **({"ramos": "; ".join(changes)} if changes else {}),
          **({"times_no_template": ", ".join(new_teams)} if new_teams else {}))
    h.send_json({"ok": True, "playbook": load_pb(folder), "sync": changes, "version": ver})

def r_pb_ramo_add(h, pid, **_):
    u = h.require(doc_perm(pid, "edit"))
    folder = get_folder(pid); b = h.body()
    if not type_info(pid)["ramos"]: raise HttpError(400, f"{type_info(pid)['plural']} não têm ramos")
    name, q = str(b.get("name", "")).strip()[:80], str(b.get("q", "")).strip()[:200]
    if not name: raise HttpError(400, "Informe o nome do ramo")
    with LOCK:
        check_rev(folder, b.get("rev"))
        ensure_baseline(folder, pid)
        md, dio = core.files_of(folder)
        view = load_pb_fresh(folder)
        doc, flow, refs = core.parse_md(md.read_text("utf-8")), view["flow"], view["refs"]
        old = core.clone_doc(doc)
        change = prod_change(b, old)
        k = ramos.next_key(doc, flow, refs)
        backup(pid, md, dio, core.MAPPINGS_FILE)
        ramos.add(doc, flow, refs, k, name, q)
        write_flow(folder, pid, view["name"], flow, refs)
        touch_review(doc, u, doc); ver = bump(doc, old, change=change)
        core.atomic_write(md, core.doc_to_md(doc))
        snapshot(folder, pid, u, "ramo", change_note(change, f"R{k} {name} criado"))
        LIB.invalidate(pid)
    audit(u["login"], "ramo_criado", pid, ramo=f"R{k} {name}", versao=ver)
    h.send_json({"ok": True, "playbook": load_pb(folder), "ramo": f"R{k}"})

def r_pb_ramo_delete(h, pid, **_):
    u = h.require(doc_perm(pid, "edit"))
    folder = get_folder(pid); b = h.body()
    if not type_info(pid)["ramos"]: raise HttpError(400, f"{type_info(pid)['plural']} não têm ramos")
    k = ramos.ref_key(h.path.split("?")[0].rsplit("/", 1)[-1])
    if not k or k == ramos.PROTO: raise HttpError(404, "ramo não encontrado")
    with LOCK:
        check_rev(folder, b.get("rev"))
        md, dio = core.files_of(folder)
        view = load_pb_fresh(folder)
        doc, flow, refs = core.parse_md(md.read_text("utf-8")), view["flow"], view["refs"]
        if k not in ramos.doc_ramos(doc) and k not in ramos.flow_ramos(flow, refs): raise HttpError(404, "ramo não encontrado")
        ensure_baseline(folder, pid)
        old = core.clone_doc(doc)
        change = prod_change(b, old)
        backup(pid, md, dio, core.MAPPINGS_FILE)
        ramos.remove(doc, flow, refs, k)
        write_flow(folder, pid, view["name"], flow, refs)
        touch_review(doc, u, doc); ver = bump(doc, old, change=change)
        core.atomic_write(md, core.doc_to_md(doc))
        snapshot(folder, pid, u, "ramo", change_note(change, f"R{k} excluído"))
        LIB.invalidate(pid)
    audit(u["login"], "ramo_excluido", pid, ramo=f"R{k}", versao=ver)
    h.send_json({"ok": True, "playbook": load_pb(folder)})

def r_pb_status(h, pid, **_):
    u = h.require(doc_perm(pid, "status"))
    folder = get_folder(pid); b = h.body()
    status = b.get("status")
    if status not in core.STATUSES: raise HttpError(400, "status inválido")
    with LOCK:
        check_rev(folder, b.get("rev"))
        md, _ = core.files_of(folder)
        doc = core.parse_md(md.read_text("utf-8")); old = core.clone_doc(doc)
        gov = core.get_gov(doc); before = gov["status"]
        if status == before: raise HttpError(400, f"O documento já está em {status}")
        needs_ap = status == "Produção" and type_info(pid)["approval"]
        if needs_ap:
            ap = check_approver(pid, u, str(b.get("approver", "")))
            gov["approver"] = ap["name"]
        ensure_baseline(folder, pid)
        gov["status"] = status
        core.set_gov(doc, gov)
        ver = bump(doc, old, publish=True) if status == "Produção" else core.fmt_version(core.get_version(doc))
        backup(pid, md)
        core.atomic_write(md, core.doc_to_md(doc))
        LIB.invalidate(pid)
        note = str(b.get("note", ""))[:300]
        snapshot(folder, pid, u, "status", f"{before} → {status}" + (f" · aprovado por {gov['approver']}" if needs_ap else "") + (f" · {note}" if note else ""))
    audit(u["login"], "status_alterado", pid, de=before, para=status, versao=ver, aprovador=gov.get("approver", "") if needs_ap else "",
          aprovador_login=str(b.get("approver", "")) if needs_ap else "", nota=str(b.get("note", ""))[:500])
    h.send_json({"ok": True, "playbook": load_pb(folder)})

# ── aprovação de Produção por outra pessoa (governança)
# O aprovador não pode ser quem promove nem quem gravou a última versão de conteúdo (comparação pelo login, não pelo
# nome do "Último revisor", que não é único). Ligado por padrão; quem tem app.reset ou users.manage pode desligar.

CONTENT_KINDS = ("documento", "fluxograma", "ramo", "restauracao", "importacao", "criacao", "sugestao")

def governance():
    return {"require_distinct_approver": True, **(open_db().get_setting("governance") or {})}

def approval_exclusions(pid, u):
    """{login: motivo} de quem não pode aprovar este documento agora, e o autor da última alteração."""
    if not governance()["require_distinct_approver"]: return {}, None
    last = open_db().last_content_version(pid, CONTENT_KINDS)
    out = {u["login"]: "é quem está publicando"}
    if last: out.setdefault(last["author"], "fez a última alteração")
    return out, last

def check_approver(pid, u, login):
    ap = open_db().get_user(login)
    if not ap or not ap["active"] or not can(ap, doc_perm(pid, "approve")):
        raise HttpError(400, "Escolha um aprovador ativo com permissão de aprovar")
    if governance()["require_distinct_approver"]:
        if ap["login"] == u["login"]:
            raise HttpError(400, "O aprovador precisa ser outra pessoa: quem está publicando não pode aprovar.")
        last = open_db().last_content_version(pid, CONTENT_KINDS)
        if last and last["author"] == ap["login"]:
            raise HttpError(400, f"O aprovador precisa ser diferente de quem fez a última alteração ({last['author_name']}).")
    return ap

def mitre_text(ids):
    by = {t["id"]: t for t in core.MITRE["tactics"]}
    bad = [i for i in ids if i not in by]
    if bad: raise HttpError(400, f"Tática MITRE desconhecida: {', '.join(bad)}")
    return " · ".join(f"{i} {by[i]['name']}" for i in ids)

def used_ids():
    return {pid_of(f) for f in core.all_folders()}

def clean_field_values(schema, raw):
    """Valores dos campos do template: select/multiselect só com opções válidas; obrigatórios preenchidos."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for f in schema:
        v = raw.get(f["key"], [] if f["type"] == "multiselect" else "")
        if f["type"] == "multiselect":
            v = [str(x) for x in (v if isinstance(v, list) else str(v).split(",")) if str(x).strip()]
            bad = [x for x in v if x not in f["options"]]
        else:
            v = " ".join(str(v or "").split())[:300]
            bad = [v] if f["type"] == "select" and v and v not in f["options"] else []
            if f["type"] == "url" and v and not re.match(r"^https?://\S+$", v, re.I): bad = [v]
            if f["type"] == "date" and v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}", v): bad = [v]
        if bad: raise HttpError(400, f"Valor inválido em {f['label']}: {', '.join(bad)[:80]}")
        if f.get("required") and not v: raise HttpError(400, f"Preencha o campo {f['label']}")
        out[f["key"]] = v
    return out

def create_document(h, u, m, dtype):
    """Cria playbook, runbook ou documento a partir de um template do mesmo tipo."""
    ti = DT.info(dtype)
    pid = str(m.get("id") or "").strip().upper() or DT.next_id(dtype, used_ids())
    name = str(m.get("name", "")).strip()[:100]
    if not core.ID_RE.fullmatch(pid) or DT.type_of(pid) != dtype: raise HttpError(400, f"ID deve ter o formato {ti['prefix']}-00")
    if not name: raise HttpError(400, f"informe o nome d{ti['article']} {ti['label'].lower()}")
    author = open_db().get_user(str(m.get("author") or u["login"]))
    if not author or not author["active"]: raise HttpError(400, "Escolha um autor entre os usuários ativos")
    t = tpl.load(str(m.get("template") or tpl.default_key(dtype)))
    if (t.get("kind") or "playbook") != dtype: raise HttpError(400, f"Escolha um template de {ti['label'].lower()}")
    folder_id = m.get("folder_id")
    if folder_id is not None:
        if not ti["folders"]: raise HttpError(400, f"{ti['plural']} não usam pastas")
        f = open_db().folder(int(folder_id)) if str(folder_id).isdigit() else None
        if not f or f["type"] != dtype: raise HttpError(400, "Pasta inválida")
        folder_id = f["id"]
    if dtype == "playbook":
        vars_ = {"id": pid, "name": name, "author": author["name"], "date": today(), "owner": str(m.get("owner", ""))[:80],
                 "nist": str(m.get("nist", ""))[:200], "mitre": mitre_text([str(x) for x in (m.get("mitre") or [])][:20]),
                 "objective": str(m.get("objective", ""))[:3000], "question": str(m.get("question", ""))[:300],
                 "ramos": [r for r in (m.get("ramos") or [])][:20]}
    else:
        vars_ = {"id": pid, "name": name, "author": author["name"], "date": today(), "owner": str(m.get("owner", ""))[:80],
                 "fields": clean_field_values(t.get("fields", []), m.get("fields"))}
    with LOCK:
        if core.folder_of(pid) or pid in used_ids(): raise HttpError(400, f"{pid} já existe")
        doc, flow, refs, tdefs = tpl.instantiate(t, vars_)
        if flow.get("nodes") or dtype == "playbook": validate_flow(flow)
        if dtype != "playbook": core.set_fields(doc, t.get("fields", []), vars_["fields"], ti["props_title"])
        base = f"{pid}-{core.slug(name).title()}"
        folder = DT.src_dir(dtype) / base
        folder.mkdir(parents=True)
        doc = core.set_gov(doc, {"status": "Desenvolvimento", "approver": "", "reviewer": u["name"], "reviewed": today()})
        core.set_version(doc, (0, 1))
        core.atomic_write(folder / f"{base}.md", core.doc_to_md(doc))
        if dtype == "playbook" or flow.get("nodes"):
            core.atomic_write(folder / f"{pid.lower()}-{core.slug(name)}.drawio", core.flow_to_drawio(flow, pid, name))
            save_refs(pid, refs)
        set_link(pid, t["key"])
        if folder_id is not None: open_db().set_doc_folder(pid, dtype, folder_id); FOLDER_GEN[0] += 1
        snapshot(folder, pid, u, "criacao", f"Criado com o template {t['name']}")
        LIB.invalidate(pid)
    audit(u["login"], "playbook_criado" if dtype == "playbook" else "documento_criado", pid, tipo=dtype, nome=name, template=t["name"],
          autor=author["login"], **({"pasta": open_db().folder_path(folder_id)} if folder_id else {}))
    h.send_json({"ok": True, "playbook": load_pb(folder), "teams": core.load_teams()})

def r_pb_create(h, **_):
    u = h.require("playbook.create")
    m = h.body()
    if not str(m.get("id", "")).strip(): raise HttpError(400, "ID deve ter o formato PB-00")
    create_document(h, u, m, "playbook")

def r_doc_create(h, **_):
    """POST /api/doc {type, name, template, folder_id, fields, id?}: cria qualquer tipo (ID livre sugerido se faltar)."""
    m = h.body()
    dtype = str(m.get("type") or "")
    if dtype not in DT.TYPES: raise HttpError(400, "tipo de documento inválido")
    u = h.require(f"{dtype}.create")
    create_document(h, u, m, dtype)

def r_doc_next_id(h, **_):
    h.require(any_of=any_type("create"))
    dtype = h.query().get("type") or ""
    if dtype not in DT.TYPES: raise HttpError(400, "tipo de documento inválido")
    h.send_json({"id": DT.next_id(dtype, used_ids())})

FOLDER_GEN = [0]       # muda quando pastas ou a pasta de um documento mudam (entra no ETag da lista)
BOOT_ID = secrets.token_hex(4)   # contadores recomeçam a cada boot: o ETag leva este id para não casar com respostas antigas

def r_pb_delete(h, pid, **_):
    u = h.require(doc_perm(pid, "delete"))
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
        open_db().archive_suggestions(pid, dest.name); SUGG_GEN[0] += 1
        open_db().drop_doc_meta(pid); FOLDER_GEN[0] += 1
        LIB.invalidate(pid)
    audit(u["login"], "playbook_excluido" if doc_type(pid) == "playbook" else "documento_excluido", pid, lixeira=dest.name)
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
    u = h.require(doc_perm(pid, "edit"))
    folder = get_folder(pid)
    ext, data = decode_image(h.body().get("dataUrl"))
    with LOCK: name = store_image(folder, ext, data)
    audit(u["login"], "imagem_enviada", pid, arquivo=name, tamanho_kb=round(len(data) / 1024))
    h.send_json({"ok": True, "src": f"{core.IMG_DIR}/{name}", "url": f"api/pb/{pid}/img/{name}"})

def r_pb_img_get(h, pid, **_):
    u = h.require(doc_perm(pid, "view"))
    folder = get_folder(pid)
    name = h.path.split("?")[0].rsplit("/", 1)[-1]
    f = folder / core.IMG_DIR / name
    if not core.IMG_NAME_RE.fullmatch(name) or not f.is_file(): raise HttpError(404, "imagem não encontrada")
    if not can(u, doc_perm(pid, "view_drafts")):
        md, _ = core.files_of(folder)
        if core.get_gov(core.parse_md(md.read_text("utf-8")))["status"] not in VIEWER_STATUSES: raise HttpError(404, "imagem não encontrada")
    h.send_bytes(f.read_bytes(), IMG_MIME[name.rsplit(".", 1)[1]], sandbox=True)

def team_usage(tkey):
    """Onde cada time do template aparece: no fluxograma modelo e nos playbooks que usam o template."""
    use, lk = {}, links()
    t = tpl.load(tkey)
    for n in tpl.used_teams(t["flow"]): use.setdefault(n, set()).add("fluxograma do template")
    for pid in LIB.pids():
        if template_of(pid, lk) != tkey: continue
        v = LIB.view(pid)
        if not v or not v["flow"]["nodes"]: continue
        for n in tpl.used_teams(v["flow"]): use.setdefault(n, set()).add(pid)
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
    u = h.require(doc_perm(pid, "export"))
    folder = get_folder(pid)
    view = load_pb(folder)
    if not visible(view, u): raise HttpError(404, "playbook não encontrado")
    fmt = h.query().get("fmt", "medusa")
    if fmt not in EXPORT_FMTS: raise HttpError(400, "formato inválido")
    if fmt in ("drawio", "mmd") and not view.get("hasFlow", True): raise HttpError(400, "Este documento não tem fluxograma")
    base = view["folder"].lower()
    if fmt == "medusa":
        data, ctype, fname = (bundle.export(view, {**core.load_teams(), **view["teams"]}, u["name"], brand()["name"], pb_images(folder, view["doc"]),
                                            doc_folder_path(pid)).encode(),
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
    buf, union, name = io.BytesIO(), core.load_teams(), brand()["name"]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for pid in LIB.pids():
            if not can(u, doc_perm(pid, "export")): continue
            v, f = LIB.view(pid), core.folder_of(pid)
            if not v or not f or not visible(v, u): continue
            z.writestr(f"{DT.info(doc_type(pid))['dir']}/{f.name.lower()}.medusa.md",
                       bundle.export(v, {**union, **v["teams"]}, u["name"], name, pb_images(f, v["doc"]), doc_folder_path(pid)))
    audit(u["login"], "playbooks_exportados")
    h.send_bytes(buf.getvalue(), "application/zip", f"medusa-{date.today().isoformat()}.zip")

def doc_folder_path(pid):
    fid = open_db().doc_folders().get(pid)
    return open_db().folder_path(fid) if fid else ""

def r_import(h, **_):
    u = h.require(any_of=any_type("create")); b = h.body()
    text = str(b.get("text", ""))
    # tipo: pelo ID pedido, pelo "type" do cabeçalho do arquivo ou pelo prefixo do ID do arquivo
    fm = dict(re.findall(r"^(type|id):\s*(\S+)\s*$", text.split("\n---", 1)[0], re.M)) if text.startswith("---") else {}
    ftype = (fm.get("type") if fm.get("type") in DT.TYPES else None) or DT.type_of(fm.get("id", ""))
    dtype = DT.type_of(str(b.get("id") or "")) or ftype or "playbook"
    if ftype and dtype != ftype:
        raise HttpError(400, f"O arquivo é de {DT.info(ftype)['label'].lower()}: use um ID {DT.info(ftype)['prefix']}-00")
    tkey = str(b.get("template") or tpl.default_key(dtype))
    if not tpl.KEY_RE.fullmatch(tkey) or not tpl.path_of(tkey).exists(): raise HttpError(400, "Escolha um template existente")
    if tpl.kind_for(tkey) != dtype: raise HttpError(400, f"Escolha um template de {DT.info(dtype)['label'].lower()}")
    union, teams = core.load_teams(), template_teams(tkey)
    try:
        p = bundle.parse(text, teams, dtype)
    except bundle.BundleError as e:
        raise HttpError(400, str(e))
    for n in p["createTeams"]:      # time que já existe em outro template: leva a definição de lá
        if n not in p["teamDefs"] and n in union: p["createTeams"][n] = {**union[n], "category": p["createTeams"][n]["category"]}
    pid = str(b.get("id") or p["id"]).strip().upper()
    if not core.ID_RE.fullmatch(pid) or DT.type_of(pid) != dtype: raise HttpError(400, f"Defina um ID no formato {DT.info(dtype)['prefix']}-00")
    for need in (doc_perm(pid, "create"), doc_perm(pid, "import")):
        if not can(u, need): raise HttpError(403, "Seu perfil não tem permissão para esta ação")
    existing = core.folder_of(pid)
    summary = {"id": pid, "originalId": p["id"], "name": p["name"], "exists": bool(existing),
               "sections": len(p["doc"]["sections"]), "nodes": len(p["flow"]["nodes"]), "edges": len(p["flow"]["edges"]),
               "lanes": [l["label"] for l in p["flow"]["lanes"]], "createTeams": sorted(p["createTeams"]),
               "warnings": p["warnings"], "origin": p["meta"], "template": tpl.load(tkey)["name"], "type": dtype,
               "folder": str(p["meta"].get("folder") or "")[:400]}
    if summary["folder"] and DT.info(dtype)["folders"] and not can(u, f"{dtype}.folders"):
        p["warnings"].append(f"Sem permissão para criar pastas: o documento fica em \"Sem pasta\" (no arquivo: {summary['folder']})")
    images = {}
    for n, durl in p["images"].items():
        if not core.IMG_NAME_RE.fullmatch(n): p["warnings"].append(f"Imagem com nome inválido ignorada: {n[:60]}"); continue
        try: images[n] = decode_image(durl, f"Imagem {n}")[1]
        except HttpError as e: p["warnings"].append(e.msg + " (ignorada)")
    missing = sorted(core.images_of(p["doc"]) - set(images))
    if missing: p["warnings"].append(f"{len(missing)} imagem(ns) citada(s) no documento não vieram no arquivo: {', '.join(missing[:5])}")
    summary["images"] = len(images)
    if b.get("dryRun"): return h.send_json({"preview": summary})
    if existing and b.get("mode") == "replace" and not can(u, doc_perm(pid, "delete")):
        raise HttpError(403, "Substituir um documento existente equivale a excluí-lo: exige a permissão de excluir. Importe com outro ID.")
    if existing and b.get("mode") != "replace":
        raise HttpError(409, f"{pid} já existe. Escolha substituir ou importe com outro ID.")
    has_flow = dtype == "playbook" or bool(p["flow"]["nodes"])
    if has_flow: validate_flow(p["flow"])
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
            open_db().archive_suggestions(pid, dest.name); SUGG_GEN[0] += 1
        if p["createTeams"]: add_template_teams(tkey, p["createTeams"], union)
        name = p["name"][:100]
        base = f"{pid}-{core.slug(name).title()}"
        folder = DT.src_dir(dtype) / base
        folder.mkdir(parents=True)
        core.atomic_write(folder / f"{base}.md", core.doc_to_md(doc))
        if has_flow: core.atomic_write(folder / f"{pid.lower()}-{core.slug(name)}.drawio", core.flow_to_drawio(p["flow"], pid, name))
        for n, data in images.items():
            (folder / core.IMG_DIR).mkdir(exist_ok=True); (folder / core.IMG_DIR / n).write_bytes(data)
        save_refs(pid, p["refs"] if has_flow else None)
        set_link(pid, tkey)
        open_db().drop_doc_meta(pid)
        if summary["folder"] and DT.info(dtype)["folders"] and can(u, f"{dtype}.folders"):
            open_db().set_doc_folder(pid, dtype, open_db().ensure_path(dtype, summary["folder"]))
        FOLDER_GEN[0] += 1
        LIB.invalidate(pid)
        snapshot(folder, pid, u, "importacao", f"Importado de {p['meta'].get('gerado_por') or 'arquivo'}" + (f" ({p['id']})" if p["id"] and p["id"] != pid else ""))
    audit(u["login"], "playbook_importado" if dtype == "playbook" else "documento_importado", pid, tipo=dtype,
          origem=p["meta"].get("gerado_por", ""), id_original=p["id"], template=tkey,
          substituiu="sim" if existing else "", times_no_template=", ".join(sorted(p["createTeams"])))
    h.send_json({"ok": True, "playbook": load_pb(folder), "teams": core.load_teams(), "summary": summary})

MAX_MD = 2 * 1024 * 1024

def r_md(h, **_):
    """Modo Markdown do editor: {doc} → {md}; {md, pid?} → {doc, sections} (prévia renderizada como na leitura).
    Usa o mesmo parser que lê os arquivos .md, então a prévia é o que será gravado."""
    h.require(any_of=any_type("edit")); b = h.body()
    if "doc" in b:
        doc = b.get("doc")
        if not isinstance(doc, dict) or not isinstance(doc.get("sections"), list): raise HttpError(400, "documento inválido")
        return h.send_json({"md": core.doc_to_md({"title": str(doc.get("title", "")), "byline": str(doc.get("byline", "")),
                                                  "intro": doc.get("intro") if isinstance(doc.get("intro"), list) else [], "sections": doc["sections"]})})
    text = str(b.get("md", ""))
    if len(text.encode("utf-8")) > MAX_MD: raise HttpError(400, "Documento grande demais (máx. 2 MB)")
    text = text.replace("\r\n", "\n").lstrip("\ufeff")
    if not re.match(r"^\s*#\s+\S", text): raise HttpError(400, "A primeira linha precisa ser o título: # PB-00 — Nome")
    doc = core.parse_md(text.lstrip())
    if not doc["title"].strip(): raise HttpError(400, "O título não pode ficar vazio")
    if not doc["sections"]: raise HttpError(400, "O documento precisa de pelo menos uma seção (## Título da seção)")
    pid = str(b.get("pid") or "")
    img = f"api/pb/{pid}/img/" if core.ID_RE.fullmatch(pid) else None
    render = lambda bl: core.render_blocks(bl, img)
    h.send_json({"doc": doc, "intro": render(doc.get("intro") or []), "sections": [{"title": s["title"], "html": render(s["blocks"]),
                                            "subs": [{"title": x["title"], "html": render(x["blocks"])} for x in s["subs"]]} for s in doc["sections"]]})

def r_flow_parse(h, **_):
    h.require(any_of=any_type("edit")); b = h.body()
    try:
        flow, refs, warns = flowdsl.parse(str(b.get("text", ""))[:300_000], core.load_teams())
    except flowdsl.FlowSyntaxError as e:
        raise HttpError(400, str(e))
    validate_flow(flow)
    h.send_json({"flow": flow, "refs": refs, "warnings": warns})

def r_flow_render(h, **_):
    h.require(any_of=any_type("edit")); b = h.body()
    flow = b.get("flow") or {}
    validate_flow(flow)
    h.send_json({"text": flowdsl.render(flow, b.get("refs") or {}, positions=b.get("positions", True))})

# ───────────────────────── rotas: marca ─────────────────────────

def r_brand_get(h, **_):
    logo = open_db().get_setting("logo")
    h.send_json({**brand(), "logo": logo["v"] if logo else None, "appVersion": APP_VERSION})

def r_brand_put(h, **_):
    u = h.require("branding.edit"); b = h.body()
    cur = brand()
    name = str(b.get("name", cur["name"])).strip()[:40] or DEFAULT_BRAND["name"]
    color = str(b.get("color", cur["color"])).strip().upper() or DEFAULT_BRAND["color"]
    if not HEX_RE.fullmatch(color): raise HttpError(400, "Cor inválida: use #RRGGBB")
    title = " ".join(str(b.get("homeTitle") or cur["homeTitle"]).split())[:120] or DEFAULT_BRAND["homeTitle"]
    sub = " ".join(str(b.get("homeSubtitle", cur["homeSubtitle"]) or "").split())[:600]
    if b.get("homeReset"): title, sub = DEFAULT_BRAND["homeTitle"], DEFAULT_BRAND["homeSubtitle"]
    contact = " ".join(str(b.get("contact", cur["contact"]) or "").split())[:120]   # mostrado no login: a quem recorrer quando não dá para entrar
    logo_bg = str(b.get("logoBg", cur["logoBg"]))
    if logo_bg not in LOGO_BGS: raise HttpError(400, "Fundo da logo inválido: use branco ou transparente")
    open_db().set_setting("branding", {"name": name, "color": color, "logoBg": logo_bg, "homeTitle": title, "homeSubtitle": sub, "contact": contact}, by=u["login"])
    audit(u["login"], "marca_alterada", nome=name, cor=color, fundo_logo=logo_bg, titulo_inicio=title, contato=contact)
    r_brand_get(h)

def r_logo_put(h, **_):
    u = h.require("branding.edit"); b = h.body()
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
    u = h.require("branding.edit")
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
    h.require("app.reset")
    db = open_db()
    h.send_json({"playbooks": len(core.all_folders("playbook")), "documents": {t: len(core.all_folders(t)) for t in DT.TYPES},
                 "templates": len(tpl._files()), "users": len(db.list_users()),
                 "versions": db.count_all_versions(), "audit": db.count_audit(), "word": RESET_WORD})

def r_admin_reset(h, **_):
    u = h.require("app.reset"); b = h.body()
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
        for src, name in ((core.SRC, "playbooks"), (DT.src_dir("runbook"), "runbooks"), (DT.src_dir("doc"), "documentos"),
                          (tpl.TPL_DIR, "templates"), (core.MAPPINGS_FILE, "mappings.json"), (BACKUPS, ".backups"),
                          *(((DATA_DIR / "logs", "logs"),) if opts["audit"] else ())):
            if Path(src).exists(): shutil.move(str(src), str(dest / name)); moved.append(name)
        for t in DT.TYPES: DT.src_dir(t).mkdir(parents=True, exist_ok=True)
        tpl.ensure_seed()
        db.reset(u["login"], **opts)
        LIB.invalidate()
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
    h.require(any_of=("templates.view",) + any_type("create"))
    kind = h.query().get("kind") or None
    if kind and kind not in DT.TYPES: raise HttpError(400, "tipo de template inválido")
    h.send_json({"templates": tpl.list_all(core.load_teams(), kind), "variables": tpl.VARIABLES, "variablesDoc": tpl.VARIABLES_DOC,
                 "defaults": tpl.DEFAULT_KEYS})

def r_tpl_get(h, tkey, **_):
    h.require(any_of=("templates.view",) + any_type("create"))
    cat = core.load_teams()
    h.send_json({"template": tpl.view(tpl.load(tkey, cat), cat), "allTeams": cat})

def _tpl_save(h, u, tkey, t, action, sync=None, **detail):
    with LOCK:
        tpl.save(tkey, {**t, "updated_by": u["name"]})
        LIB.invalidate()
    if sync: detail["ramos"] = "; ".join(sync)
    audit(u["login"], action, f"template:{tkey}", **detail)
    cat = core.load_teams()
    h.send_json({"ok": True, "template": tpl.view(tpl.load(tkey, cat), cat), "sync": sync or [], "allTeams": cat})

def _tpl_check(t, rev):
    if not rev: raise HttpError(400, "Informe a revisão do template (recarregue a página e tente de novo)")
    if rev != t["rev"]:
        raise HttpError(409, "Este template foi salvo por outra pessoa depois que você abriu. Recarregue para ver a versão atual.")

def r_tpl_doc(h, tkey, **_):
    u = h.require("templates.edit"); b = h.body()
    doc = b.get("doc")
    if not isinstance(doc, dict) or not str(doc.get("title", "")).strip() or not isinstance(doc.get("sections"), list):
        raise HttpError(400, "documento inválido")
    t = tpl.load(tkey); _tpl_check(t, b.get("rev"))
    old, t["doc"] = t["doc"], core.parse_md(core.doc_to_md(doc))
    changes = ramos.sync_from_doc(t["flow"], t.setdefault("refs", {}), old, t["doc"]) if t.get("kind", "playbook") == "playbook" else []
    _tpl_save(h, u, tkey, t, "template_documento_salvo", sync=changes)

def r_tpl_flow(h, tkey, **_):
    u = h.require("templates.edit"); b = h.body()
    flow, refs = b.get("flow") or {}, b.get("refs") or {}
    t = tpl.load(tkey)
    kind = t.get("kind", "playbook")
    if kind == "doc": raise HttpError(400, "Templates de documento não têm fluxograma")
    _tpl_check(t, b.get("rev"))
    if kind == "runbook" and not flow.get("nodes"):         # "Incluir fluxograma" desmarcado: o template volta a não ter
        flow = {"subtitle": "", "lanes": [], "nodes": [], "edges": []}
    else:
        validate_flow(flow)
    ids = {n["id"] for n in flow["nodes"]}
    refs = {k: [str(x) for x in v] for k, v in refs.items() if k in ids and isinstance(v, list) and v}
    changes = ramos.sync_from_flow(t["doc"], t["flow"], t.get("refs", {}), flow, refs) if kind == "playbook" else []
    t["flow"], t["refs"] = flow, refs
    added = tpl.sync_teams(t, core.load_teams())
    _tpl_save(h, u, tkey, t, "template_fluxograma_salvo", sync=changes, **({"times_adicionados": ", ".join(added)} if added else {}))

def r_tpl_ramos(h, tkey, **_):
    u = h.require("templates.edit"); b = h.body()
    t = tpl.load(tkey); _tpl_check(t, b.get("rev"))
    if t.get("kind", "playbook") != "playbook": raise HttpError(400, "Só templates de playbook têm ramos")
    if tpl.has_ramos(t): raise HttpError(400, "Este template já tem ramos")
    tpl.add_ramos(t)
    _tpl_save(h, u, tkey, t, "template_ramos_adicionados", sync=["ramo-protótipo criado no documento e no fluxograma"])

def r_tpl_meta(h, tkey, **_):
    u = h.require("templates.edit"); b = h.body()
    t = tpl.load(tkey); _tpl_check(t, b.get("rev"))
    name = str(b.get("name", t["name"])).strip()[:60]
    if not name: raise HttpError(400, "informe o nome do template")
    t.update(name=name, description=str(b.get("description", t.get("description", "")))[:300],
             owner=str(b.get("owner", t.get("owner", "")))[:60], nist=str(b.get("nist", t.get("nist", "")))[:200])
    detail = {}
    if "fields" in b and t.get("kind", "playbook") != "playbook":
        old = {f["key"] for f in t.get("fields", [])}
        t["fields"] = tpl.clean_fields(b["fields"])
        new = {f["key"] for f in t["fields"]}
        detail.update(campos_adicionados=", ".join(sorted(new - old)), campos_removidos=", ".join(sorted(old - new)))
    if "folders" in b and t.get("kind", "playbook") != "playbook":
        t["folders"] = tpl.clean_folders(b["folders"])
        detail["pastas"] = len(t["folders"])
    _tpl_save(h, u, tkey, t, "template_alterado", **detail)

def r_tpl_teams(h, tkey, **_):
    """Times e tags do template (lista completa). Não deixa tirar um time em uso no template ou nos playbooks dele."""
    u = h.require("templates.edit"); b = h.body()
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
    u = h.require("templates.edit"); b = h.body()
    name = str(b.get("name", "")).strip()[:60]
    if not name: raise HttpError(400, "informe o nome do template")
    kind = str(b.get("kind") or "playbook")
    if kind not in DT.TYPES: raise HttpError(400, "tipo de template inválido")
    base = tpl.load(b["from"]) if b.get("from") else tpl.blank(name, kind=kind)
    t = {k: v for k, v in base.items() if k not in ("key", "rev")}
    t.update(name=name, description=str(b.get("description", "")).strip()[:300] or (f"Cópia de {base['name']}" if b.get("from") else ""))
    key = tpl.key_for(name)
    _tpl_save(h, u, key, t, "template_criado", base=b.get("from") or "em branco")

def r_tpl_delete(h, tkey, **_):
    u = h.require("templates.delete")
    f = tpl.path_of(tkey)
    if not f.exists(): raise HttpError(404, "template não encontrado")
    if tkey in tpl.DEFAULT_KEYS.values(): raise HttpError(400, "Os templates padrão não podem ser excluídos (são os iniciais de cada tipo)")
    kind = tpl.kind_for(tkey) or "playbook"
    to = tpl.default_key(kind)
    with LOCK:
        # documentos do template excluído passam para o padrão do tipo, que recebe os times e tags que faltarem
        lk, moved = links(), []
        for pid, k in list(lk.items()):
            if k == tkey: lk[pid] = to; moved.append(pid)
        if moved and kind != "doc": add_template_teams(to, tpl.teams_of_file(f))
        open_db().set_setting("pb_templates", lk)
        dest = TRASH / "templates"; dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), str(dest / f"{f.name}__{time.strftime('%Y%m%d-%H%M%S')}"))
        LIB.invalidate()
    audit(u["login"], "template_excluido", f"template:{tkey}", playbooks_movidos_para_padrao=", ".join(moved))
    h.send_json({"ok": True, "moved": moved})

def r_tpl_export(h, tkey, **_):
    u = h.require(any_of=("templates.view",) + any_type("create"))
    f = tpl.path_of(tkey)
    if not f.exists(): raise HttpError(404, "template não encontrado")
    audit(u["login"], "template_exportado", f"template:{tkey}")
    h.send_bytes(f.read_bytes(), "text/markdown; charset=utf-8", f.name)

def r_tpl_import(h, **_):
    u = h.require("templates.edit"); b = h.body()
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
    h.require(any_of=any_type("create"))
    h.send_json({"people": [{"login": x["login"], "name": x["name"], "roleName": x["role_name"]}
                            for x in open_db().list_users() if x["active"]]})

# ───────────────────────── rotas: usuários ─────────────────────────

def r_approvers(h, **_):
    """Candidatos a aprovador (?type=playbook). Com &pid=, aplica a regra do aprovador diferente: quem não pode
    aprovar este documento agora vem marcado com "excluded" (o motivo), para a tela explicar."""
    u = h.require(any_of=any_type("status")); q = h.query()
    t = q.get("type") or "playbook"
    if t not in P.TYPES: raise HttpError(400, "tipo de documento inválido")
    pid = str(q.get("pid") or "").upper()
    excl, last = approval_exclusions(pid, u) if core.ID_RE.fullmatch(pid) else ({}, None)
    out = [{"login": a["login"], "name": a["name"], "roleName": a["role_name"], **({"excluded": excl[a["login"]]} if a["login"] in excl else {})}
           for a in open_db().approvers(f"{t}.approve")]
    h.send_json({"approvers": out, "distinct": governance()["require_distinct_approver"],
                 "lastAuthor": {"login": last["author"], "name": last["author_name"]} if last else None})

def role_choice(u, key):
    """Papel que este usuário pode atribuir: precisa existir e (fora o Administrador) ter só permissões que ele mesmo tem."""
    r = open_db().role(str(key or ""))
    if not r: raise HttpError(400, "role inválida")
    if not is_admin(u) and not r["perms"] <= u["perms"]:
        raise HttpError(403, f"Você não pode atribuir a role {r['name']}: ela tem permissões que a sua role não tem")
    return r["key"]

def check_manageable(u, target):
    """Quem não é Administrador só gerencia usuários cujo papel não tem permissões além das dele."""
    if target and not is_admin(u) and not target["perms"] <= u["perms"]:
        raise HttpError(403, "Você não pode alterar um usuário com mais permissões que você")

def r_users(h, **_):
    h.require("users.manage")
    db = open_db()
    roles = db.list_roles()
    h.send_json({"users": [public_user(x) for x in db.list_users()], "roles": {r["key"]: r["name"] for r in roles},
                 "roleList": [{"key": r["key"], "name": r["name"], "system": r["system"], "priority": r["priority"]} for r in roles]})

def r_user_create(h, **_):
    u = h.require("users.manage"); b = h.body()
    login = str(b.get("login", "")).strip().lower()
    if not LOGIN_RE.fullmatch(login): raise HttpError(400, "Login: 3 a 80 caracteres (letras minúsculas, números, ponto, hífen, sublinhado ou @)")
    role = role_choice(u, b.get("role_id") or b.get("role"))
    name = str(b.get("name", "")).strip()[:80] or login
    if b.get("auth") == "sso":     # pré-cadastro: o usuário entra pelo SSO com este login (e-mail ou usuário do provedor)
        new = open_db().create_user(login, name, role, NO_PASSWORD, must_change=False, auth="sso")
        audit(u["login"], "usuario_criado", login, papel=role, autenticacao="sso")
        return h.send_json({"user": public_user(new), "tempPassword": None})
    pw = temp_password()
    new = open_db().create_user(login, name, role, hash_password(pw), must_change=True)
    audit(u["login"], "usuario_criado", login, papel=role)
    h.send_json({"user": public_user(new), "tempPassword": pw})

def r_user_update(h, login, **_):
    u = h.require("users.manage"); b = h.body()
    new_role = b.get("role_id") or b.get("role")
    if login == u["login"] and (new_role or b.get("active") is False):
        raise HttpError(400, "Você não pode alterar a própria role nem se desativar")
    if login == u["login"] and "auth" in b: raise HttpError(400, "Você não pode alterar a própria forma de autenticação")
    auth = b.get("auth") if b.get("auth") in ("local", "sso") else None
    name = str(b["name"]).strip()[:80] or login if "name" in b else None
    db = open_db()
    before = db.get_user(login)
    check_manageable(u, before)
    role = role_choice(u, new_role) if new_role else None
    rec = db.update_user(login, name=name, role=role, active=b.get("active"), auth=auth)
    pw = None
    if auth == "sso":
        db.set_password(login, NO_PASSWORD, must_change=False)
    elif auth == "local" and before and before.get("auth") == "sso":   # volta a usar senha: gera uma temporária
        pw = temp_password(); db.set_password(login, hash_password(pw), must_change=True)
    audit(u["login"], "usuario_alterado", login, **{k: v for k, v in (("papel", role), ("ativo", b.get("active")), ("autenticacao", auth)) if v is not None})
    h.send_json({"user": public_user(db.get_user(login)), "tempPassword": pw})

def r_user_reset(h, login, **_):
    u = h.require("users.manage"); db = open_db()
    target = db.get_user(login)
    if not target: raise HttpError(404, "usuário não encontrado")
    check_manageable(u, target)
    if target.get("auth") == "sso": raise HttpError(400, "Conta do SSO: a senha é gerenciada pelo provedor")
    pw = temp_password()
    db.set_password(login, hash_password(pw), must_change=True)
    audit(u["login"], "senha_redefinida", login)
    h.send_json({"user": public_user(db.get_user(login)), "tempPassword": pw})

def r_user_logout(h, login, **_):
    u = h.require("users.manage")
    check_manageable(u, open_db().get_user(login))
    n = open_db().delete_user_sessions(login)
    audit(u["login"], "sessoes_encerradas", login, sessoes=n)
    h.send_json({"ok": True, "closed": n})

def r_user_delete(h, login, **_):
    u = h.require("users.manage")
    if login == u["login"]: raise HttpError(400, "Você não pode excluir o próprio usuário")
    check_manageable(u, open_db().get_user(login))
    open_db().delete_user(login)
    audit(u["login"], "usuario_excluido", login)
    h.send_json({"ok": True})

# ───────────────────────── rotas: papéis ─────────────────────────
# Regras: Administrador é imutável e não pode ser excluído; Editor e Visualizador podem ser editados (e voltar ao
# padrão), não excluídos; ninguém além do Administrador concede permissões que não tem nem mexe em papel com
# permissões além das suas; papel em uso só sai realocando os usuários; mudanças valem na próxima requisição.

def role_key_from(path):
    m = re.match(r"^/api/roles/([^/?]+)", path)
    return urllib.parse.unquote(m.group(1)) if m else ""

def public_role(r, users=None):
    return {"key": r["key"], "name": r["name"], "description": r["description"], "system": r["system"], "priority": r["priority"],
            "permissions": "*" if "*" in r["permissions"] else P.clean(r["permissions"]), "users": users if users is not None else r.get("users", 0),
            "editable": r["key"] != "admin", "deletable": not r["system"]}

def role_fields(b, cur=None):
    name = " ".join(str(b.get("name", cur["name"] if cur else "")).split())[:41]
    if not name: raise HttpError(400, "Informe o nome da role")
    if len(name) > 40: raise HttpError(400, "Nome da role: até 40 caracteres")
    desc = " ".join(str(b.get("description", cur["description"] if cur else "")).split())
    if len(desc) > 200: raise HttpError(400, "Descrição da role: até 200 caracteres")
    try: prio = int(b.get("priority", cur["priority"] if cur else 20))
    except (TypeError, ValueError): raise HttpError(400, "Prioridade inválida")
    if not 1 <= prio <= 99: raise HttpError(400, "Prioridade: de 1 a 99 (o Administrador é 100)")
    return name, desc, prio

def check_grant(u, new_perms, cur=None):
    """Sem escalada: fora o Administrador, só se concede o que se tem, e só se mexe em papel contido no próprio."""
    if is_admin(u): return
    if cur is not None and not cur["perms"] <= u["perms"]:
        raise HttpError(403, "Você não pode alterar uma role com permissões que a sua não tem")
    extra = set(new_perms) - set(u["perms"])
    if extra: raise HttpError(403, "Você não pode conceder permissões que não tem: " + ", ".join(sorted(extra)))

def r_roles(h, **_):
    u = h.require("roles.manage")
    h.send_json({"roles": [public_role(r) for r in open_db().list_roles()], "catalog": P.catalog(), "mine": sorted(u["perms"]),
                 "isAdmin": is_admin(u)})

def r_role_create(h, **_):
    u = h.require("roles.manage"); b = h.body(); db = open_db()
    name, desc, prio = role_fields(b)
    src = db.role(str(b.get("from") or "")) if b.get("from") else None
    perms = P.clean(b["permissions"] if isinstance(b.get("permissions"), list) else (sorted(src["perms"]) if src else []))
    check_grant(u, perms)
    base = core.slug(name)[:28].strip("-") or "papel"
    if len(base) < 2: base = f"papel-{base}"
    key, i = base, 2
    while db.role(key) or key in P.SYSTEM_KEYS: key = f"{base[:26]}-{i}"; i += 1
    if not ROLE_KEY_RE.fullmatch(key): raise HttpError(400, "Nome da role inválido")
    r = db.create_role(key, name, desc, perms, prio)
    audit(u["login"], "papel_criado", f"papel:{key}", nome=name, permissoes=len(perms), **({"copia_de": src["key"]} if src else {}))
    h.send_json({"role": public_role(r, 0)})

def r_role_update(h, **_):
    u = h.require("roles.manage"); b = h.body(); db = open_db()
    key = role_key_from(h.path)
    cur = db.role(key)
    if not cur: raise HttpError(404, "role não encontrada")
    if key == "admin": raise HttpError(400, "A role Administrador não pode ser alterada")
    if b.get("reset"):
        check_grant(u, P.DEFAULTS.get(key, {}).get("permissions", []), cur)
        new = db.reset_role(key)
    else:
        name, desc, prio = role_fields(b, cur)
        perms = P.clean(b["permissions"]) if isinstance(b.get("permissions"), list) else sorted(cur["perms"])
        check_grant(u, perms, cur)
        new = db.update_role(key, name=name, description=desc, permissions=perms, priority=prio)
    added, removed = sorted(new["perms"] - cur["perms"]), sorted(cur["perms"] - new["perms"])
    audit(u["login"], "papel_alterado", f"papel:{key}", nome=new["name"], adicionadas=", ".join(added), removidas=", ".join(removed),
          **({"restaurado_padrao": "sim"} if b.get("reset") else {}))
    h.send_json({"role": public_role(new, len(db.users_with_role(key)))})

def r_role_delete(h, **_):
    u = h.require("roles.manage"); b = h.body(); db = open_db()
    key = role_key_from(h.path)
    cur = db.role(key)
    if not cur: raise HttpError(404, "role não encontrada")
    check_grant(u, [], cur)
    reassign = b.get("reassign") or None
    if reassign: role_choice(u, reassign)
    n = db.delete_role(key, reassign)
    audit(u["login"], "papel_excluido", f"papel:{key}", nome=cur["name"], usuarios=n, **({"realocados_para": reassign} if n else {}))
    h.send_json({"ok": True, "moved": n})

# ───────────────────────── rotas: pastas ─────────────────────────
# Árvore por tipo de documento (runbook, doc). Estrutura: permissão T.folders. Mover documento: T.edit.
# Mover não gera versão: a pasta é do banco, o arquivo continua no mesmo lugar.

def folder_type(t):
    if t not in DT.TYPES or not DT.info(t)["folders"]: raise HttpError(400, "Este tipo de documento não usa pastas")
    return t

def folder_id(h):
    m = re.search(r"/api/folders/(\d+)", h.path)
    f = open_db().folder(int(m.group(1))) if m else None
    if not f: raise HttpError(404, "pasta não encontrada")
    return f

def parent_arg(v):
    if v in (None, "", "none"): return None
    if not str(v).isdigit(): raise HttpError(400, "pasta inválida")
    return int(v)

def r_folders(h, **_):
    u = h.require(); t = folder_type(h.query().get("type") or "")
    if not can(u, f"{t}.view"): raise HttpError(403, "Seu perfil não tem permissão para esta ação")
    vis = summary_visible(u)
    fmap = open_db().doc_folders(t)
    direct = {}
    unfiled = 0
    for s in LIB.summaries(vis, dtype=t):
        fid = fmap.get(s["id"])
        if fid is None: unfiled += 1
        else: direct[fid] = direct.get(fid, 0) + 1
    fs = open_db().folders(t)
    kids = {}
    for f in fs: kids.setdefault(f["parent_id"], []).append(f["id"])
    def total(fid): return direct.get(fid, 0) + sum(total(k) for k in kids.get(fid, []))
    h.send_json({"folders": [{"id": f["id"], "name": f["name"], "parentId": f["parent_id"], "position": f["position"],
                              "count": direct.get(f["id"], 0), "total": total(f["id"])} for f in fs],
                 "unfiled": unfiled, "canManage": can(u, f"{t}.folders")})

def r_folder_create(h, **_):
    b = h.body(); t = folder_type(str(b.get("type") or ""))
    u = h.require(f"{t}.folders")
    f = open_db().create_folder(t, b.get("name"), parent_arg(b.get("parent_id")))
    FOLDER_GEN[0] += 1
    audit(u["login"], "pasta_criada", f"pasta:{f['id']}", tipo=t, caminho=open_db().folder_path(f["id"]))
    h.send_json({"folder": f})

def r_folder_update(h, **_):
    cur = folder_id(h); b = h.body()
    u = h.require(f"{cur['type']}.folders")
    before = open_db().folder_path(cur["id"])
    kw = {}
    if "name" in b: kw["name"] = b["name"]
    if "parent_id" in b: kw["parent_id"] = parent_arg(b["parent_id"])
    if "position" in b:
        try: kw["position"] = int(b["position"])
        except (TypeError, ValueError): raise HttpError(400, "posição inválida")
    f = open_db().update_folder(cur["id"], **kw)
    FOLDER_GEN[0] += 1
    after = open_db().folder_path(f["id"])
    if f["name"] != cur["name"]: audit(u["login"], "pasta_renomeada", f"pasta:{f['id']}", de=before, para=after)
    if f["parent_id"] != cur["parent_id"]: audit(u["login"], "pasta_movida", f"pasta:{f['id']}", de=before, para=after)
    h.send_json({"folder": f})

def r_folder_delete(h, **_):
    cur = folder_id(h); b = h.body()
    u = h.require(f"{cur['type']}.folders")
    path = open_db().folder_path(cur["id"])
    r = open_db().delete_folder(cur["id"], parent_arg(b["moveTo"]) if "moveTo" in b else ...)
    FOLDER_GEN[0] += 1
    audit(u["login"], "pasta_excluida", f"pasta:{cur['id']}", caminho=path, documentos_movidos=r["docs"], subpastas_movidas=r["subs"])
    h.send_json({"ok": True, **r})

def r_doc_move(h, pid, **_):
    u = h.require(doc_perm(pid, "edit")); b = h.body()
    t = folder_type(doc_type(pid))
    get_folder(pid)
    before = doc_folder_path(pid)
    open_db().set_doc_folder(pid, t, parent_arg(b.get("folder_id")))
    FOLDER_GEN[0] += 1
    audit(u["login"], "documento_movido", pid, de=before or "Sem pasta", para=doc_folder_path(pid) or "Sem pasta")
    h.send_json({"ok": True, "folderId": parent_arg(b.get("folder_id"))})

def r_folders_from_template(h, **_):
    b = h.body(); t = folder_type(str(b.get("type") or ""))
    u = h.require(f"{t}.folders")
    key = str(b.get("template") or tpl.default_key(t))
    tt = tpl.load(key)
    if tt.get("kind") != t: raise HttpError(400, "Template de outro tipo")
    before = len(open_db().folders(t))
    for path in tt.get("folders", []): open_db().ensure_path(t, path)
    made = len(open_db().folders(t)) - before
    FOLDER_GEN[0] += 1
    audit(u["login"], "pastas_do_template", f"template:{key}", tipo=t, criadas=made)
    h.send_json({"ok": True, "created": made})

# ───────────────────────── rotas: governança ─────────────────────────

def r_governance_get(h, **_):
    h.require(any_of=("app.reset", "users.manage"))
    h.send_json({"governance": governance()})

def r_governance_put(h, **_):
    u = h.require(any_of=("app.reset", "users.manage")); b = h.body()
    if not isinstance(b.get("require_distinct_approver"), bool): raise HttpError(400, "Valor inválido")
    g = {**governance(), "require_distinct_approver": b["require_distinct_approver"]}
    open_db().set_setting("governance", g, by=u["login"])
    audit(u["login"], "governanca_alterada", aprovador_diferente="sim" if g["require_distinct_approver"] else "não")
    h.send_json({"governance": g})

def audit_filters(q, default_days=0):
    """Filtros da auditoria vindos da URL (tela e exportação): q, days (0 = todo o período), user e actions."""
    try: days = max(0, min(3650, int(q.get("days", default_days) or 0)))
    except ValueError: raise HttpError(400, "Período inválido")
    actions = [a for a in str(q.get("actions", "")).split(",") if re.fullmatch(r"[a-z_]{1,40}", a)][:80]
    return {"q": str(q.get("q", "")).strip()[:120], "days": days, "user": str(q.get("user", "")).strip().lower()[:80], "actions": actions}

def r_audit(h, **_):
    h.require("audit.view")
    q = h.query()
    try: limit = max(1, min(int(q.get("limit", 500) or 500), 5000))
    except ValueError: raise HttpError(400, "Limite inválido")
    f, db = audit_filters(q), open_db()
    h.send_json({"entries": db.read_audit(limit=limit, **f), "total": db.count_audit_filtered(**f), "limit": limit})

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
    h.require("logs.manage")
    h.send_json({"config": public_log_cfg(log_cfg()), "status": FWD.status(), "logDir": str(DATA_DIR / "logs"),
                 "sample": logfwd.make_event(datetime.now(), "maria.souza", "documento_salvo", "PB-01", {"versao": "0.2"}, "10.0.0.15",
                                             brand()["name"], APP_VERSION)})

def r_logs_put(h, **_):
    u = h.require("logs.manage"); b = h.body()
    c = clean_log_cfg(b, open_db().get_setting("logs"))
    open_db().set_setting("logs", c, by=u["login"]); _log_cfg["at"] = 0
    audit(u["login"], "logs_configurados", retencao_dias=c["retention_days"], http=c["http"]["enabled"], syslog=c["syslog"]["enabled"],
          arquivo=c["file"]["enabled"])
    threading.Thread(target=lambda: (open_db().purge(c["retention_days"]), FWD.purge_files(c["retention_days"])), daemon=True).start()
    r_logs_get(h)

def r_logs_retention_preview(h, **_):
    """Quanto a retenção indicada apagaria agora (a tela confirma antes de reduzir a retenção)."""
    h.require("logs.manage")
    try: days = max(1, min(3650, int(h.query().get("days", ""))))
    except ValueError: raise HttpError(400, "Informe os dias de retenção")
    h.send_json({"days": days, "events": open_db().count_audit_older(days), "files": FWD.count_files_older(days)})

def r_logs_test(h, **_):
    u = h.require("logs.manage"); b = h.body()
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
    u = h.require("audit.view")
    f = audit_filters(h.query(), default_days=30)
    days = f["days"]
    name, lines = brand()["name"], []
    for r in open_db().audit_filtered(**f):
        d = r["detail"]; ip = d.pop("ip", None)
        lines.append(json.dumps(logfwd.make_event(datetime.fromisoformat(r["ts"]), r["user"], r["action"], r["target"], d, ip, name, APP_VERSION),
                                ensure_ascii=False))
    audit(u["login"], "auditoria_exportada", dias=days or "todos", eventos=len(lines), **({"filtro": f["q"]} if f["q"] else {}),
          **({"usuario": f["user"]} if f["user"] else {}), **({"acoes": len(f["actions"])} if f["actions"] else {}))
    h.send_bytes(("\n".join(lines) + "\n").encode("utf-8"), "application/x-ndjson; charset=utf-8", f"auditoria-{date.today().isoformat()}.jsonl")

# ───────────────────────── rotas: SSO (OpenID Connect) ─────────────────────────

SSO_DEFAULT = {"enabled": False, "label": "Entrar com SSO", "issuer": "", "client_id": "", "client_secret": "", "scopes": "openid email profile",
               "public_url": "", "login_claim": "preferred_username", "name_claim": "name", "email_claim": "email",
               "role_claim": "groups", "role_map": {}, "default_role": "viewer",
               "auto_create": True, "allowed_domains": "", "local_login": "all"}

def sso_cfg():
    c = json.loads(json.dumps(SSO_DEFAULT)); c.update(open_db().get_setting("sso") or {})
    return c

def r_sso_status(h, **_):
    c = sso_cfg()
    h.send_json({"enabled": bool(c["enabled"]), "label": c["label"] or "Entrar com SSO", "localLogin": c["local_login"]})

def r_sso_get(h, **_):
    h.require("sso.manage")
    c = sso_cfg(); c["client_secret_set"] = bool(c.pop("client_secret"))
    h.send_json({"config": c, "redirectUri": sso.redirect_uri(c["public_url"]) if c["public_url"] else "",
                 "roles": [{"key": r["key"], "name": r["name"]} for r in open_db().roles().values()]})

def r_sso_put(h, **_):
    u = h.require("sso.manage"); b = h.body(); c = sso_cfg()
    s = lambda k, n=300: str(b.get(k, c[k]) or "").strip()[:n]
    c.update(label=s("label", 60) or "Entrar com SSO", issuer=s("issuer", 500).rstrip("/"), client_id=s("client_id", 300),
             scopes=s("scopes") or "openid email profile", public_url=s("public_url", 500).rstrip("/"),
             login_claim=s("login_claim", 80) or "preferred_username", name_claim=s("name_claim", 80) or "name",
             email_claim=s("email_claim", 80) or "email", role_claim=s("role_claim", 120), allowed_domains=s("allowed_domains", 500).lower(),
             auto_create=bool(b.get("auto_create", c["auto_create"])), enabled=bool(b.get("enabled")),
             local_login="admins" if b.get("local_login") == "admins" else "all")
    roles = open_db().roles()
    dr = b.get("default_role", c.get("default_role", "viewer"))
    if dr not in ("", *roles): raise HttpError(400, f"Role padrão inexistente: {dr}")
    c["default_role"] = dr
    rm = b.get("role_map") if isinstance(b.get("role_map"), dict) else {}
    bad = [k for k in rm if k not in roles]
    if bad: raise HttpError(400, f"Role inexistente no mapeamento de grupos: {', '.join(bad)}")
    c["role_map"] = {r: str(rm.get(r, "") or "")[:1000] for r in roles if str(rm.get(r, "") or "").strip()}
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
    h.require("sso.manage"); b = h.body()
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
    if not c["enabled"]: return h.send_redirect("/?sso_error=desativado")
    try:
        url, state, nonce, verifier = sso.start(c)
    except sso.SSOError as e:
        audit("?", "sso_falhou", motivo=str(e))
        return h.send_redirect("/?sso_error=indisponivel")
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
    if domains and not any(email.endswith("@" + d) for d in domains): raise sso.SSOError(f"Domínio de e-mail não autorizado ({email or 'sem e-mail'})", "conta")
    roles = db.roles()
    mapped = sso.map_role(claims, c, roles) if c["role_claim"] else None
    if c["default_role"] and c["default_role"] not in roles: c["default_role"] = "viewer"
    has_rules = bool(c["role_claim"]) and any(str(v).strip() for v in c["role_map"].values())
    u = db.user_by_subject(subject)
    if not u:
        if not LOGIN_RE.fullmatch(login or ""): raise sso.SSOError("O provedor não enviou um login válido (ajuste a claim de login)", "conta")
        u = db.get_user(login)
        if u and u.get("auth") != "sso":
            raise sso.SSOError(f"Já existe uma conta local \"{login}\". Peça a um administrador para convertê-la em conta SSO", "conta")
        if u and u.get("sso_subject") and u["sso_subject"] != subject: raise sso.SSOError("Esta conta já está vinculada a outra identidade do provedor", "conta")
        if u:
            db.bind_subject(login, subject, name); u = db.get_user(login)
        else:
            role = mapped or (c["default_role"] if not has_rules or c["default_role"] else None)
            if not c["auto_create"]: raise sso.SSOError("Usuário não cadastrado. Peça acesso a um administrador", "conta")
            if not role: raise sso.SSOError("Seu usuário não pertence a nenhum grupo autorizado", "conta")
            u = db.create_user(login, name, role, NO_PASSWORD, must_change=False, auth="sso", sso_subject=subject)
            audit("sistema", "usuario_criado", login, papel=role, autenticacao="sso")
    if not u["active"]: raise sso.SSOError("Usuário desativado", "inativo")
    if has_rules:
        role = mapped or c["default_role"]
        if not role: raise sso.SSOError("Seu usuário não pertence a nenhum grupo autorizado", "conta")
        if role != u["role_id"]:
            try:
                db.update_user(u["login"], role=role); audit("sistema", "usuario_alterado", u["login"], papel=role, origem="grupos do SSO")
            except StoreError:
                pass    # não rebaixa o último administrador ativo
    return db.get_user(u["login"])

def r_sso_callback(h, **_):
    c, q = sso_cfg(), h.query()
    # o navegador recebe só um código (o texto mostrado é fixo, em app.js); o motivo detalhado vai para a auditoria
    fail = lambda code, internal: (audit("?", "sso_falhou", motivo=internal),
                                   h.send_redirect("/?sso_error=" + code, [_sso_cookie(h, "", 0)]))
    if not c["enabled"]: return fail("desativado", "SSO desativado")
    if q.get("error"): return fail("recusado", f"{q.get('error')}: {q.get('error_description', '')[:200]}")
    st = q.get("state", "")
    ck = SimpleCookie(h.headers.get("Cookie", ""))
    if not st or "pbsso" not in ck or not hmac.compare_digest(ck["pbsso"].value, st): return fail("expirado", "state ausente ou diferente do cookie")
    saved = open_db().pop_sso_state(st)
    if not saved or not q.get("code"): return fail("expirado", "state desconhecido ou vencido")
    try:
        tok, d = sso.exchange(c, q["code"], saved["verifier"])
        claims = sso.validate_id_token(tok["id_token"], d, c["client_id"], saved["nonce"])
        claims = {**sso.userinfo(d, tok.get("access_token"), claims["sub"]), **claims}
        u = sso_user(c, claims)
    except sso.SSOError as e:
        return fail(e.code, str(e))
    except StoreError as e:
        return fail("tecnico", str(e))
    db = open_db()
    token = db.create_session(u["login"], h.client_ip(), h.headers.get("User-Agent"))
    audit(u["login"], "login", metodo="sso")
    # página intermediária: a navegação seguinte parte do próprio site, e o cookie de sessão (SameSite=Strict) vale nela
    h.send_html('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=/#/"><title>Entrando…</title>'
                '<p style="font:15px system-ui;margin:40px">Entrando… <a href="/#/">continuar</a></p>',
                [h.session_cookie(token), _sso_cookie(h, "", 0)])

# ───────────────────────── rotas: versões ─────────────────────────

KIND_NAMES = {"base": "Registro inicial", "criacao": "Criação", "importacao": "Importação", "documento": "Documento",
              "fluxograma": "Fluxograma", "ramo": "Ramos", "status": "Status", "restauracao": "Restauração", "sugestao": "Sugestão aceita"}

def version_id(h):
    m = re.search(r"/versions/(\d+)", h.path.split("?")[0])
    if not m: raise HttpError(404, "versão não encontrada")
    return int(m.group(1))

def can_see_version(v, u):
    return can_view_status(u, doc_type(v["pid"].split("#")[0]), v["status"])

def version_meta(v):
    return {k: v[k] for k in ("id", "version", "status", "created_at", "author", "author_name", "kind", "note", "template")} | \
           {"kindName": KIND_NAMES.get(v["kind"], v["kind"])}

def version_view(folder, pid, v):
    doc = core.parse_md(v["md"])
    flow = core.drawio_to_flow(v["drawio"]) if v["drawio"].strip() else core.empty_flow(doc_type(pid))
    key = v.get("template") if v.get("template") and tpl.KEY_RE.fullmatch(v["template"]) and tpl.path_of(v["template"]).exists() else template_of(pid)
    teams = template_teams(key)
    view = core.build_view(pid, folder.name, doc, flow, v["refs"], teams)
    view.update(teams=teams, templateKey=key, templateName=template_name(key))
    return view

def r_versions(h, pid, **_):
    u = h.require(doc_perm(pid, "view"))
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
    u = h.require(doc_perm(pid, "view"))
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
    u = h.require(doc_perm(pid, "view"))
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
    u = h.require(doc_perm(pid, "restore")); b = h.body()
    folder, v = _version(h, pid, u, version_id(h))
    with LOCK:
        check_rev(folder, b.get("rev"))
        ensure_baseline(folder, pid)
        md, dio = core.files_of(folder)
        cur = core.parse_md(md.read_text("utf-8"))
        change = prod_change(b, cur)
        doc = core.set_gov(core.parse_md(v["md"]), core.get_gov(cur))
        touch_review(doc, u, cur); ver = bump(doc, cur, change=change)
        backup(pid, md, dio, core.MAPPINGS_FILE)
        core.atomic_write(md, core.doc_to_md(doc))
        if v["drawio"].strip():
            view = load_pb_fresh(folder)
            write_flow(folder, pid, view["name"], core.drawio_to_flow(v["drawio"]), dict(v["refs"]))
        LIB.invalidate(pid)
        snapshot(folder, pid, u, "restauracao", change_note(change, f"Conteúdo da versão {v['version']} ({v['created_at'][:10]})"))
    audit(u["login"], "versao_restaurada", pid, de=v["version"], nova=ver, **change_audit(change))
    h.send_json({"ok": True, "playbook": load_pb(folder), "version": ver})

ROUTES = {
    ("POST", "/api/login"): r_login, ("POST", "/api/logout"): r_logout,
    ("GET", "/api/me"): r_me, ("POST", "/api/me/password"): r_password,
    ("GET", "/api/data"): r_data, ("GET", "/api/pb/{pb}"): r_pb_get,
    ("GET", "/api/bootstrap"): r_bootstrap, ("GET", "/api/library"): r_library, ("GET", "/api/search"): r_search,
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
    ("GET", "/api/logs"): r_logs_get, ("PUT", "/api/logs"): r_logs_put, ("POST", "/api/logs/test"): r_logs_test, ("GET", "/api/logs/retention-preview"): r_logs_retention_preview,
    ("GET", "/api/sso/status"): r_sso_status, ("GET", "/api/sso/login"): r_sso_login, ("GET", "/api/sso/callback"): r_sso_callback,
    ("GET", "/api/sso/config"): r_sso_get, ("PUT", "/api/sso/config"): r_sso_put, ("POST", "/api/sso/test"): r_sso_test,
    ("GET", "/api/templates"): r_tpl_list, ("POST", "/api/templates"): r_tpl_create, ("POST", "/api/templates/import"): r_tpl_import,
    ("GET", "/api/templates/{t}"): r_tpl_get, ("DELETE", "/api/templates/{t}"): r_tpl_delete, ("GET", "/api/templates/{t}/export"): r_tpl_export,
    ("PUT", "/api/templates/{t}/doc"): r_tpl_doc, ("PUT", "/api/templates/{t}/flow"): r_tpl_flow, ("PUT", "/api/templates/{t}/meta"): r_tpl_meta,
    ("GET", "/api/people"): r_people,
    ("GET", "/api/roles"): r_roles, ("POST", "/api/roles"): r_role_create,
    ("PUT", "/api/roles/{role}"): r_role_update, ("DELETE", "/api/roles/{role}"): r_role_delete,
    ("GET", "/api/governance"): r_governance_get, ("PUT", "/api/governance"): r_governance_put,
    ("GET", "/api/pb/{pb}/links"): r_doc_links, ("GET", "/api/pb/{pb}/lint"): r_doc_lint,
    ("GET", "/api/pb/{pb}/suggestions"): r_suggestions, ("POST", "/api/pb/{pb}/suggestions"): r_suggestion_create,
    ("POST", "/api/pb/{pb}/suggestions/{s}/accept"): r_suggestion_accept, ("POST", "/api/pb/{pb}/suggestions/{s}/reject"): r_suggestion_reject,
    ("POST", "/api/pb/{pb}/suggestions/{s}/withdraw"): r_suggestion_withdraw,
    ("POST", "/api/doc"): r_doc_create, ("GET", "/api/doc/next-id"): r_doc_next_id, ("PUT", "/api/pb/{pb}/folder"): r_doc_move,
    ("GET", "/api/folders"): r_folders, ("POST", "/api/folders"): r_folder_create, ("POST", "/api/folders/from-template"): r_folders_from_template,
    ("PUT", "/api/folders/{f}"): r_folder_update, ("DELETE", "/api/folders/{f}"): r_folder_delete,
    ("GET", "/api/pb/{pb}/export"): r_pb_export, ("GET", "/api/export"): r_export_all, ("POST", "/api/import"): r_import,
    ("POST", "/api/flow/parse"): r_flow_parse, ("POST", "/api/md"): r_md, ("POST", "/api/flow/render"): r_flow_render,
    ("GET", "/api/branding"): r_brand_get, ("PUT", "/api/branding"): r_brand_put,
    ("GET", "/api/branding/logo"): r_logo_get, ("PUT", "/api/branding/logo"): r_logo_put, ("DELETE", "/api/branding/logo"): r_logo_delete,
}

# ───────────────────────── linha de comando ─────────────────────────

def cmd_adduser(args):
    login = args.login.strip().lower()
    if not LOGIN_RE.fullmatch(login): sys.exit("Login inválido (3 a 80: letras minúsculas, números, . _ - @)")
    if not open_db().role(args.role):
        sys.exit(f"Role inexistente: {args.role}. Roles: {', '.join(open_db().roles())}")
    pw = getpass.getpass(f"Senha para {login}: ")
    if getpass.getpass("Repita a senha: ") != pw: sys.exit("As senhas não conferem.")
    try: validate_password(pw)
    except HttpError as e: sys.exit(e.msg)
    db = open_db()
    old = db.get_user(login)
    db.upsert_user(login, args.name or (old and old["name"]) or login, args.role, hash_password(pw))
    audit("cli", "usuario_cli", login, papel=args.role)
    print(f"Usuário {login} salvo com a role {db.role(args.role)['name']} em {DB.path}")

def bootstrap_admin():
    """Primeira subida (ex.: Docker): cria o administrador indicado em MEDUSA_ADMIN_LOGIN se ainda não há nenhum.
    Sem MEDUSA_ADMIN_PASSWORD, gera uma senha temporária e a mostra uma única vez no log; a troca é obrigatória."""
    db = open_db()
    login = os.environ.get("MEDUSA_ADMIN_LOGIN", "").strip().lower()
    if db.count_active_admins() >= 1 or not login: return
    if not LOGIN_RE.fullmatch(login): sys.exit("MEDUSA_ADMIN_LOGIN inválido (3 a 80: letras minúsculas, números, . _ - @)")
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
        p.add_argument("--role", default="viewer", help="chave da role (admin, editor, viewer ou uma role criada)"); p.add_argument("--name")
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
    made = tpl.ensure_seed()
    if made: print("Templates criados em", tpl.TPL_DIR, ":", ", ".join(made))
    for t in DT.TYPES: DT.src_dir(t).mkdir(parents=True, exist_ok=True)
    bootstrap_admin()
    global FWD
    FWD = logfwd.Forwarder(log_cfg, DATA_DIR / "logs")
    threading.Thread(target=retention_loop, name="retention", daemon=True).start()
    if open_db().count_active_admins() < 1:
        sys.exit("Nenhum administrador cadastrado. Crie o primeiro com:\n"
                 f"  python3 {Path(__file__).name} adduser <login> --role admin --name \"Seu Nome\"\n"
                 "ou defina MEDUSA_ADMIN_LOGIN para criá-lo com senha temporária (ver INSTALACAO-DOCKER.md).")
    LIB.warm()
    srv = Server((a.host, port), Handler)
    print(f"Playbooks em http://{'localhost' if a.host in ('127.0.0.1', '::1') else a.host}:{port}  (Ctrl+C para parar)")
    print(f"Banco de dados: {DB.path}")
    if a.host not in ("127.0.0.1", "::1", "localhost") and not a.secure_cookies:
        print("Atenção: exposto na rede sem --secure-cookies. Use um proxy com HTTPS.")
    def stop(*_):                 # docker/podman stop: grava o cache dos documentos antes de sair
        LIB.persist(); raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        LIB.persist()

if __name__ == "__main__":
    main()
