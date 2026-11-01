#!/usr/bin/env python3
"""Heavy continuous load: N concurrent API clients hammer every ticker/Greek/expiry-set combination while one real
browser (Atlas + 4-pane heatmap) must stay responsive. Reports server RSS/threads/fds, request latency percentiles,
error counts, and browser frame pacing + heap/DOM/listeners.   usage: stress_heavy.py [seconds] [clients]"""
import os, subprocess, sys, threading, time, http.client, itertools, statistics, random, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from real_lwc import install_real_lwc
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 120; CLIENTS = int(sys.argv[2]) if len(sys.argv) > 2 else 24; PORT = 18650
srv = subprocess.Popen([f"{ROOT}/build/skylit_server", "--port", str(PORT), "--web-root", f"{ROOT}/frontend"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
T = ["SPXW", "SPY", "QQQ", "NVDA", "TSLA", "MSFT", "AMZN", "VIX"]; G = ["GEX", "VEX", "CHEX", "COLOR", "SPEED", "GEX%2BVEX"]
E = ["0dte", "dte:0", "dte:1,2,3", "dte:0,1,2,3,4,5,6", "current%2B10", "current%2B50", "dte:50"]
lat, errs, stop = [], [], False; lock = threading.Lock(); count = [0]
def proc(pid):
    d = {}
    for l in open(f"/proc/{pid}/status"):
        k, _, v = l.partition(":"); d[k] = v.strip()
    return int(d["VmRSS"].split()[0]) / 1024, int(d["Threads"]), len(os.listdir(f"/proc/{pid}/fd"))
def worker(seed):
    rnd = random.Random(seed); c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    while not stop:
        t = rnd.choice(T); k = rnd.random()
        if k < 0.5: p = f"/api/heatmap?ticker={t}&exposure={rnd.choice(G)}&expiration={rnd.choice(E)}"
        elif k < 0.7: p = f"/api/candles?ticker={t}&interval={rnd.choice(['1m','5m','15m'])}"
        elif k < 0.85: p = f"/api/candles/latest?ticker={t}&interval=1m"
        elif k < 0.95: p = f"/api/quadrinity?tickers={','.join(rnd.sample(T, 4))}&exposure=GEX&expiration=dte:0"
        else: p = f"/api/projection?ticker={t}&interval=5m&exposure=GEX&dte={rnd.randint(0,6)}"
        t0 = time.perf_counter()
        try:
            c.request("GET", p); r = c.getresponse(); body = r.read()
            ok = r.status == 200; 
            if ok and body[:1] in b"{[": json.loads(body)
            if not ok: raise RuntimeError(f"{r.status} {p}")
            with lock: lat.append((time.perf_counter() - t0) * 1000); count[0] += 1
        except Exception as e:
            with lock: errs.append(str(e)[:120])
            c.close(); c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
try:
    for _ in range(60):
        try: http.client.HTTPConnection("127.0.0.1", PORT, timeout=1).request("GET", "/api/health"); break
        except Exception: time.sleep(0.1)
    r0 = proc(srv.pid); print(f"server baseline RSS {r0[0]:.1f} MB threads {r0[1]} fds {r0[2]}")
    ths = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(CLIENTS)]
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=os.environ.get("SKYLIT_CHROMIUM") or None, args=["--no-sandbox", "--enable-precise-memory-info"])
        pg = b.new_context(viewport={"width": 1700, "height": 950}).new_page(); perr = []
        pg.on("pageerror", lambda e: perr.append(str(e)))
        install_real_lwc(pg); pg.goto(f"http://127.0.0.1:{PORT}/"); pg.wait_for_selector(".atlas-pane-price"); pg.wait_for_timeout(2500)
        cdp = pg.context.new_cdp_session(pg); cdp.send("Performance.enable")
        def snap():
            cdp.send("HeapProfiler.collectGarbage"); m = {x["name"]: x["value"] for x in cdp.send("Performance.getMetrics")["metrics"]}
            return m["JSHeapUsedSize"] / 1e6, m["Nodes"], m["JSEventListeners"]
        h0 = snap()
        pg.evaluate("() => { window.__ft = []; let last = performance.now(); const f = (t) => { window.__ft.push(t - last); last = t; requestAnimationFrame(f); }; requestAnimationFrame(f); }")
        [t.start() for t in ths]; t0 = time.time(); box = pg.locator("#chart-pane .atlas-pane-chart").first.bounding_box(); samples = []
        tick = 0
        while time.time() - t0 < SECS:
            pg.wait_for_timeout(5000); tick += 1
            pg.mouse.move(box["x"] + 500, box["y"] + 300); pg.mouse.wheel(0, -150 if tick % 2 else 150)
            if tick % 6 == 0: pg.select_option(".atlas-pane-ticker-select", T[tick // 6 % len(T)])
            samples.append(proc(srv.pid))
        stop = True; [t.join(5) for t in ths]
        ft = pg.evaluate("() => window.__ft")[3:]; h1 = snap(); s = sorted(ft)
        spot = pg.inner_text(".atlas-pane-price")
        b.close()
    r1 = proc(srv.pid); L = sorted(lat)
    q = lambda p: L[min(len(L) - 1, int(len(L) * p))]
    print(f"requests {count[0]} in {SECS:.0f}s = {count[0]/SECS:.0f}/s with {CLIENTS} clients; errors {len(errs)} {errs[:3]}")
    print(f"latency ms p50 {q(.5):.1f} p95 {q(.95):.1f} p99 {q(.99):.1f} max {L[-1]:.0f}")
    print(f"server RSS {r0[0]:.1f} -> {max(x[0] for x in samples):.1f} peak -> {r1[0]:.1f} MB; threads {r0[1]} -> {r1[1]}; fds {r0[2]} -> {r1[2]}")
    print(f"browser frames {len(ft)} mean {statistics.mean(ft):.1f} ms p95 {s[int(len(s)*.95)]:.1f} p99 {s[int(len(s)*.99)]:.1f} max {max(ft):.0f}; >100ms: {sum(1 for x in ft if x > 100)}")
    print(f"browser heap {h0[0]:.1f} -> {h1[0]:.1f} MB; DOM {h0[1]} -> {h1[1]}; listeners {h0[2]} -> {h1[2]}; page errors {perr[:3]}; price still live: {spot}")
    bad = errs or perr or r1[2] > r0[2] + 20 or r1[0] > r0[0] * 3 + 50
    sys.exit(1 if bad else 0)
finally: srv.terminate()
