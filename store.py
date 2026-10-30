"""Banco de dados da ferramenta (SQLite, embutido no Python): usuários, sessões, tentativas de login, auditoria,
configurações, estados do login SSO e versões dos playbooks.

Arquivo único: data/playbooks.db. Cada thread do servidor usa a própria conexão, aberta uma vez (WAL,
synchronous=NORMAL); operações que precisam de várias leituras e escritas usam transação BEGIN IMMEDIATE.
A sessão validada fica 15 s em memória (cache invalidado em logout, troca de senha e alteração de usuário).
O esquema é versionado por PRAGMA user_version; novas versões entram em MIGRATIONS.
"""
import hashlib, json, os, secrets, sqlite3, sys, threading, time
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path

import perms

KEEP_DB_BACKUPS = 5             # cópias pré-migração guardadas em data/backups/
SESSION_CACHE_TTL = 15          # segundos que uma sessão validada fica em memória
MAX_LOGIN_ATTEMPTS_ROWS = 10_000

MIGRATIONS = [
    # v1
    """
    CREATE TABLE users (
        login        TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        role         TEXT NOT NULL CHECK (role IN ('viewer','editor','admin')),
        hash         TEXT NOT NULL,
        active       INTEGER NOT NULL DEFAULT 1,
        must_change  INTEGER NOT NULL DEFAULT 0,
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL,
        last_login   TEXT
    );
    CREATE TABLE sessions (
        token_hash   TEXT PRIMARY KEY,            -- guarda só o SHA-256 do token do cookie
        login        TEXT NOT NULL REFERENCES users(login) ON DELETE CASCADE,
        created_at   REAL NOT NULL,
        seen_at      REAL NOT NULL,
        ip           TEXT,
        user_agent   TEXT
    );
    CREATE INDEX sessions_login ON sessions(login);
    CREATE TABLE login_attempts (
        key          TEXT PRIMARY KEY,            -- login|ip
        fails        INTEGER NOT NULL DEFAULT 0,
        locked_until REAL NOT NULL DEFAULT 0
    );
    CREATE TABLE audit (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ts           TEXT NOT NULL,
        user         TEXT NOT NULL,
        action       TEXT NOT NULL,
        target       TEXT NOT NULL DEFAULT '',
        detail       TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX audit_ts ON audit(ts);
    CREATE INDEX audit_target ON audit(target);
    CREATE INDEX audit_user ON audit(user);
    """,
    # v2: configurações da instalação (marca, cor, logo)
    """
    CREATE TABLE settings (
        key          TEXT PRIMARY KEY,
        value        TEXT NOT NULL,
        updated_at   TEXT NOT NULL,
        updated_by   TEXT
    );
    """,
    # v3: SSO (OpenID Connect) e histórico de versões dos playbooks
    """
    ALTER TABLE users ADD COLUMN auth TEXT NOT NULL DEFAULT 'local';      -- 'local' (senha) ou 'sso'
    ALTER TABLE users ADD COLUMN sso_subject TEXT;                        -- emissor|sub do provedor
    CREATE UNIQUE INDEX users_sso_subject ON users(sso_subject) WHERE sso_subject IS NOT NULL;
    CREATE TABLE sso_states (
        state        TEXT PRIMARY KEY,
        nonce        TEXT NOT NULL,
        verifier     TEXT NOT NULL,
        created      REAL NOT NULL
    );
    CREATE TABLE pb_versions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        pid          TEXT NOT NULL,
        version      TEXT NOT NULL,
        status       TEXT NOT NULL,
        created_at   TEXT NOT NULL,
        author       TEXT NOT NULL,
        author_name  TEXT NOT NULL,
        kind         TEXT NOT NULL,                   -- base, criacao, importacao, documento, fluxograma, ramo, status, restauracao
        note         TEXT NOT NULL DEFAULT '',
        md           TEXT NOT NULL,
        drawio       TEXT NOT NULL DEFAULT '',
        refs         TEXT NOT NULL DEFAULT '{}',
        template     TEXT
    );
    CREATE INDEX pb_versions_pid ON pb_versions(pid, id);
    """,
]


def _m4_roles(c):
    """v4: papéis personalizados. Só acrescenta (tabela roles, users.role_id, login_attempts.updated): a coluna
    users.role continua como espelho legado, então a versão 2.x ainda abre este banco (rollback)."""
    ts = now_iso()
    c.execute("""CREATE TABLE roles (
        key TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        system INTEGER NOT NULL DEFAULT 0, priority INTEGER NOT NULL DEFAULT 20,
        permissions TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    c.execute("ALTER TABLE users ADD COLUMN role_id TEXT")
    c.execute("UPDATE users SET role_id = role")            # viewer/editor/admin → mesmas chaves dos papéis semente
    c.execute("CREATE INDEX users_role_id ON users(role_id)")
    c.execute("ALTER TABLE login_attempts ADD COLUMN updated REAL NOT NULL DEFAULT 0")
    for r in perms.SEED_ROLES:
        c.execute("INSERT INTO roles VALUES (?,?,?,1,?,?,?,?)",
                  (r["key"], r["name"], r["description"], r["priority"], json.dumps(r["permissions"]), ts, ts))


MIGRATIONS.append(_m4_roles)


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class StoreError(ValueError):
    """Regra de negócio violada (vira HTTP 400)."""


class Store:
    def __init__(self, path, session_ttl=8 * 3600, max_fails=5, lock_seconds=300, session_max=24 * 3600):
        self.path = Path(path)
        self.ttl, self.max_fails, self.lock_seconds, self.session_max = session_ttl, max_fails, lock_seconds, session_max
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)           # pasta de dados só para o dono
        self._local = threading.local()
        self._sessions, self._sessions_lock = {}, threading.Lock()
        self._roles = None
        self._migrate()

    # ── conexão
    def _connect(self):
        c = sqlite3.connect(self.path, timeout=15, isolation_level=None)   # autocommit; transações explícitas
        c.row_factory = sqlite3.Row
        for pragma in ("foreign_keys = ON", "busy_timeout = 15000", "journal_mode = WAL", "synchronous = NORMAL",
                       "temp_store = MEMORY", "cache_size = -8000"):
            c.execute("PRAGMA " + pragma)
        return c

    def _conn(self):
        """Conexão desta thread (aberta na primeira vez; fecha sozinha quando a thread termina)."""
        c = getattr(self._local, "c", None)
        if c is None: c = self._local.c = self._connect()
        return c

    @contextmanager
    def _db(self):
        yield self._conn()

    @contextmanager
    def _tx(self):
        c = self._conn()
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise

    def _forget_sessions(self):
        with self._sessions_lock: self._sessions.clear()

    def _migrate(self):
        """Aplica as migrações pendentes, cada uma numa transação junto com o PRAGMA user_version (uma falha no meio
        não deixa o banco pela metade). Antes de migrar um banco existente, guarda uma cópia em data/backups/."""
        with closing(self._connect()) as c:
            v, n = c.execute("PRAGMA user_version").fetchone()[0], len(MIGRATIONS)
            if v >= n: return
            if v > 0:
                dest = self._backup_before_migration(c, v, n)
                sys.stderr.write(f"Migração do banco v{v} → v{n} (cópia anterior em {dest})\n")
            for i, m in enumerate(MIGRATIONS[v:], start=v + 1):
                if callable(m):
                    c.execute("BEGIN IMMEDIATE")
                    try:
                        m(c)
                        c.execute(f"PRAGMA user_version = {i}")
                        c.execute("COMMIT")
                    except BaseException:
                        c.execute("ROLLBACK")
                        raise
                else:
                    c.executescript("BEGIN;" + m + f"PRAGMA user_version = {i}; COMMIT;")

    def _backup_before_migration(self, c, v, n):
        d = self.path.parent / "backups"
        d.mkdir(exist_ok=True); os.chmod(d, 0o700)
        dest = d / f"{self.path.name}.pre-v{v}-v{n}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        dst = sqlite3.connect(dest)
        try: c.backup(dst)
        finally: dst.close()
        os.chmod(dest, 0o600)
        old = sorted(d.glob(f"{self.path.name}.pre-v*"), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in old[KEEP_DB_BACKUPS:]: f.unlink()
        return dest

    # ── papéis (cache em memória, recarregado a cada alteração)
    def roles(self):
        """{chave: papel} com "perms" (conjunto efetivo) e "permissions" (lista gravada)."""
        r = self._roles
        if r is None:
            with self._db() as c:
                rows = c.execute("SELECT * FROM roles ORDER BY priority DESC, name").fetchall()
            r = {}
            for row in rows:
                d = dict(row); d["system"] = bool(d["system"])
                d["permissions"] = json.loads(d["permissions"] or "[]"); d["perms"] = perms.expand(d["permissions"])
                r[d["key"]] = d
            self._roles = r
        return r

    def _roles_changed(self):
        self._roles = None
        self._forget_sessions()

    def role(self, key):
        return self.roles().get(key)

    def list_roles(self):
        with self._db() as c:
            used = dict(c.execute("SELECT COALESCE(role_id, role), COUNT(*) FROM users GROUP BY 1").fetchall())
        return [{**{k: v for k, v in r.items() if k != "perms"}, "users": used.get(r["key"], 0)} for r in self.roles().values()]

    def create_role(self, key, name, description, permissions, priority=20):
        ts = now_iso()
        try:
            with self._tx() as c:
                c.execute("INSERT INTO roles VALUES (?,?,?,0,?,?,?,?)", (key, name, description, int(priority), json.dumps(permissions), ts, ts))
        except sqlite3.IntegrityError:
            raise StoreError("Já existe um papel com essa chave")
        self._roles_changed()
        return self.role(key)

    def update_role(self, key, name=None, description=None, permissions=None, priority=None):
        if key == "admin": raise StoreError("O papel Administrador não pode ser alterado")
        if key not in self.roles(): raise StoreError("papel não encontrado")
        sets, args = ["updated_at = ?"], [now_iso()]
        for col, val in (("name", name), ("description", description), ("priority", priority),
                         ("permissions", None if permissions is None else json.dumps(permissions))):
            if val is not None: sets.append(f"{col} = ?"); args.append(val)
        with self._tx() as c:
            c.execute(f"UPDATE roles SET {', '.join(sets)} WHERE key = ?", (*args, key))
        self._roles_changed()
        return self.role(key)

    def reset_role(self, key):
        """Papel do sistema (Editor, Visualizador) volta às permissões padrão."""
        d = perms.DEFAULTS.get(key)
        if key == "admin" or not d: raise StoreError("Só os papéis Editor e Visualizador têm padrão para restaurar")
        return self.update_role(key, name=d["name"], description=d["description"], permissions=d["permissions"], priority=d["priority"])

    def delete_role(self, key, reassign=None):
        r = self.role(key)
        if not r: raise StoreError("papel não encontrado")
        if r["system"]: raise StoreError("Papéis do sistema não podem ser excluídos")
        if reassign is not None and (reassign == key or reassign not in self.roles()): raise StoreError("Papel de destino inválido")
        with self._tx() as c:
            n = c.execute("SELECT COUNT(*) FROM users WHERE COALESCE(role_id, role) = ?", (key,)).fetchone()[0]
            if n and reassign is None:
                raise StoreError(f"Papel em uso por {n} usuário(s): escolha para qual papel eles vão")
            if n:
                c.execute("UPDATE users SET role_id = ?, role = ?, updated_at = ? WHERE COALESCE(role_id, role) = ?",
                          (reassign, perms.legacy_role(reassign), now_iso(), key))
            c.execute("DELETE FROM roles WHERE key = ?", (key,))
        self._roles_changed()
        return n

    # ── usuários
    def _user(self, row):
        """Registro do usuário com o papel resolvido: role_id, role_name, priority e perms (conjunto efetivo).
        Papel inexistente (excluído por fora, ou usuário criado pela 2.x num rollback) → sem permissões."""
        if not row: return None
        d = dict(row)
        d["active"], d["must_change"] = bool(d["active"]), bool(d["must_change"])
        d["role_id"] = d.get("role_id") or d["role"]
        r = self.roles().get(d["role_id"])
        d["role_name"] = r["name"] if r else "(papel removido)"
        d["priority"] = r["priority"] if r else 0
        d["perms"] = r["perms"] if r else frozenset()
        return d

    def get_user(self, login):
        with self._db() as c:
            return self._user(c.execute("SELECT * FROM users WHERE login = ?", (login,)).fetchone())

    def list_users(self):
        with self._db() as c:
            rows = c.execute("""SELECT u.*, (SELECT COUNT(*) FROM sessions s WHERE s.login = u.login AND s.seen_at > ?) AS sessions
                                FROM users u ORDER BY u.login""", (time.time() - self.ttl,)).fetchall()
            return [self._user(r) for r in rows]

    def users_with_role(self, key):
        with self._db() as c:
            rows = c.execute("SELECT * FROM users WHERE COALESCE(role_id, role) = ? ORDER BY login", (key,)).fetchall()
            return [self._user(r) for r in rows]

    def approvers(self, perm):
        """Usuários ativos cujo papel tem a permissão (ex.: playbook.approve)."""
        with self._db() as c:
            rows = c.execute("SELECT * FROM users WHERE active = 1 ORDER BY name").fetchall()
        return [u for u in map(self._user, rows) if perm in u["perms"]]

    def count_active_admins(self, c=None):
        q = "SELECT COUNT(*) FROM users WHERE COALESCE(role_id, role) = 'admin' AND active = 1"
        if c: return c.execute(q).fetchone()[0]
        with self._db() as c2: return c2.execute(q).fetchone()[0]

    def create_user(self, login, name, role, pw_hash, must_change=True, auth="local", sso_subject=None):
        """role = chave do papel (role_id); a coluna antiga role recebe o espelho legado."""
        if role not in self.roles(): raise StoreError("papel inválido")
        ts = now_iso()
        try:
            with self._tx() as c:
                c.execute("""INSERT INTO users (login, name, role, role_id, hash, active, must_change, created_at, updated_at, auth, sso_subject)
                             VALUES (?,?,?,?,?,1,?,?,?,?,?)""",
                          (login, name, perms.legacy_role(role), role, pw_hash, int(must_change), ts, ts, auth, sso_subject))
        except sqlite3.IntegrityError:
            raise StoreError("Já existe um usuário com esse login")
        return self.get_user(login)

    def upsert_user(self, login, name, role, pw_hash):
        """Usado pela linha de comando: cria ou redefine (ativo, sem troca obrigatória)."""
        if role not in self.roles(): raise StoreError("papel inválido")
        ts = now_iso()
        with self._tx() as c:
            c.execute("""INSERT INTO users (login, name, role, role_id, hash, active, must_change, created_at, updated_at) VALUES (?,?,?,?,?,1,0,?,?)
                         ON CONFLICT(login) DO UPDATE SET name=excluded.name, role=excluded.role, role_id=excluded.role_id, hash=excluded.hash,
                         active=1, must_change=0, updated_at=excluded.updated_at""", (login, name, perms.legacy_role(role), role, pw_hash, ts, ts))
        self._forget_sessions()
        return self.get_user(login)

    def update_user(self, login, name=None, role=None, active=None, auth=None):
        with self._tx() as c:
            if not c.execute("SELECT 1 FROM users WHERE login = ?", (login,)).fetchone():
                raise StoreError("usuário não encontrado")
            if role is not None and role not in self.roles(): raise StoreError("papel inválido")
            if auth is not None and auth not in ("local", "sso"): raise StoreError("tipo de autenticação inválido")
            sets, args = ["updated_at = ?"], [now_iso()]
            for col, val in (("name", name), ("role_id", role), ("role", role and perms.legacy_role(role)),
                             ("active", None if active is None else int(bool(active))), ("auth", auth)):
                if val is not None: sets.append(f"{col} = ?"); args.append(val)
            c.execute(f"UPDATE users SET {', '.join(sets)} WHERE login = ?", (*args, login))
            if self.count_active_admins(c) < 1:
                raise StoreError("É preciso manter pelo menos um administrador ativo")   # rollback automático
            if active is False or auth is not None:
                c.execute("DELETE FROM sessions WHERE login = ?", (login,))
            if auth == "local":
                c.execute("UPDATE users SET sso_subject = NULL WHERE login = ?", (login,))
        self._forget_sessions()
        return self.get_user(login)

    def user_by_subject(self, subject):
        with self._db() as c:
            return self._user(c.execute("SELECT * FROM users WHERE sso_subject = ?", (subject,)).fetchone())

    def bind_subject(self, login, subject, name=None):
        with self._db() as c:
            c.execute("UPDATE users SET sso_subject = ?, name = COALESCE(?, name), updated_at = ? WHERE login = ?", (subject, name, now_iso(), login))
        self._forget_sessions()

    # ── SSO: estado do fluxo de login (state, nonce, PKCE), válido por 10 minutos
    def put_sso_state(self, state, nonce, verifier):
        with self._db() as c:
            c.execute("DELETE FROM sso_states WHERE created < ?", (time.time() - 600,))
            c.execute("INSERT INTO sso_states VALUES (?,?,?,?)", (state, nonce, verifier, time.time()))

    def pop_sso_state(self, state):
        with self._tx() as c:
            r = c.execute("SELECT * FROM sso_states WHERE state = ? AND created >= ?", (state, time.time() - 600)).fetchone()
            c.execute("DELETE FROM sso_states WHERE state = ?", (state,))
            return dict(r) if r else None

    def delete_user(self, login):
        with self._tx() as c:
            if not c.execute("DELETE FROM users WHERE login = ?", (login,)).rowcount:
                raise StoreError("usuário não encontrado")
            if self.count_active_admins(c) < 1:
                raise StoreError("É preciso manter pelo menos um administrador ativo")
        self._forget_sessions()

    def set_password(self, login, pw_hash, must_change, keep_token=None):
        """Troca a senha e encerra as outras sessões do usuário (todas, se keep_token for None)."""
        with self._tx() as c:
            c.execute("UPDATE users SET hash = ?, must_change = ?, updated_at = ? WHERE login = ?", (pw_hash, int(must_change), now_iso(), login))
            if keep_token:
                c.execute("DELETE FROM sessions WHERE login = ? AND token_hash <> ?", (login, token_hash(keep_token)))
            else:
                c.execute("DELETE FROM sessions WHERE login = ?", (login,))
        self._forget_sessions()

    # ── sessões
    def create_session(self, login, ip, user_agent):
        token = secrets.token_urlsafe(32)
        t = time.time()
        with self._tx() as c:
            c.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)", (token_hash(token), login, t, t, ip, (user_agent or "")[:200]))
            c.execute("UPDATE users SET last_login = ? WHERE login = ?", (now_iso(), login))
            c.execute("DELETE FROM sessions WHERE seen_at < ?", (t - self.ttl,))          # limpeza oportunista
        return token

    def session_user(self, token):
        """Usuário da sessão, se válida e ativa. Atualiza o 'visto por último' no máximo 1x por minuto.
        A resposta fica 15 s em memória por token (cada requisição não precisa ir ao banco)."""
        if not token: return None
        th, t = token_hash(token), time.time()
        with self._sessions_lock:
            hit = self._sessions.get(th)
        if hit and hit[1] > t: return dict(hit[0])
        with self._db() as c:
            r = c.execute("""SELECT s.seen_at, s.created_at AS session_created, u.* FROM sessions s JOIN users u ON u.login = s.login
                             WHERE s.token_hash = ?""", (th,)).fetchone()
            if not r: return None
            if t - r["seen_at"] > self.ttl or t - r["session_created"] > self.session_max or not r["active"]:
                c.execute("DELETE FROM sessions WHERE token_hash = ?", (th,)); return None
            if t - r["seen_at"] > 60:
                c.execute("UPDATE sessions SET seen_at = ? WHERE token_hash = ?", (t, th))
            d = self._user(r); d.pop("seen_at", None)
        with self._sessions_lock:
            if len(self._sessions) > 5000: self._sessions.clear()
            # nunca guarda além do vencimento da própria sessão
            self._sessions[th] = (d, min(t + SESSION_CACHE_TTL, d["session_created"] + self.session_max))
        return dict(d)

    def delete_session(self, token):
        with self._db() as c:
            r = c.execute("SELECT login FROM sessions WHERE token_hash = ?", (token_hash(token),)).fetchone()
            c.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
        self._forget_sessions()
        return r["login"] if r else None

    def delete_user_sessions(self, login):
        with self._db() as c:
            n = c.execute("DELETE FROM sessions WHERE login = ?", (login,)).rowcount
        self._forget_sessions()
        return n

    # ── tentativas de login
    def locked_for(self, key):
        with self._db() as c:
            r = c.execute("SELECT locked_until FROM login_attempts WHERE key = ?", (key,)).fetchone()
            return max(0, r["locked_until"] - time.time()) if r else 0

    def register_fail(self, key):
        with self._tx() as c:
            c.execute("""INSERT INTO login_attempts (key, fails, updated) VALUES (?, 1, ?)
                         ON CONFLICT(key) DO UPDATE SET fails = fails + 1, updated = excluded.updated""", (key, time.time()))
            if c.execute("SELECT fails FROM login_attempts WHERE key = ?", (key,)).fetchone()[0] >= self.max_fails:
                c.execute("UPDATE login_attempts SET fails = 0, locked_until = ? WHERE key = ?", (time.time() + self.lock_seconds, key))

    def clear_fails(self, key):
        with self._db() as c:
            c.execute("DELETE FROM login_attempts WHERE key = ?", (key,))

    # ── auditoria
    def audit(self, user, action, target="", **detail):
        with self._db() as c:
            c.execute("INSERT INTO audit (ts, user, action, target, detail) VALUES (?,?,?,?,?)",
                      (now_iso(), user, action, target or "", json.dumps(detail, ensure_ascii=False)))

    def purge(self, audit_days):
        """Retenção: apaga auditoria mais antiga que audit_days, estados de SSO vencidos e bloqueios expirados."""
        cutoff = datetime.fromtimestamp(time.time() - audit_days * 86400).isoformat(timespec="seconds")
        with self._db() as c:
            n = c.execute("DELETE FROM audit WHERE ts < ?", (cutoff,)).rowcount
            c.execute("DELETE FROM sso_states WHERE created < ?", (time.time() - 600,))
            c.execute("DELETE FROM login_attempts WHERE locked_until < ? AND fails = 0", (time.time(),))
            # falhas soltas (sem bloqueio) sem atividade há mais de 1 h
            c.execute("DELETE FROM login_attempts WHERE locked_until < ? AND updated < ?", (time.time(), time.time() - 3600))
            if c.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0] > MAX_LOGIN_ATTEMPTS_ROWS:
                c.execute("DELETE FROM login_attempts WHERE locked_until = 0")
            c.execute("DELETE FROM sessions WHERE seen_at < ?", (time.time() - self.ttl,))
        return n

    def audit_since(self, days):
        cutoff = datetime.fromtimestamp(time.time() - days * 86400).isoformat(timespec="seconds")
        with self._db() as c:
            for r in c.execute("SELECT * FROM audit WHERE ts >= ? ORDER BY id", (cutoff,)):
                d = dict(r); d["detail"] = json.loads(d["detail"] or "{}")
                yield d

    # ── versões dos playbooks
    def add_version(self, pid, version, status, author, author_name, kind, note, md, drawio, refs, template=None):
        with self._db() as c:
            return c.execute("""INSERT INTO pb_versions (pid, version, status, created_at, author, author_name, kind, note, md, drawio, refs, template)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (pid, version, status, now_iso(), author, author_name, kind, note[:500], md, drawio,
                              json.dumps(refs, ensure_ascii=False), template)).lastrowid

    def list_versions(self, pid):
        with self._db() as c:
            return [dict(r) for r in c.execute("""SELECT id, pid, version, status, created_at, author, author_name, kind, note, template
                                                  FROM pb_versions WHERE pid = ? ORDER BY id DESC""", (pid,))]

    def get_version(self, pid, vid):
        with self._db() as c:
            r = c.execute("SELECT * FROM pb_versions WHERE pid = ? AND id = ?", (pid, vid)).fetchone()
            if not r: return None
            d = dict(r); d["refs"] = json.loads(d["refs"] or "{}")
            return d

    def last_content_version(self, pid, kinds):
        """Última versão de conteúdo (não de status) do documento: quem a gravou não pode aprovar a publicação."""
        with self._db() as c:
            r = c.execute(f"""SELECT author, author_name, kind, created_at FROM pb_versions
                              WHERE pid = ? AND kind IN ({",".join("?" * len(kinds))}) ORDER BY id DESC LIMIT 1""", (pid, *kinds)).fetchone()
            return dict(r) if r else None

    def count_versions(self, pid):
        with self._db() as c:
            return c.execute("SELECT COUNT(*) FROM pb_versions WHERE pid = ?", (pid,)).fetchone()[0]

    def archive_versions(self, pid, suffix):
        """Playbook excluído ou substituído: o histórico fica guardado sob outro identificador (PB-02#lixeira…)."""
        with self._db() as c:
            c.execute("UPDATE pb_versions SET pid = ? WHERE pid = ?", (f"{pid}#{suffix}", pid))

    def count_all_versions(self):
        with self._db() as c:
            return c.execute("SELECT COUNT(*) FROM pb_versions").fetchone()[0]

    def count_audit(self):
        with self._db() as c:
            return c.execute("SELECT COUNT(*) FROM audit").fetchone()[0]

    # ── reset da aplicação
    def backup_to(self, path):
        """Cópia consistente do banco (API de backup do SQLite), mesmo com o servidor em uso."""
        dst = sqlite3.connect(path)
        try:
            with closing(self._connect()) as c: c.backup(dst)
        finally:
            dst.close()
        os.chmod(path, 0o600)

    def reset(self, keep_login, settings=False, users=False, audit=False):
        """Apaga o histórico de versões e os vínculos playbook→template; opcionalmente configurações
        (aparência, logs, SSO), os demais usuários e a auditoria. Quem fez o reset continua com a sessão."""
        with self._tx() as c:
            c.execute("DELETE FROM pb_versions")
            c.execute("DELETE FROM sso_states")
            if settings: c.execute("DELETE FROM settings")
            else: c.execute("DELETE FROM settings WHERE key = 'pb_templates'")
            if users:
                c.execute("DELETE FROM sessions WHERE login <> ?", (keep_login,))
                c.execute("DELETE FROM users WHERE login <> ?", (keep_login,))
                c.execute("DELETE FROM login_attempts")
            if audit: c.execute("DELETE FROM audit")
        self._forget_sessions()

    def read_audit(self, limit=500, q=""):
        sql, args = "SELECT * FROM audit", []
        if q:
            sql += " WHERE user LIKE ? OR action LIKE ? OR target LIKE ? OR detail LIKE ?"
            args = [f"%{q}%"] * 4
        sql += " ORDER BY id DESC LIMIT ?"
        with self._db() as c:
            out = []
            for r in c.execute(sql, (*args, int(limit))).fetchall():
                d = dict(r); d.update(json.loads(d.pop("detail") or "{}")); d.pop("id", None)
                out.append(d)
            return out

    # ── configurações
    def get_setting(self, key, default=None):
        with self._db() as c:
            r = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return json.loads(r["value"]) if r else default

    def set_setting(self, key, value, by=None):
        with self._db() as c:
            if value is None:
                c.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                c.execute("""INSERT INTO settings (key, value, updated_at, updated_by) VALUES (?,?,?,?)
                             ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at, updated_by = excluded.updated_by""",
                          (key, json.dumps(value, ensure_ascii=False), now_iso(), by))

    # ── migração do formato antigo (users.json / audit.log)
    def import_legacy(self, users_json, audit_log):
        done = []
        if users_json.exists() and not self.list_users():
            users = json.loads(users_json.read_text("utf-8")).get("users", {})
            ts = now_iso()
            with self._tx() as c:
                for login, u in users.items():
                    c.execute("""INSERT OR IGNORE INTO users (login, name, role, hash, active, must_change, created_at, updated_at, last_login)
                                 VALUES (?,?,?,?,?,?,?,?,?)""",
                              (login, u.get("name") or login, u["role"], u["hash"], int(u.get("active", True)), int(u.get("must_change", False)),
                               u.get("created") or ts, ts, u.get("last_login")))
            users_json.rename(users_json.with_suffix(".json.migrado"))
            done.append(f"{len(users)} usuário(s)")
        if audit_log.exists():
            n = 0
            with self._tx() as c:
                for line in audit_log.read_text("utf-8").splitlines():
                    if not line.strip(): continue
                    e = json.loads(line)
                    c.execute("INSERT INTO audit (ts, user, action, target, detail) VALUES (?,?,?,?,?)",
                              (e.pop("ts"), e.pop("user"), e.pop("action"), e.pop("target", ""), json.dumps(e, ensure_ascii=False)))
                    n += 1
            audit_log.rename(audit_log.with_suffix(".log.migrado"))
            done.append(f"{n} evento(s) de auditoria")
        return done
