"""Cache do conteúdo dos documentos (playbooks): cada arquivo é interpretado uma vez e só volta a ser lido
quando a assinatura muda.

Assinatura de um documento: (mtime_ns e tamanho do .md, mtime_ns e tamanho do .drawio, hash dos vínculos
"ao clicar" dele no mappings.json, template vinculado e mtime_ns/tamanho do arquivo do template).
A varredura da pasta (os.scandir + stat) roda no máximo 1x por segundo, então uma edição feita por fora da
aplicação aparece em até ~1 s. Toda gravação feita pela aplicação chama invalidate(), que vale na hora.

O que fica sempre em memória por documento: o resumo (lista da home) e os textos normalizados da busca.
A visão completa (o que GET /api/pb/{id} devolve) fica num LRU de 256 entradas e é refeita sob demanda.
As estruturas devolvidas são compartilhadas: quem chama não pode alterá-las.

Resumos e textos de busca também são gravados em data/cache/biblioteca.json: depois de reiniciar, os
documentos cuja assinatura não mudou não precisam ser interpretados de novo (o boot fica instantâneo).
"""
import hashlib, json, os, re, sys, threading, time

import doctypes as DT, unicodedata
from collections import OrderedDict
from pathlib import Path

PID_RE = re.compile(r"^((?:PB|RB|DOC)-\d+)-")
SCAN_EVERY = 1.0
VIEW_CACHE = 256
PERSIST_FORMAT = 4              # 3: + documentos citados (links); 4: + times do fluxograma e tática MITRE
PERSIST_EVERY = 30              # segundos entre gravações do cache em disco (só se algo mudou)


def norm(s):
    """Texto para busca: sem acento, minúsculo, espaços simples."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())


def stable_hash(obj):
    """Hash que não muda entre execuções (o hash() do Python muda): vai para o cache em disco."""
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def tup(x):
    return tuple(tup(i) for i in x) if isinstance(x, (list, tuple)) else x


def strip_html(h):
    return re.sub(r"<[^>]+>", " ", h or "")


MENTION_RE = re.compile(r"(?<![\w-])((?:PB|RB|DOC)-\d{2,4})(?!\w)")


class Entry:
    __slots__ = ("pid", "type", "sig", "summary", "search_docs", "links")

    def __init__(self, pid, sig, summary, search_docs, links=()):
        self.pid, self.type, self.sig, self.summary, self.search_docs = pid, DT.type_of(pid) or "playbook", sig, summary, search_docs
        self.links = tuple(links)                       # IDs de outros documentos citados (texto e caixas do fluxograma)


def links_of(v):
    """Documentos citados: PB-00, RB-00 e DOC-00 no texto (introdução, seções) e nas caixas do fluxograma."""
    parts = [v.get("intro") or ""]
    for s in v["sections"]:
        parts.append(s["html"]); parts += [x["html"] for x in s["subs"]]
    parts += [l.get("t", "") for n in v["flow"].get("nodes", []) for l in n.get("lines", [])]
    return sorted({m for m in MENTION_RE.findall(" ".join(parts)) if m != v["id"]}, key=DT.sort_key)


def summary_of(v, fields_schema=None, core=None):
    g = v["gov"]
    props = v.get("props", {})
    t = v.get("type") or "playbook"
    fields = core.get_fields(v["doc"], fields_schema, DT.info(t)["props_title"]) if fields_schema and core else {}
    return {"id": v["id"], "type": t, "slug": v["slug"], "name": v["name"], "status": g["status"], "fields": fields,
            "hasFlow": bool(v.get("hasFlow", True)),
            "version": (props.get("Versão") or "").split(" ")[0], "templateKey": v.get("templateKey"), "templateName": v.get("templateName"),
            "reviewed": g.get("reviewed", ""), "reviewer": g.get("reviewer", ""), "approver": g.get("approver", ""),
            "gov": g, "ramos": len(v["ramos"]), "steps": len(v["steps"]), "rev": v.get("rev"),
            "subtitle": props.get("Tática MITRE principal") or props.get("Fase NIST") or "",
            "mitre": props.get("Tática MITRE principal") or "", "teams": teams_of(v)}


def teams_of(v):
    """Times (raias de time) que têm ao menos uma caixa no fluxograma, na ordem das raias: a pista do cartão na biblioteca."""
    flow = v.get("flow") or {}
    used = {n.get("lane") for n in flow.get("nodes", [])}
    return [{"name": l.get("team") or l.get("label"), "color": l.get("color")}
            for l in flow.get("lanes", []) if l.get("kind") == "team" and l.get("key") in used]


def search_docs_of(v):
    """(tipo, título, âncora, título normalizado, texto normalizado) — o que a busca percorre."""
    out = [("documento", f"{v['id']} · {v['name']}", None, norm(f"{v['id']} {v['name']}"), norm(v["title"]))]
    for s in v["steps"]:
        t = f"{s['id']} · {s['action']}"
        out.append(("passo", t, s["id"], norm(t), norm(f"{s['id']} {s['action']} {s['exit']}")))
    for r in v["ramos"]:
        out.append(("ramo", r["title"], r["id"], norm(r["title"]), norm(r["title"] + " " + strip_html(r["html"]))))
    for s in v["sections"]:
        body = s["title"] + " " + strip_html(s["html"]) + " " + " ".join(x["title"] + " " + strip_html(x["html"]) for x in s["subs"])
        out.append(("secao", s["title"], "sec-" + s["id"], norm(s["title"]), norm(body)))
    return out


class Library:
    def __init__(self, core, tpl, links, template_of, cache_file=None):
        """links() → {pid: chave do template}; template_of(pid, links) → chave válida (ou a do Padrão)."""
        self.core, self.tpl, self.links, self.template_of = core, tpl, links, template_of
        self.cache_file = Path(cache_file) if cache_file else None
        self._persisted, self._persisted_gen = {}, None
        self._lock = threading.RLock()
        self._pid_locks = {}
        self._entries = {}                 # pid → Entry
        self._found = {}                   # pid → (pasta, assinatura atual)
        self._views = OrderedDict()        # pid → (assinatura, visão) — LRU
        self._scanned = 0.0
        self._maps = (None, {}, {})        # (assinatura do mappings.json, conteúdo, hash por pid)
        self.generation = 0                # muda quando qualquer documento muda (ETag das listas)
        self.ready, self._warming = threading.Event(), False

    # ── varredura
    def _mappings(self):
        f = self.core.MAPPINGS_FILE
        try:
            st = os.stat(f); sig = (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            sig = None
        if sig != self._maps[0]:
            data = self.core.read_json(f, {}) if sig else {}
            self._maps = (sig, data, {pid: stable_hash(v) for pid, v in data.items()})
        return self._maps

    @staticmethod
    def _files(folder):
        """Mesma regra de pbcore.files_of: o primeiro .md e o primeiro .drawio em ordem alfabética."""
        md = dio = None
        for e in sorted(os.scandir(folder), key=lambda e: e.name):
            if md is None and e.name.endswith(".md") and e.is_file(): md = e
            elif dio is None and e.name.endswith(".drawio") and e.is_file(): dio = e
        st = lambda e: (e.stat().st_mtime_ns, e.stat().st_size) if e else None
        return st(md), st(dio)

    def scan(self, force=False):
        with self._lock:
            now = time.monotonic()
            if not force and now - self._scanned < SCAN_EVERY: return
            self._scanned = now
            dirs = []
            for t in DT.TYPES:
                try: dirs += [e for e in os.scandir(DT.src_dir(t)) if e.is_dir() and e.name.startswith(DT.TYPES[t]["prefix"] + "-")]
                except FileNotFoundError: pass
            dirs.sort(key=lambda e: e.name)
            _, _, hashes = self._mappings()
            lk = self.links()
            tsigs, found = {}, {}
            for d in dirs:
                m = PID_RE.match(d.name)
                if not m or m.group(1) in found or not self.core.ID_RE.fullmatch(m.group(1)): continue
                pid = m.group(1)
                try: md, dio = self._files(d.path)
                except OSError: continue
                if not md: continue
                key = self.template_of(pid, lk)
                if key not in tsigs: tsigs[key] = self.tpl.file_sig(key)
                found[pid] = (Path(d.path), (md, dio, hashes.get(pid), key, tsigs[key]))
            changed = set(found) ^ set(self._found) or any(self._found[p][1] != found[p][1] for p in found)
            for pid in set(self._entries) - set(found): self._entries.pop(pid, None); self._views.pop(pid, None)
            self._found = found
            if changed: self.generation += 1

    def invalidate(self, pid=None):
        """Chamado por toda gravação feita pela aplicação (dentro do LOCK do servidor, depois de gravar)."""
        with self._lock:
            if pid is None: self._entries.clear(); self._views.clear()
            else: self._entries.pop(pid, None); self._views.pop(pid, None)
            self._scanned = 0.0
            self.generation += 1

    # ── documentos
    def _pid_lock(self, pid):
        with self._lock:
            return self._pid_locks.setdefault(pid, threading.Lock())

    def _build(self, pid, folder, sig):
        key = sig[3]
        teams = self.tpl.teams_for(key)
        v = self.core.load_playbook(folder, teams)
        v.update(templateKey=key, templateName=self.tpl.name_for(key), teams=teams)
        return v

    def _load(self, pid):
        """(Entry, visão recém-montada ou None) — reinterpreta só se a assinatura mudou."""
        self.scan()
        with self._lock:
            f = self._found.get(pid)
            e = self._entries.get(pid)
            if not f: return None, None
            if e and e.sig == f[1]: return e, None
        with self._pid_lock(pid):              # uma thread interpreta; as outras esperam e reaproveitam
            with self._lock:
                f = self._found.get(pid)
                e = self._entries.get(pid)
                if not f: return None, None
                if e and e.sig == f[1]: return e, None
            folder, sig = f
            p = self._persisted.pop(pid, None)
            if p and tup(p["sig"]) == sig:            # mesmo arquivo de antes do reinício: não precisa interpretar
                e = Entry(pid, sig, p["summary"], [tuple(d) for d in p["search"]], p.get("links", []))
                with self._lock:
                    if self._found.get(pid, (None, None))[1] == sig: self._entries[pid] = e
                return e, None
            v = self._build(pid, folder, sig)
            e = Entry(pid, sig, summary_of(v, self.tpl.fields_for(sig[3]), self.core), search_docs_of(v), links_of(v))
            with self._lock:
                if self._found.get(pid, (None, None))[1] == sig:
                    self._entries[pid] = e
                    self._remember(pid, sig, v)
            return e, v

    def _remember(self, pid, sig, v):
        self._views[pid] = (sig, v)
        self._views.move_to_end(pid)
        while len(self._views) > VIEW_CACHE: self._views.popitem(last=False)

    def entry(self, pid):
        return self._load(pid)[0]

    def view(self, pid):
        """O documento completo (o que load_pb() devolve), ou None se não existe."""
        e, v = self._load(pid)
        if not e: return None
        if v is not None: return v
        with self._lock:
            c = self._views.get(pid)
            if c and c[0] == e.sig:
                self._views.move_to_end(pid)
                return c[1]
            f = self._found.get(pid)
        if not f: return None
        with self._pid_lock(pid):
            v = self._build(pid, *f)
            with self._lock: self._remember(pid, f[1], v)
            return v

    def pids(self):
        self.scan()
        with self._lock:
            return sorted(self._found, key=self.core.sort_key)

    def entries(self):
        # durante o pré-aquecimento, espera ele terminar em vez de disputar documento a documento com ele
        if self._warming and not self.ready.is_set() and threading.current_thread().name != "cache-warm":
            self.ready.wait(timeout=30)
        return [e for e in (self.entry(p) for p in self.pids()) if e]

    def summaries(self, visible=None, status=None, dtype=None):
        if dtype: return [e.summary for e in self.entries() if e.type == dtype and (visible is None or visible(e.summary))
                          and (not status or e.summary["status"] == status)]
        return [e.summary for e in self.entries() if (visible is None or visible(e.summary)) and (not status or e.summary["status"] == status)]

    def citations(self, pid, visible=None):
        """{out: citados por pid, in: quem cita pid}; só documentos que a pessoa pode ver (citação a documento que não
        existe vem com missing=True, sem revelar nada)."""
        es = {e.pid: e for e in self.entries()}
        me = es.get(pid)
        if not me: return {"out": [], "in": []}
        ok = lambda e: visible is None or visible(e.summary)
        brief = lambda e: {"id": e.pid, "type": e.type, "name": e.summary["name"], "slug": e.summary["slug"], "status": e.summary["status"]}
        out = [brief(es[x]) if x in es else {"id": x, "missing": True} for x in me.links if x not in es or ok(es[x])]
        inc = [brief(e) for e in es.values() if pid in e.links and ok(e)]
        return {"out": out, "in": sorted(inc, key=lambda x: DT.sort_key(x["id"]))}

    def search(self, q, visible=None, limit=30):
        words = norm(q).split()
        if not words: return []
        hits = []
        for e in self.entries():
            if visible is not None and not visible(e.summary): continue
            for kind, title, anchor, ntitle, ntext in e.search_docs:
                if not all(w in ntext or w in ntitle for w in words): continue
                score = (3 if all(w in ntitle for w in words) else 0) + (2 if kind in ("passo", "ramo", "documento") else 1)
                hits.append((-score, e.pid, {"pid": e.pid, "type": e.type, "kind": kind, "title": title, "anchor": anchor}))
        hits.sort(key=lambda h: (h[0], self.core.sort_key(h[1])))
        return [h[2] for h in hits[:limit]]

    # ── cache em disco
    def load_persisted(self):
        if not self.cache_file: return
        try:
            d = json.loads(self.cache_file.read_text("utf-8"))
            if d.get("format") == PERSIST_FORMAT and isinstance(d.get("entries"), dict): self._persisted = d["entries"]
        except (OSError, ValueError):
            self._persisted = {}

    def persist(self):
        """Grava resumos e textos de busca (só se algo mudou desde a última gravação)."""
        if not self.cache_file or self._persisted_gen == self.generation: return
        with self._lock:
            gen = self.generation
            entries = {pid: {"sig": e.sig, "summary": e.summary, "search": e.search_docs, "links": list(e.links)} for pid, e in self._entries.items()}
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.core.atomic_write(self.cache_file, json.dumps({"format": PERSIST_FORMAT, "entries": entries}, ensure_ascii=False))
            self._persisted_gen = gen
        except OSError as e:
            sys.stderr.write(f"Aviso: não consegui gravar o cache em disco ({e})\n")

    def warm(self):
        """Pré-aquecimento no boot (thread daemon): lê o cache em disco, interpreta só o que mudou e registra o
        tempo no log. Depois grava o cache em disco a cada 30 s, se algo mudou."""
        def run():
            t = time.perf_counter()
            try:
                self.load_persisted()
                self.scan(force=True)
                n = len(self.entries())
                sys.stderr.write(f"Cache de documentos pronto: {n} documento(s) em {(time.perf_counter() - t) * 1000:.0f} ms\n")
                self._persisted = {}
                self.persist()
            except Exception as e:  # o cache se monta sob demanda se o pré-aquecimento falhar
                sys.stderr.write(f"ERRO no pré-aquecimento do cache: {e!r}\n")
            finally:
                self.ready.set()
            while True:
                time.sleep(PERSIST_EVERY)
                try: self.persist()
                except Exception as e: sys.stderr.write(f"ERRO ao gravar o cache: {e!r}\n")
        self._warming = True
        threading.Thread(target=run, name="cache-warm", daemon=True).start()
