#!/usr/bin/env python3
"""Servidor da ferramenta de playbooks: leitura, edição, ciclo de vida e controle de acesso.

  python3 server.py adduser <login> --role admin [--name "Nome"]   cria/atualiza usuário (pede a senha)
  python3 server.py [--host 127.0.0.1] [--port 8765] [--secure-cookies]

Variáveis de ambiente (usadas no Docker)
  MEDUSA_HOME            pasta de dados: playbooks/, templates/, data/ (banco), .backups/, mappings.json
  MEDUSA_HOST / MEDUSA_PORT / MEDUSA_SECURE_COOKIES=1
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
import argparse, base64, getpass, hashlib, hmac, io, json, os, re, secrets, shutil, sys, threading, time, zipfile
from datetime import date
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import bundle
import ramos
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
LOGIN_RE = re.compile(r"^[a-z0-9._-]{3,40}$")
STATIC = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/flow.js": "flow.js",
          "/editor.js": "editor.js", "/style.css": "style.css", "/theme.js": "theme.js", "/docs.js": "docs.js"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon", ".woff2": "font/woff2"}

DEFAULT_BRAND = {"name": "Medusa Docs", "color": "#3B5BDB", "homeTitle": "Playbooks de resposta a incidentes",
                 "homeSubtitle": "Base interativa dos playbooks do time de segurança. Escolha um playbook, navegue pelo fluxograma e clique "
                                 "em qualquer caixa, ramo (R1…), passo (T0, A3…) ou time para ler o trecho da documentação."}
LOGO_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg", "image/webp": ".webp"}
MAX_LOGO = 512 * 1024
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

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
            "lastLogin": u.get("last_login"), "sessions": u.get("sessions")}

def audit(user, action, target="", **detail):
    open_db().audit(user, action, target, **detail)

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

    def handle_api(self, method):
        path = self.path.split("?")[0]
        try:
            if method != "GET": self.csrf()
            key = re.sub(r"/PB-\d{2,3}", "/{pb}", re.sub(r"^/api/users/[^/]+", "/api/users/{u}", path))
            key = re.sub(r"^(/api/pb/\{pb\}/ramos)/[^/]+$", r"\1/{r}", key)
            if not path.startswith("/api/templates/import"):
                key = re.sub(r"^/api/templates/[^/]+", "/api/templates/{t}", key)
            route = ROUTES.get((method, key))
            if not route: raise HttpError(404, "não encontrado")
            m = re.search(r"/(PB-\d{2,3})(?:/|$)", path); u = re.match(r"^/api/users/([^/]+)", path)
            t = re.match(r"^/api/templates/([^/]+)", path)
            return route(self, pid=m.group(1) if m else None, login=u.group(1) if u else None, tkey=t.group(1) if t else None)
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
    ip = h.client_address[0]; key = f"{login}|{ip}"
    wait = db.locked_for(key)
    if wait: raise HttpError(429, f"Muitas tentativas. Tente de novo em {int(wait // 60) + 1} min.")
    u = db.get_user(login)
    if not (check_password(pw, u["hash"] if u else DUMMY_HASH) and u and u["active"]):
        db.register_fail(key)
        audit(login or "?", "login_falhou", ip=ip)
        raise HttpError(401, "Usuário ou senha inválidos")
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

def r_pb_doc(h, pid, **_):
    u = h.require("editor")
    folder = get_folder(pid); b = h.body()
    doc = b.get("doc")
    if not isinstance(doc, dict) or not str(doc.get("title", "")).strip() or not isinstance(doc.get("sections"), list):
        raise HttpError(400, "documento inválido")
    with LOCK:
        check_rev(folder, b.get("rev"))
        md, dio = core.files_of(folder)
        old = core.parse_md(md.read_text("utf-8"))
        touch_review(doc, u, old)
        doc = core.parse_md(core.doc_to_md(doc))          # mesma forma que será lida de volta
        view = load_pb(folder)
        flow, refs = view["flow"], view["refs"]
        changes = ramos.sync_from_doc(flow, refs, old, doc)
        backup(pid, md, *( (dio, core.MAPPINGS_FILE) if changes else ()))
        md.write_text(core.doc_to_md(doc), "utf-8")
        if changes: write_flow(folder, pid, view["name"], flow, refs)
    audit(u["login"], "documento_salvo", pid, **({"ramos": "; ".join(changes)} if changes else {}))
    h.send_json({"ok": True, "playbook": load_pb(folder), "sync": changes})

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
        md, dio = core.files_of(folder)
        view = load_pb(folder)
        backup(pid, dio, md, core.MAPPINGS_FILE)
        doc = core.parse_md(md.read_text("utf-8"))
        changes = ramos.sync_from_flow(doc, view["flow"], view["refs"], flow, refs)
        write_flow(folder, pid, view["name"], flow, refs)
        md.write_text(core.doc_to_md(touch_review(doc, u, doc)), "utf-8")
        new_teams = add_template_teams(view["templateKey"], sorted(tpl.used_teams(flow) - set(view["teams"])))
    audit(u["login"], "fluxograma_salvo", pid, **({"ramos": "; ".join(changes)} if changes else {}),
          **({"times_no_template": ", ".join(new_teams)} if new_teams else {}))
    h.send_json({"ok": True, "playbook": load_pb(folder), "sync": changes})

def r_pb_ramo_add(h, pid, **_):
    u = h.require("editor")
    folder = get_folder(pid); b = h.body()
    name, q = str(b.get("name", "")).strip()[:80], str(b.get("q", "")).strip()[:200]
    if not name: raise HttpError(400, "Informe o nome do ramo")
    with LOCK:
        check_rev(folder, b.get("rev"))
        md, dio = core.files_of(folder)
        view = load_pb(folder)
        doc, flow, refs = core.parse_md(md.read_text("utf-8")), view["flow"], view["refs"]
        k = ramos.next_key(doc, flow, refs)
        backup(pid, md, dio, core.MAPPINGS_FILE)
        ramos.add(doc, flow, refs, k, name, q)
        write_flow(folder, pid, view["name"], flow, refs)
        md.write_text(core.doc_to_md(touch_review(doc, u, doc)), "utf-8")
    audit(u["login"], "ramo_criado", pid, ramo=f"R{k} {name}")
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
        backup(pid, md, dio, core.MAPPINGS_FILE)
        ramos.remove(doc, flow, refs, k)
        write_flow(folder, pid, view["name"], flow, refs)
        md.write_text(core.doc_to_md(touch_review(doc, u, doc)), "utf-8")
    audit(u["login"], "ramo_excluido", pid, ramo=f"R{k}")
    h.send_json({"ok": True, "playbook": load_pb(folder)})

def r_pb_status(h, pid, **_):
    u = h.require("editor")
    folder = get_folder(pid); b = h.body()
    status = b.get("status")
    if status not in core.STATUSES: raise HttpError(400, "status inválido")
    with LOCK:
        check_rev(folder, b.get("rev"))
        md, _ = core.files_of(folder)
        doc = core.parse_md(md.read_text("utf-8"))
        gov = core.get_gov(doc); before = gov["status"]
        if status == before: raise HttpError(400, f"O playbook já está em {status}")
        if status == "Produção":
            ap = open_db().get_user(str(b.get("approver", "")))
            if not ap or not ap["active"] or ROLES[ap["role"]] < ROLES["editor"]:
                raise HttpError(400, "Escolha um aprovador (editor ou administrador ativo)")
            gov["approver"] = ap["name"]
        gov["status"] = status
        backup(pid, md)
        md.write_text(core.doc_to_md(core.set_gov(doc, gov)), "utf-8")
    audit(u["login"], "status_alterado", pid, de=before, para=status, aprovador=gov.get("approver", "") if status == "Produção" else "",
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
        (folder / f"{base}.md").write_text(core.doc_to_md(doc), "utf-8")
        (folder / f"{pid.lower()}-{core.slug(name)}.drawio").write_text(core.flow_to_drawio(flow, pid, name), "utf-8")
        save_refs(pid, refs)
        set_link(pid, t["key"])
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
    audit(u["login"], "playbook_excluido", pid, lixeira=dest.name)
    h.send_json({"ok": True, "trash": dest.name})

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
        data, ctype, fname = bundle.export(view, {**core.load_teams(), **view["teams"]}, u["name"], brand()["name"]).encode(), "text/markdown; charset=utf-8", f"{base}.medusa.md"
    elif fmt == "md":
        data, ctype, fname = core.doc_to_md(view["doc"]).encode(), "text/markdown; charset=utf-8", f"{base}.md"
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
            z.writestr(f"{f.name.lower()}.medusa.md", bundle.export(v, {**union, **v["teams"]}, u["name"], name))
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
        if p["createTeams"]: add_template_teams(tkey, p["createTeams"], union)
        name = p["name"][:100]
        base = f"{pid}-{core.slug(name).title()}"
        folder = core.SRC / base
        folder.mkdir(parents=True)
        (folder / f"{base}.md").write_text(core.doc_to_md(doc), "utf-8")
        (folder / f"{pid.lower()}-{core.slug(name)}.drawio").write_text(core.flow_to_drawio(p["flow"], pid, name), "utf-8")
        save_refs(pid, p["refs"])
        set_link(pid, tkey)
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
    h.send_json({**brand(), "logo": logo["v"] if logo else None})

def r_brand_put(h, **_):
    u = h.require("admin"); b = h.body()
    cur = brand()
    name = str(b.get("name", cur["name"])).strip()[:40] or DEFAULT_BRAND["name"]
    color = str(b.get("color", cur["color"])).strip().upper() or DEFAULT_BRAND["color"]
    if not HEX_RE.fullmatch(color): raise HttpError(400, "Cor inválida: use #RRGGBB")
    title = " ".join(str(b.get("homeTitle") or cur["homeTitle"]).split())[:120] or DEFAULT_BRAND["homeTitle"]
    sub = " ".join(str(b.get("homeSubtitle", cur["homeSubtitle"]) or "").split())[:600]
    if b.get("homeReset"): title, sub = DEFAULT_BRAND["homeTitle"], DEFAULT_BRAND["homeSubtitle"]
    open_db().set_setting("branding", {"name": name, "color": color, "homeTitle": title, "homeSubtitle": sub}, by=u["login"])
    audit(u["login"], "marca_alterada", nome=name, cor=color, titulo_inicio=title)
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
    if not LOGIN_RE.fullmatch(login): raise HttpError(400, "Login: 3 a 40 caracteres (letras minúsculas, números, ponto, hífen, sublinhado)")
    if role not in ROLES: raise HttpError(400, "perfil inválido")
    pw = temp_password()
    new = open_db().create_user(login, str(b.get("name", "")).strip()[:80] or login, role, hash_password(pw), must_change=True)
    audit(u["login"], "usuario_criado", login, perfil=role)
    h.send_json({"user": public_user(new), "tempPassword": pw})

def r_user_update(h, login, **_):
    u = h.require("admin"); b = h.body()
    if login == u["login"] and ("role" in b or b.get("active") is False):
        raise HttpError(400, "Você não pode alterar o próprio perfil nem se desativar")
    name = str(b["name"]).strip()[:80] or login if "name" in b else None
    rec = open_db().update_user(login, name=name, role=b.get("role"), active=b.get("active"))
    audit(u["login"], "usuario_alterado", login, **{k: v for k, v in (("perfil", b.get("role")), ("ativo", b.get("active"))) if v is not None})
    h.send_json({"user": public_user(rec)})

def r_user_reset(h, login, **_):
    u = h.require("admin"); db = open_db()
    if not db.get_user(login): raise HttpError(404, "usuário não encontrado")
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

ROUTES = {
    ("POST", "/api/login"): r_login, ("POST", "/api/logout"): r_logout,
    ("GET", "/api/me"): r_me, ("POST", "/api/me/password"): r_password,
    ("GET", "/api/data"): r_data, ("GET", "/api/pb/{pb}"): r_pb_get,
    ("PUT", "/api/pb/{pb}/doc"): r_pb_doc, ("PUT", "/api/pb/{pb}/flow"): r_pb_flow, ("PUT", "/api/pb/{pb}/status"): r_pb_status,
    ("POST", "/api/pb"): r_pb_create, ("DELETE", "/api/pb/{pb}"): r_pb_delete,
    ("POST", "/api/pb/{pb}/ramos"): r_pb_ramo_add, ("DELETE", "/api/pb/{pb}/ramos/{r}"): r_pb_ramo_delete,
    ("POST", "/api/templates/{t}/ramos"): r_tpl_ramos,
    ("GET", "/api/approvers"): r_approvers, ("PUT", "/api/templates/{t}/teams"): r_tpl_teams,
    ("GET", "/api/users"): r_users, ("POST", "/api/users"): r_user_create,
    ("PUT", "/api/users/{u}"): r_user_update, ("DELETE", "/api/users/{u}"): r_user_delete,
    ("POST", "/api/users/{u}/reset"): r_user_reset, ("POST", "/api/users/{u}/logout"): r_user_logout,
    ("GET", "/api/audit"): r_audit,
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
