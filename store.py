"""Banco de dados da ferramenta (SQLite, embutido no Python): usuários, sessões, tentativas de login e auditoria.

Arquivo único: data/playbooks.db. Cada operação abre a própria conexão (seguro com o servidor multithread);
operações que precisam de várias leituras e escritas usam transação BEGIN IMMEDIATE.
O esquema é versionado por PRAGMA user_version; novas versões entram em MIGRATIONS.
"""
import hashlib, json, os, secrets, sqlite3, time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROLES = ("viewer", "editor", "admin")

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
]


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class StoreError(ValueError):
    """Regra de negócio violada (vira HTTP 400)."""


class Store:
    def __init__(self, path, session_ttl=8 * 3600, max_fails=5, lock_seconds=300):
        self.path = Path(path)
        self.ttl, self.max_fails, self.lock_seconds = session_ttl, max_fails, lock_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)           # pasta de dados só para o dono
        self._migrate()

    # ── conexão
    def _connect(self):
        c = sqlite3.connect(self.path, timeout=15, isolation_level=None)   # autocommit; transações explícitas
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("PRAGMA busy_timeout = 15000")
        return c

    @contextmanager
    def _db(self):
        c = self._connect()
        try:
            yield c
        finally:
            c.close()

    @contextmanager
    def _tx(self):
        c = self._connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    def _migrate(self):
        with self._db() as c:
            c.execute("PRAGMA journal_mode = WAL")
            v = c.execute("PRAGMA user_version").fetchone()[0]
            for i, sql in enumerate(MIGRATIONS[v:], start=v + 1):
                c.executescript("BEGIN;" + sql + f"PRAGMA user_version = {i}; COMMIT;")

    # ── usuários
    @staticmethod
    def _user(row):
        if not row: return None
        d = dict(row)
        d["active"], d["must_change"] = bool(d["active"]), bool(d["must_change"])
        return d

    def get_user(self, login):
        with self._db() as c:
            return self._user(c.execute("SELECT * FROM users WHERE login = ?", (login,)).fetchone())

    def list_users(self):
        with self._db() as c:
            rows = c.execute("""SELECT u.*, (SELECT COUNT(*) FROM sessions s WHERE s.login = u.login AND s.seen_at > ?) AS sessions
                                FROM users u ORDER BY u.login""", (time.time() - self.ttl,)).fetchall()
            return [self._user(r) for r in rows]

    def approvers(self):
        with self._db() as c:
            return [dict(r) for r in c.execute(
                "SELECT login, name, role FROM users WHERE active = 1 AND role IN ('editor','admin') ORDER BY name").fetchall()]

    def count_active_admins(self, c=None):
        q = "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1"
        if c: return c.execute(q).fetchone()[0]
        with self._db() as c2: return c2.execute(q).fetchone()[0]

    def create_user(self, login, name, role, pw_hash, must_change=True):
        if role not in ROLES: raise StoreError("perfil inválido")
        ts = now_iso()
        try:
            with self._tx() as c:
                c.execute("INSERT INTO users (login, name, role, hash, active, must_change, created_at, updated_at) VALUES (?,?,?,?,1,?,?,?)",
                          (login, name, role, pw_hash, int(must_change), ts, ts))
        except sqlite3.IntegrityError:
            raise StoreError("Já existe um usuário com esse login")
        return self.get_user(login)

    def upsert_user(self, login, name, role, pw_hash):
        """Usado pela linha de comando: cria ou redefine (ativo, sem troca obrigatória)."""
        ts = now_iso()
        with self._tx() as c:
            c.execute("""INSERT INTO users (login, name, role, hash, active, must_change, created_at, updated_at) VALUES (?,?,?,?,1,0,?,?)
                         ON CONFLICT(login) DO UPDATE SET name=excluded.name, role=excluded.role, hash=excluded.hash,
                         active=1, must_change=0, updated_at=excluded.updated_at""", (login, name, role, pw_hash, ts, ts))
        return self.get_user(login)

    def update_user(self, login, name=None, role=None, active=None):
        with self._tx() as c:
            if not c.execute("SELECT 1 FROM users WHERE login = ?", (login,)).fetchone():
                raise StoreError("usuário não encontrado")
            if role is not None and role not in ROLES: raise StoreError("perfil inválido")
            sets, args = ["updated_at = ?"], [now_iso()]
            for col, val in (("name", name), ("role", role), ("active", None if active is None else int(bool(active)))):
                if val is not None: sets.append(f"{col} = ?"); args.append(val)
            c.execute(f"UPDATE users SET {', '.join(sets)} WHERE login = ?", (*args, login))
            if self.count_active_admins(c) < 1:
                raise StoreError("É preciso manter pelo menos um administrador ativo")   # rollback automático
            if active is False:
                c.execute("DELETE FROM sessions WHERE login = ?", (login,))
        return self.get_user(login)

    def delete_user(self, login):
        with self._tx() as c:
            if not c.execute("DELETE FROM users WHERE login = ?", (login,)).rowcount:
                raise StoreError("usuário não encontrado")
            if self.count_active_admins(c) < 1:
                raise StoreError("É preciso manter pelo menos um administrador ativo")

    def set_password(self, login, pw_hash, must_change, keep_token=None):
        """Troca a senha e encerra as outras sessões do usuário (todas, se keep_token for None)."""
        with self._tx() as c:
            c.execute("UPDATE users SET hash = ?, must_change = ?, updated_at = ? WHERE login = ?", (pw_hash, int(must_change), now_iso(), login))
            if keep_token:
                c.execute("DELETE FROM sessions WHERE login = ? AND token_hash <> ?", (login, token_hash(keep_token)))
            else:
                c.execute("DELETE FROM sessions WHERE login = ?", (login,))

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
        """Usuário da sessão, se válida e ativa. Atualiza o 'visto por último' no máximo 1x por minuto."""
        if not token: return None
        th, t = token_hash(token), time.time()
        with self._db() as c:
            r = c.execute("""SELECT s.seen_at, u.* FROM sessions s JOIN users u ON u.login = s.login
                             WHERE s.token_hash = ?""", (th,)).fetchone()
            if not r: return None
            if t - r["seen_at"] > self.ttl or not r["active"]:
                c.execute("DELETE FROM sessions WHERE token_hash = ?", (th,)); return None
            if t - r["seen_at"] > 60:
                c.execute("UPDATE sessions SET seen_at = ? WHERE token_hash = ?", (t, th))
            d = self._user(r); d.pop("seen_at", None)
            return d

    def delete_session(self, token):
        with self._db() as c:
            r = c.execute("SELECT login FROM sessions WHERE token_hash = ?", (token_hash(token),)).fetchone()
            c.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
            return r["login"] if r else None

    def delete_user_sessions(self, login):
        with self._db() as c:
            return c.execute("DELETE FROM sessions WHERE login = ?", (login,)).rowcount

    # ── tentativas de login
    def locked_for(self, key):
        with self._db() as c:
            r = c.execute("SELECT locked_until FROM login_attempts WHERE key = ?", (key,)).fetchone()
            return max(0, r["locked_until"] - time.time()) if r else 0

    def register_fail(self, key):
        with self._tx() as c:
            c.execute("INSERT INTO login_attempts (key, fails) VALUES (?, 1) ON CONFLICT(key) DO UPDATE SET fails = fails + 1", (key,))
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
                    c.execute("INSERT OR IGNORE INTO users VALUES (?,?,?,?,?,?,?,?,?)",
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
