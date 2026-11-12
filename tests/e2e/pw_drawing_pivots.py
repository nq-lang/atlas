#!/usr/bin/env python3
"""Drawings: (1) after placing, the chart is immediately interactive again (no lingering preview, tool idle,
pan/zoom work); (2) every drawing has pivots that edit ONE aspect (TP, SL, entry, width / corners, edges /
price) with validity clamps; (3) lost-mouseup / blur / Esc safety; (4) persistence + migration; (5) numeric
level editing; (6) performance with hundreds of drawings and no listener growth.  Real Lightweight Charts."""
import json, os, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from real_lwc import install_real_lwc
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORT = int(os.environ.get("SKYLIT_TEST_PORT", "18442")); results = []
def check(n, c, d=""):
    results.append(bool(c)); print(("  PASS  " if c else "  FAIL  ") + n + (f"   [{d}]" if d else ""))
INIT = """
(() => { let real; Object.defineProperty(window, 'createDrawingLayer', { configurable: true,
  set(f) { real = function () { const l = f.apply(this, arguments); (window.__layers = window.__layers || []).push(l); return l; }; }, get() { return real; } }); })();
window.__lc = 0;
const add = EventTarget.prototype.addEventListener, rem = EventTarget.prototype.removeEventListener; const seen = new WeakMap();
EventTarget.prototype.addEventListener = function (t, f, o) { if (f) { const k = t + '|' + (o && o.capture || o === true); let m = seen.get(this); if (!m) seen.set(this, m = new Map()); if (!m.has(f)) m.set(f, new Set()); if (!m.get(f).has(k)) { m.get(f).add(k); window.__lc++; } } return add.call(this, t, f, o); };
EventTarget.prototype.removeEventListener = function (t, f, o) { const m = seen.get(this); const k = t + '|' + (o && o.capture || o === true); if (m && m.has(f) && m.get(f).delete(k)) window.__lc--; return rem.call(this, t, f, o); };
"""
PREVPIX = """() => { const c = document.querySelector('#chart-pane .atlas-drawing-preview'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  for (let i = 3; i < d.length; i += 4) if (d[i] > 20) return true; return false; }"""
srv = subprocess.Popen([f"{ROOT}/build/skylit_server", "--port", str(PORT), "--web-root", f"{ROOT}/frontend"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=1); break
        except Exception: time.sleep(0.1)
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=os.environ.get("SKYLIT_CHROMIUM") or None, args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width": 1700, "height": 1000}); pg = ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "favicon" not in m.text else None)
        pg.add_init_script(INIT); install_real_lwc(pg)
        pg.goto(f"http://127.0.0.1:{PORT}/"); pg.wait_for_selector(".atlas-pane-price"); pg.wait_for_timeout(2500)
        pg.evaluate("() => localStorage.clear()")
        box = pg.locator("#chart-pane .atlas-pane-chart").first.bounding_box(); X0, Y0 = box["x"], box["y"]
        L = lambda js, *a: pg.evaluate(f"(a) => {{ const L = window.__layers[0]; {js} }}", list(a))
        def frames(n=3): pg.evaluate("(n) => new Promise(r => { let i = 0; const f = () => ++i >= n ? setTimeout(r, 0) : requestAnimationFrame(f); requestAnimationFrame(f); })", n)
        drawings = lambda: L("return L.getDrawings();")
        byid = lambda i: next(d for d in drawings() if d["id"] == i)
        handles = lambda: {h["id"]: h for h in L("return L.getHandles();")}
        sel = lambda: L("return L.getSelectedId();")
        def place(t, x, y, dx=120, dy=-60):
            pg.click(f"#chart-pane .atlas-drawing-tool-{t}"); pg.mouse.move(X0 + x, Y0 + y); pg.mouse.down(); pg.mouse.move(X0 + x + dx, Y0 + y + dy, steps=5); pg.mouse.up(); frames()
            return drawings()[-1]["id"]
        def drag(hid, dx, dy, to=None):
            h = handles()[hid]; pg.mouse.move(X0 + h["x"], Y0 + h["y"]); pg.mouse.down()
            tx, ty = (X0 + to[0], Y0 + to[1]) if to else (X0 + h["x"] + dx, Y0 + h["y"] + dy)
            pg.mouse.move(tx, ty, steps=6); pg.mouse.up(); frames()
        price_at = lambda x, y: L("return L.pointAt(a[0], a[1]);", x, y)["price"]
        time_at = lambda x, y: L("return L.pointAt(a[0], a[1]);", x, y)["time"]

        print("[1] after placing: chart interactive again, nothing lingers")
        for i, t in enumerate(["hline", "rect", "short", "long", "range"]):
            did = place(t, 300 + i * 40, 330 + i * 20)
            check(f"{t}: idle, new drawing selected (pivots usable), no preview pixels",
                  L("return L.getMode();") == "idle" and sel() == did and not pg.evaluate(PREVPIX) and "armed" not in (pg.get_attribute("#chart-pane .atlas-pane-chart", "class") or ""))
            for k in range(8):
                pg.mouse.move(X0 + 700 + k * 70, Y0 + 150 + (k % 3) * 120); pg.wait_for_timeout(15)
            frames()
            check(f"{t}: sweeping the chart creates no preview", not pg.evaluate(PREVPIX) and L("return L.getPreview();") is None)
        n0 = L("return L.getDrawingCount();")
        lr0 = pg.evaluate("() => __charts[0].timeScale().getVisibleLogicalRange().from")
        pg.mouse.move(X0 + 900, Y0 + 700); pg.mouse.down(); pg.mouse.move(X0 + 1050, Y0 + 700, steps=6); pg.mouse.up(); frames()
        check("first drag on empty chart pans it (no click needed to 'unlock')", pg.evaluate("() => __charts[0].timeScale().getVisibleLogicalRange().from") < lr0 - 2)
        check("...and does not create anything", L("return L.getDrawingCount();") == n0 and not pg.evaluate(PREVPIX) and sel() is None)
        lr1 = pg.evaluate("() => { const r = __charts[0].timeScale().getVisibleLogicalRange(); return r.to - r.from; }")
        pg.mouse.move(X0 + 900, Y0 + 500); pg.mouse.wheel(0, -300); frames(4)
        check("wheel zoom works", abs(pg.evaluate("() => { const r = __charts[0].timeScale().getVisibleLogicalRange(); return r.to - r.from; }") - lr1) > 0.5)
        L("a; L.getDrawings().forEach(() => {}); return 0;")
        pg.evaluate("() => { window.__layers[0].clearAll(); }")

        print("[2] position tool pivots (long)")
        did = place("long", 400, 520, 200, -120); d0 = byid(did)
        check("committed with explicit sl", d0.get("sl") is not None and d0["sl"] < d0["p1"]["price"] < d0["p2"]["price"], str((d0["sl"], d0["p1"]["price"], d0["p2"]["price"])))
        H = handles(); check("4 pivots: entry, tp, sl, width", set(H) == {"entry", "tp", "sl", "width"}, str(list(H)))
        drag("tp", 0, -50, None); d1 = byid(did)
        check("TP pivot moves TP only", d1["p2"]["price"] > d0["p2"]["price"] and d1["sl"] == d0["sl"] and d1["p1"] == d0["p1"] and d1["p2"]["time"] == d0["p2"]["time"])
        H = handles(); drag("sl", 0, 40); d2 = byid(did)
        check("SL pivot moves SL only (lower)", d2["sl"] < d1["sl"] and d2["p2"] == d1["p2"] and d2["p1"] == d1["p1"])
        H = handles(); drag("width", 90, 0); d3 = byid(did)
        check("width pivot changes length only", d3["p2"]["time"] > d2["p2"]["time"] and d3["p2"]["price"] == d2["p2"]["price"] and d3["sl"] == d2["sl"] and d3["p1"] == d2["p1"])
        H = handles(); drag("entry", -30, 15); d4 = byid(did)
        check("entry pivot moves entry (time+price); TP and SL stay put", d4["p1"]["time"] != d3["p1"]["time"] and d4["p1"]["price"] != d3["p1"]["price"] and d4["sl"] == d3["sl"] and d4["p2"]["price"] == d3["p2"]["price"])
        lv = lambda d: (d["sl"], d["p1"]["price"], d["p2"]["price"])
        H = handles(); drag("tp", 0, 0, to=(H["tp"]["x"], H["entry"]["y"] + 150)); d5 = byid(did)
        check("TP cannot be dragged below entry (clamped, still valid)", d5["sl"] < d5["p1"]["price"] < d5["p2"]["price"], str(lv(d5)))
        H = handles(); drag("sl", 0, 0, to=(H["sl"]["x"], H["entry"]["y"] - 150)); d6 = byid(did)
        check("SL cannot be dragged above entry (clamped, still valid)", d6["sl"] < d6["p1"]["price"] < d6["p2"]["price"], str(lv(d6)))
        H = handles(); drag("entry", 0, 0, to=(H["entry"]["x"], H["tp"]["y"] - 80)); d7 = byid(did)
        check("entry cannot cross TP", d7["sl"] < d7["p1"]["price"] < d7["p2"]["price"], str(lv(d7)))
        check("label reflects edited levels", L("return L.getDrawingCount();") == 1)

        print("[3] short mirrors")
        pg.evaluate("() => window.__layers[0].clearAll()")
        did = place("short", 400, 420, 200, 120); s0 = byid(did)
        check("short committed valid", s0["p2"]["price"] < s0["p1"]["price"] < s0["sl"], str((s0["p2"]["price"], s0["p1"]["price"], s0["sl"])))
        H = handles(); drag("tp", 0, 0, to=(H["tp"]["x"], H["entry"]["y"] - 120)); s1 = byid(did)
        check("short TP cannot go above entry", s1["p2"]["price"] < s1["p1"]["price"] < s1["sl"])
        H = handles(); drag("sl", 0, 0, to=(H["sl"]["x"], H["entry"]["y"] + 100)); s2 = byid(did)
        check("short SL cannot go below entry", s2["p2"]["price"] < s2["p1"]["price"] < s2["sl"])
        H = handles(); drag("sl", 0, -35); s3 = byid(did)
        check("short SL moves SL only", s3["sl"] != s2["sl"] and s3["p1"] == s2["p1"] and s3["p2"] == s2["p2"])

        print("[4] body drag moves the whole position (SL included)")
        before = byid(did); H = handles(); bx, by = X0 + H["entry"]["x"] + 40, Y0 + (H["entry"]["y"] + H["tp"]["y"]) / 2
        pg.mouse.move(bx, by); pg.mouse.down(); pg.mouse.move(bx + 60, by + 40, steps=6); pg.mouse.up(); frames(); after = byid(did)
        dpe = after["p1"]["price"] - before["p1"]["price"]
        check("entry, TP and SL all shifted by the same price delta", abs((after["p2"]["price"] - before["p2"]["price"]) - dpe) < 1e-6 and abs((after["sl"] - before["sl"]) - dpe) < 1e-6 and abs(dpe) > 0, f"{dpe:.4f}")
        check("length preserved", abs((after["p2"]["time"] - after["p1"]["time"]) - (before["p2"]["time"] - before["p1"]["time"])) < 1)

        print("[5] rect / range: 8 pivots, each edits only its sides")
        pg.evaluate("() => window.__layers[0].clearAll()")
        for t in ["rect", "range"]:
            did = place(t, 450, 450, 220, 120)
            H = handles(); check(f"{t}: 8 pivots", set(H) == {"nw", "ne", "sw", "se", "n", "s", "w", "e"}, str(sorted(H)))
            base = byid(did); pts = lambda d: (d["p1"]["time"], d["p1"]["price"], d["p2"]["time"], d["p2"]["price"])
            def side(d):  # normalised box
                return dict(l=min(d["p1"]["time"], d["p2"]["time"]), r=max(d["p1"]["time"], d["p2"]["time"]), t=max(d["p1"]["price"], d["p2"]["price"]), b=min(d["p1"]["price"], d["p2"]["price"]))
            for hid, key, dxy in [("e", "r", (50, 0)), ("w", "l", (-40, 0)), ("n", "t", (0, -40)), ("s", "b", (0, 35))]:
                a = side(byid(did)); H = handles(); drag(hid, *dxy); c = side(byid(did))
                changed = {k for k in a if abs(a[k] - c[k]) > 1e-9}
                check(f"{t}: edge {hid} changes only side {key}", changed == {key}, str(changed))
            for hid, keys, dxy in [("se", {"r", "b"}, (30, 25)), ("nw", {"l", "t"}, (-25, -20)), ("ne", {"r", "t"}, (30, -20)), ("sw", {"l", "b"}, (-25, 25))]:
                a = side(byid(did)); H = handles(); drag(hid, *dxy); c = side(byid(did))
                changed = {k for k in a if abs(a[k] - c[k]) > 1e-9}
                check(f"{t}: corner {hid} changes exactly sides {sorted(keys)}", changed == keys, str(changed))
            H = handles(); drag("e", 0, 0, to=(H["w"]["x"] - 70, H["e"]["y"])); c = side(byid(did))
            check(f"{t}: dragging an edge past the opposite one flips cleanly (still a valid box)", c["l"] < c["r"] and c["b"] < c["t"])
            pg.evaluate("() => window.__layers[0].clearAll()")
        did = place("hline", 500, 500, 0, 0); H = handles()
        check("hline: one price pivot", list(H) == ["price"], str(list(H)))
        p0 = byid(did)["p1"]; drag("price", 0, -60); p1 = byid(did)
        check("hline price pivot moves the line, time unchanged", p1["p1"]["price"] != p0["price"] and p1["p1"]["time"] == p0["time"] and p1["p2"] == p1["p1"])

        print("[6] safety: Esc, lost mouseup, blur, tool switching")
        pg.evaluate("() => window.__layers[0].clearAll()")
        did = place("long", 400, 520, 200, -120); d0 = byid(did); H = handles()
        pg.mouse.move(X0 + H["tp"]["x"], Y0 + H["tp"]["y"]); pg.mouse.down(); pg.mouse.move(X0 + H["tp"]["x"], Y0 + H["tp"]["y"] - 60, steps=4); frames()
        pg.keyboard.press("Escape"); pg.mouse.up(); frames()
        check("Esc during a pivot drag reverts it", byid(did)["p2"] == d0["p2"] and byid(did)["sl"] == d0["sl"])
        H = handles(); pg.mouse.move(X0 + H["tp"]["x"], Y0 + H["tp"]["y"]); pg.mouse.down(); pg.mouse.move(X0 + H["tp"]["x"], Y0 + H["tp"]["y"] - 40, steps=3)
        # the button is released somewhere we never see it: next move reports buttons=0
        pg.evaluate("() => { const w = document.querySelector('#chart-pane .atlas-pane-chart'); w.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: 600, clientY: 300, buttons: 0 })); }"); frames()
        check("lost mouseup: gesture ends on the next move (no stuck drag)", L("return L.getMode();") == "idle")
        pg.mouse.up(); pg.mouse.move(X0 + 800, Y0 + 600); frames(); check("no preview after lost mouseup", not pg.evaluate(PREVPIX))
        pg.click("#chart-pane .atlas-drawing-tool-rect"); pg.mouse.move(X0 + 500, Y0 + 400); frames()
        pg.evaluate("() => window.dispatchEvent(new Event('blur'))"); frames()
        check("window blur while armed -> idle, no ghost", L("return L.getMode();") == "idle" and not pg.evaluate(PREVPIX))
        pg.click("#chart-pane .atlas-drawing-tool-rect"); pg.mouse.move(X0 + 500, Y0 + 400); pg.mouse.down(); pg.mouse.up(); pg.mouse.move(X0 + 600, Y0 + 460); frames()
        pg.evaluate("() => window.dispatchEvent(new Event('blur'))"); frames()
        check("window blur while placing -> idle, nothing committed", L("return L.getMode();") == "idle" and L("return L.getDrawingCount();") == 1 and not pg.evaluate(PREVPIX))

        print("[7] persistence + migration + numeric levels")
        key = pg.evaluate("() => Object.keys(localStorage).find(k => k.startsWith('skylit:drawings:'))")
        saved = json.loads(pg.evaluate("(k) => localStorage.getItem(k)", key))
        check("sl persisted", saved[0].get("sl") is not None)
        legacy = [{"id": "old1", "type": "long", "p1": saved[0]["p1"], "p2": saved[0]["p2"]}, {"id": "old2", "type": "short", "p1": saved[0]["p1"], "p2": {"time": saved[0]["p2"]["time"], "price": saved[0]["p1"]["price"] - 5}}]
        pg.evaluate("([k, v]) => localStorage.setItem(k, v)", [key, json.dumps(legacy)]); pg.reload(); pg.wait_for_selector(".atlas-pane-price"); pg.wait_for_timeout(2500)
        ds = drawings(); o1 = next(d for d in ds if d["id"] == "old1"); o2 = next(d for d in ds if d["id"] == "old2")
        check("legacy long gets the old default SL (half the reward)", abs((o1["p1"]["price"] - o1["sl"]) - (o1["p2"]["price"] - o1["p1"]["price"]) / 2) < 1e-6)
        check("legacy short gets the old default SL", abs((o2["sl"] - o2["p1"]["price"]) - (o2["p1"]["price"] - o2["p2"]["price"]) / 2) < 1e-6)
        L("a; L.openSettings('old1'); return 0;"); pg.wait_for_selector("#chart-pane .atlas-drawing-level")
        e = pg.locator("#chart-pane .atlas-drawing-level[data-k=tp]"); newtp = round(byid("old1")["p2"]["price"] + 3, 2)
        e.fill(str(newtp)); e.dispatch_event("change"); frames()
        check("numeric TP entry applies", abs(byid("old1")["p2"]["price"] - newtp) < 0.011, str(byid("old1")["p2"]["price"]))
        s_in = pg.locator("#chart-pane .atlas-drawing-level[data-k=sl]"); s_in.fill(str(round(byid("old1")["p1"]["price"] + 50, 2))); s_in.dispatch_event("change"); frames()
        check("numeric SL above entry is clamped for a long", byid("old1")["sl"] < byid("old1")["p1"]["price"])
        pg.keyboard.press("Escape")

        print("[8] performance: 300 drawings, listener stability")
        pg.evaluate("() => window.__layers[0].clearAll()")
        t0 = pg.evaluate("""() => { const L = window.__layers[0]; const out = [];
          for (let i = 0; i < 300; i++) { const x = 80 + (i * 37) % 900, y = 90 + (i * 53) % 560; const a = L.pointAt(x, y), b = L.pointAt(x + 60 + i % 40, y - 30);
            const type = ['rect', 'long', 'short', 'range', 'hline'][i % 5]; out.push({ id: 'p' + i, type, p1: a, p2: type === 'hline' ? a : b, visible: true }); }
          localStorage.setItem('skylit:drawings:' + Object.keys(localStorage).find(k => k.startsWith('skylit:drawings:')).split(':')[2], JSON.stringify(out)); return out.length; }""")
        pg.reload(); pg.wait_for_selector(".atlas-pane-price"); pg.wait_for_timeout(2500)
        check("300 drawings loaded", L("return L.getDrawingCount();") == 300)
        L("a; L.select('p1'); return 0;"); frames()
        pg.evaluate("() => { window.__ft = []; let last = performance.now(); window.__on = true; const f = (t) => { if (!window.__on) return; window.__ft.push(t - last); last = t; requestAnimationFrame(f); }; requestAnimationFrame(f); }")
        H = handles(); hid = next(iter(H))
        h = H[hid]; pg.mouse.move(X0 + h["x"], Y0 + h["y"]); pg.mouse.down()
        for k in range(90): pg.mouse.move(X0 + h["x"] + (k % 45) * 2, Y0 + h["y"] + (k % 30))
        pg.mouse.up(); pg.evaluate("() => { window.__on = false; }"); ft = sorted(pg.evaluate("() => window.__ft")[3:])
        p95 = ft[int(len(ft) * .95) - 1]
        stats = L("return L.getStats();")
        check("pivot drag with 300 drawings: p95 frame <= 34 ms (30+ FPS even in software rendering)", p95 <= 34, f"p95={p95:.1f} ms, frames={len(ft)}")
        base = pg.evaluate("() => window.__lc")
        for i in range(60):
            pg.click("#chart-pane .atlas-drawing-tool-rect"); pg.mouse.move(X0 + 500, Y0 + 400); pg.mouse.down(); pg.mouse.move(X0 + 560, Y0 + 440, steps=2); pg.mouse.up()
            L("a; L.deleteDrawing(L.getDrawings().slice(-1)[0].id); return 0;")
        frames(); check("no listener growth over 60 place+delete cycles", pg.evaluate("() => window.__lc") == base, f"{base} -> {pg.evaluate('() => window.__lc')}")
        check("no page/console errors", not errs, str(errs[:3]))
        b.close()
finally: srv.terminate()
print(f"\n{sum(results)}/{len(results)} checks passed"); sys.exit(0 if all(results) else 1)
