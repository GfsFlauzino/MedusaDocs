#!/usr/bin/env python3
"""Benchmark das APIs com N documentos sintéticos numa instalação temporária (só biblioteca padrão).

  python3 tools/bench.py [--app-dir .] [--sizes 10,50,150,500] [--reps 5]

Mede: lista (GET /api/library, ou /api/data na versão base), detalhe, busca, PUT doc, 8 e 32 clientes
simultâneos na lista, tamanho bruto e comprimido (gzip) da lista e memória do servidor.
Os documentos são criados copiando no disco um playbook criado pela API (como faria uma edição externa).
"""
import argparse, gzip, json, re, shutil, statistics, subprocess, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import helpers as H  # noqa: E402


def clone(app, n):
    """PB-01 já criado pela API → PB-02…PB-n copiados no disco (com vínculos do mappings.json)."""
    src = next((app.home / "playbooks").glob("PB-01-*"))
    maps_f = app.home / "mappings.json"
    maps = json.loads(maps_f.read_text("utf-8"))
    for i in range(2, n + 1):
        pid = f"PB-{i:02d}" if i < 100 else f"PB-{i}"
        dest = app.home / "playbooks" / src.name.replace("PB-01", pid)
        shutil.copytree(src, dest)
        for f in dest.iterdir():
            if f.is_file():
                g = f.with_name(f.name.replace("PB-01", pid).replace("pb-01", pid.lower()))
                f.rename(g)
                if g.suffix == ".md":
                    g.write_text(g.read_text("utf-8").replace("PB-01", pid), "utf-8")
        maps[pid] = maps.get("PB-01", {})
    maps_f.write_text(json.dumps(maps, ensure_ascii=False), "utf-8")


def wait_ready(app, before, timeout=60):
    """Espera o fim do pré-aquecimento (nova linha no log). A versão base não tem: volta na hora."""
    t = time.time()
    while time.time() - t < timeout:
        n = app.read_log().count("Cache de documentos pronto")
        if n > before or (n == 0 and "Cache de documentos" not in app.read_log() and time.time() - t > 0.5): return
        time.sleep(0.05)


def timed(fn):
    t = time.perf_counter(); r = fn(); return (time.perf_counter() - t) * 1000, r


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def rss_mb(pid):
    try: return int(subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()) / 1024
    except ValueError: return float("nan")


def concurrent(app, path, n, gz):
    cookie = app.admin().token()
    times, errors = [], []
    def run(i):
        c = app.client(); c.set_token(cookie)
        try:
            ms, r = timed(lambda: c.get(path, headers={"Accept-Encoding": "gzip"} if gz else None))
            (times if r.status == 200 else errors).append(ms)
        except OSError as e:          # conexão recusada/derrubada pelo servidor sobrecarregado
            errors.append(repr(e))
    ts = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    t0 = time.perf_counter()
    for t in ts: t.start()
    for t in ts: t.join()
    total = (time.perf_counter() - t0) * 1000
    return (pct(times, 50), pct(times, 95), total, len(errors)) if times else (float("nan"), float("nan"), total, len(errors))


def bench(app_dir, n, reps):
    app = H.TempApp(app_dir=app_dir).start()
    try:
        admin = app.admin()
        H.create_playbook(admin, "PB-01", "Teste de desempenho", ramos=("Credencial", "Anexo", "Link"))
        clone(app, n)
        new_api = admin.get("/api/library").status == 200
        lst = "/api/library?limit=100" if new_api else "/api/data"
        # reinicia para medir a primeira chamada depois do boot (o pré-aquecimento corre em paralelo)
        ready = lambda: app.read_log().count("Cache de documentos pronto")
        before = ready(); app.stop(); app.start()
        cold, _ = timed(lambda: admin.get(lst))
        wait_ready(app, before)
        cold_disk = None
        if new_api:          # 2º boot: resumos vêm do cache em disco (data/cache/biblioteca.json)
            before = ready(); app.stop(); app.start()
            cold_disk, _ = timed(lambda: admin.get(lst))
            wait_ready(app, before)
        gz = {"Accept-Encoding": "gzip"}
        hot = [timed(lambda: admin.get(lst, headers=gz))[0] for _ in range(reps)]
        r = admin.get(lst)
        raw = len(r.body)
        rz = admin.get(lst, headers=gz)
        comp = len(rz.body) if rz.headers.get("Content-Encoding") == "gzip" else len(gzip.compress(r.body, 5))
        et = r.headers.get("ETag")
        t304 = [timed(lambda: admin.get(lst, headers={"If-None-Match": et}))[0] for _ in range(reps)] if et else []
        det = [timed(lambda: admin.get(f"/api/pb/PB-{(i % n) + 1:02d}" if (i % n) + 1 < 100 else f"/api/pb/PB-{(i % n) + 1}"))[0] for i in range(reps)]
        search = [timed(lambda: admin.get("/api/search?q=credencial"))[0] for _ in range(reps)] if new_api else []
        puts = []
        for _ in range(reps):
            pb = admin.get("/api/pb/PB-01").json()["playbook"]
            ms, rr = timed(lambda: admin.put("/api/pb/PB-01/doc", {"doc": pb["doc"], "rev": pb["rev"]}))
            puts.append(ms)
        c8, c32 = concurrent(app, lst, 8, True), concurrent(app, lst, 32, True)
        mem = rss_mb(app.proc.pid)
        return {"n": n, "api": lst.split("?")[0], "cold": cold, "cold_disk": cold_disk, "hot50": statistics.median(hot), "raw_kb": raw / 1024, "gz_kb": comp / 1024,
                "t304": statistics.median(t304) if t304 else None, "detail": statistics.median(det),
                "search": statistics.median(search) if search else None, "put": statistics.median(puts),
                "c8": c8, "c32": c32, "mem": mem}
    finally:
        app.cleanup()


def conc(c):
    return f"{c[0]:.0f}/{c[1]:.0f} ({c[2]:.0f})" + (f" {c[3]} erro(s)" if c[3] else "")


def fmt(v, d=1):
    return "—" if v is None else f"{v:.{d}f}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--app-dir", default=str(ROOT))
    p.add_argument("--sizes", default="10,50,150,500")
    p.add_argument("--reps", type=int, default=5)
    a = p.parse_args()
    rows = [bench(Path(a.app_dir).resolve(), int(n), a.reps) for n in a.sizes.split(",")]
    print(f"Medusa Docs — benchmark ({time.strftime('%Y-%m-%d %H:%M')}, Python {sys.version.split()[0]}, {a.app_dir})")
    print("tempos em ms (mediana); concorrência: p50/p95 por requisição e tempo total; memória do servidor no fim (MB)\n")
    head = ["N", "lista", "1ª após boot", "1ª após boot (cache em disco)", "quente", "bruto KB", "gzip KB", "304", "detalhe", "busca", "PUT doc", "8 simult.", "32 simult.", "RSS MB"]
    print(" | ".join(head))
    for r in rows:
        print(" | ".join([str(r["n"]), r["api"], fmt(r["cold"]), fmt(r["cold_disk"]), fmt(r["hot50"]), fmt(r["raw_kb"], 0), fmt(r["gz_kb"], 0), fmt(r["t304"]),
                          fmt(r["detail"]), fmt(r["search"]), fmt(r["put"]),
                          conc(r["c8"]), conc(r["c32"]),
                          fmt(r["mem"], 0)]))


if __name__ == "__main__":
    main()
