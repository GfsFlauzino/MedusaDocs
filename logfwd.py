"""Encaminhamento dos logs de auditoria em JSON e retenção.

Cada evento de auditoria vira um documento JSON (campos no estilo Elastic Common Schema) e é enviado, em
segundo plano, para os destinos ligados no painel (Administração → Logs):

  http    POST para uma URL (SIEM, coletor, webhook): um array JSON por lote, com cabeçalho de autenticação opcional
  syslog  RFC 5424 por UDP ou TCP, com o JSON na mensagem
  file    arquivo JSON Lines por dia em data/logs/ (para agentes como Filebeat, Fluent Bit, Splunk UF)

A fila é limitada e não bloqueia as requisições: se o destino cair, o envio é tentado de novo algumas vezes
e o status fica visível no painel. A retenção apaga auditoria e arquivos de log mais antigos que N dias.
"""
import json, os, queue, socket, ssl, threading, time, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path

APP_TYPE = "medusa-docs"
DEFAULT = {"retention_days": 30,
           "http": {"enabled": False, "url": "", "auth_header": "Authorization", "auth_value": ""},
           "syslog": {"enabled": False, "host": "", "port": 514, "proto": "udp", "facility": 16},
           "file": {"enabled": False}}
MAX_QUEUE, BATCH, RETRIES = 10000, 200, 3
FAIL_ACTIONS = ("_falhou", "_negado")


def merge(cfg):
    out = json.loads(json.dumps(DEFAULT))
    for k, v in (cfg or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict): out[k].update(v)
        else: out[k] = v
    return out


def category(action):
    if action.startswith(("login", "logout", "sso_", "senha")): return ["authentication"]
    if action.startswith(("usuario", "sessoes", "admin_inicial")): return ["iam"]
    if action.endswith(("exportado", "exportados")): return ["file"]
    return ["configuration"]


def make_event(ts, user, action, target, detail, ip, service, version):
    """ts: datetime local. Retorna o documento JSON enviado aos destinos."""
    d = dict(detail or {})
    ev = {
        "@timestamp": ts.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "event": {"kind": "event", "dataset": "medusa.audit", "action": action, "category": category(action),
                  "outcome": "failure" if action.endswith(FAIL_ACTIONS) else "success"},
        "user": {"name": user},
        "medusa": {"target": target or "", "detail": d},
        "service": {"name": service, "type": APP_TYPE, "version": version},
        "host": {"hostname": socket.gethostname()},
    }
    if ip: ev["source"] = {"ip": ip}
    return ev


class Forwarder:
    def __init__(self, get_cfg, log_dir):
        self.get_cfg, self.log_dir = get_cfg, Path(log_dir)
        self.q = queue.Queue(MAX_QUEUE)
        self.stats = {d: {"sent": 0, "failed": 0, "last_ok": None, "last_error": None} for d in ("http", "syslog", "file")}
        self.dropped = 0
        self._lock = threading.Lock()
        threading.Thread(target=self._run, name="log-forwarder", daemon=True).start()

    # ── entrada
    def enqueue(self, ev):
        cfg = merge(self.get_cfg())
        if not any(cfg[d]["enabled"] for d in ("http", "syslog", "file")): return
        try: self.q.put_nowait(ev)
        except queue.Full: self.dropped += 1

    def status(self):
        return {"queue": self.q.qsize(), "dropped": self.dropped, "destinations": self.stats}

    # ── laço de envio
    def _run(self):
        while True:
            batch = [self.q.get()]
            while len(batch) < BATCH:
                try: batch.append(self.q.get_nowait())
                except queue.Empty: break
            cfg = merge(self.get_cfg())
            for dest, fn in (("file", self._file), ("syslog", self._syslog), ("http", self._http)):
                if not cfg[dest]["enabled"]: continue
                for attempt in range(RETRIES):
                    try:
                        fn(cfg[dest], batch)
                        self._ok(dest, len(batch)); break
                    except Exception as e:  # destino fora do ar, recusou ou deu timeout
                        if attempt == RETRIES - 1: self._fail(dest, len(batch), e)
                        else: time.sleep(2 ** attempt)

    def _ok(self, dest, n):
        with self._lock:
            s = self.stats[dest]; s["sent"] += n; s["last_ok"] = datetime.now().isoformat(timespec="seconds")

    def _fail(self, dest, n, e):
        with self._lock:
            s = self.stats[dest]; s["failed"] += n
            s["last_error"] = f"{datetime.now().isoformat(timespec='seconds')} · {type(e).__name__}: {str(e)[:200]}"

    # ── destinos
    @staticmethod
    def _http(c, batch, timeout=10):
        url = str(c.get("url", ""))
        if not url.lower().startswith(("https://", "http://")): raise ValueError("URL precisa começar com http:// ou https://")
        headers = {"Content-Type": "application/json", "User-Agent": f"{APP_TYPE}/log-forwarder"}
        if c.get("auth_header") and c.get("auth_value"): headers[str(c["auth_header"])] = str(c["auth_value"])
        req = urllib.request.Request(url, data=json.dumps(batch, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            if r.status >= 300: raise urllib.error.HTTPError(url, r.status, "resposta inesperada", r.headers, None)

    @staticmethod
    def _syslog(c, batch, timeout=5):
        host, port = str(c.get("host", "")).strip(), int(c.get("port") or 514)
        if not host: raise ValueError("informe o host do syslog")
        pri = int(c.get("facility", 16)) * 8 + 6           # severidade informational
        hn = socket.gethostname()
        msgs = [f"<{pri}>1 {ev['@timestamp']} {hn} {APP_TYPE} - {ev['event']['action']} - {json.dumps(ev, ensure_ascii=False)}".encode("utf-8")
                for ev in batch]
        if c.get("proto") == "tcp":
            with socket.create_connection((host, port), timeout=timeout) as s:
                for m in msgs: s.sendall(f"{len(m)} ".encode() + m)      # octet counting (RFC 6587)
        else:
            with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(timeout)
                for m in msgs: s.sendto(m[:65000], (host, port))

    def _file(self, c, batch):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        f = self.log_dir / f"audit-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        with open(f, "a", encoding="utf-8") as fh:
            for ev in batch: fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        os.chmod(f, 0o640)

    # ── teste a partir do painel (síncrono, com a configuração ainda não salva)
    def test(self, cfg, dest, ev):
        cfg = merge(cfg)
        try:
            {"http": lambda: self._http(cfg["http"], [ev], timeout=8), "syslog": lambda: self._syslog(cfg["syslog"], [ev]),
             "file": lambda: self._file(cfg["file"], [ev])}[dest]()
            return {"ok": True, "message": "Evento de teste enviado"}
        except urllib.error.HTTPError as e:
            return {"ok": False, "message": f"O destino respondeu HTTP {e.code}"}
        except Exception as e:
            return {"ok": False, "message": f"{type(e).__name__}: {str(e)[:200]}"}

    def purge_files(self, days):
        if not self.log_dir.exists(): return 0
        cutoff, n = time.time() - days * 86400, 0
        for f in self.log_dir.glob("audit-*.jsonl"):
            if f.stat().st_mtime < cutoff: f.unlink(); n += 1
        return n
