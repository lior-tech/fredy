#!/usr/bin/env python3
"""Daily market scan for Fredy's dashboard.

Runs in GitHub Actions, not in a browser, so it can check the whole universe
instead of a rotating slice. Writes data/ideas.json, which the page reads.
Buy candidates only, matching what the app shows.
"""
import json, time, urllib.request, urllib.error, os, sys, math, random

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
BASE = "https://stockanalysis.com"

def get(url, tries=3):
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(20 * (a + 1) + random.random() * 5)
                continue
            return None
        except Exception:
            time.sleep(1)
    return None

def quote(sid):
    d = get("%s/api/quotes/%s" % (BASE, sid), tries=2)
    return d.get("data") if d and d.get("status") == 200 else None

def history(sid):
    d = get("%s/api/symbol/%s/history?range=5Y" % (BASE, sid))
    return d.get("data") if d and d.get("status") == 200 else None

def analyze(rows, q):
    if not rows or len(rows) < 260 or not q:
        return None
    r = sorted(rows, key=lambda x: x["t"])
    lastrow = r[-1]
    fl = (lastrow.get("a") / lastrow["c"]) if lastrow.get("a") and lastrow.get("c") else 1.0
    c = [x.get("a") if x.get("a") is not None else x["c"] for x in r]
    v = []
    h = []
    for x in r:
        f = (x["a"] / x["c"]) if x.get("a") and x.get("c") else 1.0
        v.append((x.get("v") or 0) * (f / fl))
        h.append((x.get("h") or x["c"]) * f)
    ma = lambda a, n: (sum(a[-n:]) / n) if len(a) >= n else None
    last = c[-1]
    px = q.get("p") if isinstance(q.get("p"), (int, float)) else last
    sc = (px / last) if last else 1.0
    ma50, ma200 = ma(c, 50), ma(c, 200)
    hi3 = max(h[-66:]) * sc
    vol5, vol60 = ma(v, 5), ma(v, 60)
    mv = [abs(c[i] / c[i-1] - 1) * 100 for i in range(len(c) - 60, len(c)) if i > 0 and c[i-1]]
    lo52, hi52 = q.get("l52"), q.get("h52")
    return {
        "px": px, "lo52": lo52, "hi52": hi52,
        "pos52": ((px - lo52) / (hi52 - lo52) * 100) if (lo52 is not None and hi52 and hi52 > lo52) else None,
        "ma50": ma50 * sc if ma50 else None, "ma200": ma200 * sc if ma200 else None,
        "vs50": ((px / (ma50 * sc) - 1) * 100) if ma50 else None,
        "vs200": ((px / (ma200 * sc) - 1) * 100) if ma200 else None,
        "goldencross": (ma50 > ma200) if (ma50 and ma200) else None,
        "r1m": (px / (c[-23] * sc) - 1) * 100 if len(c) > 22 else None,
        "r3m": (px / (c[-67] * sc) - 1) * 100 if len(c) > 66 else None,
        "r12m": (px / (c[-251] * sc) - 1) * 100 if len(c) > 250 else None,
        "fromHi3m": ((px / hi3 - 1) * 100) if hi3 else None,
        "volRatio": (vol5 / vol60) if (vol5 and vol60) else None,
        "dailyMove": (sum(mv) / len(mv)) if mv else None,
    }

def buy_score(M):
    """Mirrors verdict() in the page: 4 of 5, and no broken trend."""
    if not M:
        return None
    b = 0
    reasons = []
    if M["vs200"] is not None and M["vs200"] > 0:
        b += 1; reasons.append("המחיר מעל הממוצע של 200 יום, כלומר המגמה ארוכת הטווח חיובית")
    if M["goldencross"] is True:
        b += 1; reasons.append("הממוצע של 50 יום מעל זה של 200 יום, סימן למגמה עולה")
    if M["r3m"] is not None and M["r3m"] > 0:
        b += 1; reasons.append("המניה עלתה בשלושת החודשים האחרונים")
    if M["pos52"] is not None and M["pos52"] < 70:
        b += 1; reasons.append("המחיר עדיין לא בשיא של השנה, יש מקום לעלייה")
    if M["fromHi3m"] is not None and -18 <= M["fromHi3m"] <= -4:
        b += 1; reasons.append("המחיר ירד מעט מהשיא האחרון, נקודת כניסה סבירה בתוך מגמה עולה")
    sb = 0
    if M["vs200"] is not None and M["vs200"] < 0: sb += 1
    if M["goldencross"] is False: sb += 1
    if M["r3m"] is not None and M["r3m"] <= -10: sb += 1
    if M["fromHi3m"] is not None and M["fromHi3m"] <= -20: sb += 1
    if b >= 4 and sb <= 1:
        return {"score": b, "of": 5, "reasons": reasons}
    return None

SKIP_FILE = "data/.scanskip.json"


def load_skips():
    """Symbols that returned nothing today. Without this, every run retries all
    ~350 dead tickers with backoff and never reaches the measures at all."""
    try:
        j = json.load(open(SKIP_FILE))
        if j.get("date") == time.strftime("%Y-%m-%d", time.gmtime()):
            return set(j.get("ids") or [])
    except Exception:
        pass
    return set()


def save_skips(skips):
    try:
        json.dump({"date": time.strftime("%Y-%m-%d", time.gmtime()), "ids": sorted(skips)},
                  open(SKIP_FILE, "w"))
    except Exception:
        pass


def load_existing():
    """Resume a previous run. Anything collected today is kept, so a run that is
    cut short is never wasted and the next one simply continues."""
    prices, measures = {}, {}
    today = time.strftime("%Y-%m-%d", time.gmtime())
    for name, target in (("data/prices.json", prices), ("data/measures.json", measures)):
        try:
            j = json.load(open(name))
            if (j.get("generated_at") or "")[:10] == today:
                target.update(j.get("data") or {})
        except Exception:
            pass
    if prices or measures:
        print("resuming: %d prices, %d measures already collected today"
              % (len(prices), len(measures)), flush=True)
    return prices, measures


def publish(prices, measures):
    """Write price and measure files next to the page.

    The browser can always read these: they are served from the same origin as
    the page, so the provider's block on cross-origin calls does not apply.
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # Only the fields the page actually reads. The raw quotes carry roughly
    # twenty five keys each and the file was heading past half a megabyte,
    # which his browser would have to download before showing anything.
    keep = ("p", "cp", "cl", "l52", "h52", "ex", "v", "u", "ts", "ms")
    prices = {k: {f: v[f] for f in keep if f in v} for k, v in prices.items()}
    json.dump({"generated_at": now, "data": prices},
              open("data/prices.json", "w"), ensure_ascii=False, separators=(",", ":"))
    # round: raw floats carry a dozen meaningless decimals and inflate the file
    # his browser has to download before it can show him anything
    def r(v):
        return round(v, 3) if isinstance(v, float) else v
    measures = {k: {f: r(v) for f, v in m.items()} for k, m in measures.items()}
    if measures:
        json.dump({"generated_at": now, "data": measures},
                  open("data/measures.json", "w"), ensure_ascii=False, separators=(",", ":"))
    else:
        print("no measures this run: keeping the existing file rather than "
              "publishing an empty one", flush=True)
    print("published %d prices and %d measure sets" % (len(prices), len(measures)), flush=True)


def main():
    uni = json.load(open("data/universe.json"))
    sp500 = set(x.upper() for x in uni.get("sp500", []))
    tase_all = uni.get("tase_all") or uni["tase"]
    ids = ["a/TLV-" + x for x in tase_all] + ["s/" + x.lower() for x in uni["us"]]
    print("scanning %d symbols" % len(ids), flush=True)

    prices, measures = load_existing()
    skips = load_skips()
    if skips:
        print("skipping %d symbols that returned nothing today" % len(skips), flush=True)
    t_start = time.time()
    stage1 = []
    for i, sid in enumerate(ids):
        if sid in skips:
            continue                      # already known to return nothing today
        if sid in prices:
            q = prices[sid]               # already collected today, reuse it
        else:
            q = quote(sid)
            if q:
                prices[sid] = q
            else:
                skips.add(sid)
                if len(skips) % 25 == 0:
                    save_skips(skips)
            if len(prices) % 150 == 0:
                publish(prices, measures) # checkpoint, so nothing is ever lost
            time.sleep(0.2)
        if q and q.get("p") and q.get("l52") and q.get("h52") and q["h52"] > q["l52"]:
            pos = (q["p"] - q["l52"]) / (q["h52"] - q["l52"]) * 100
            turn = q["p"] * (q.get("v") or 0) * (0.01 if sid.startswith("a/") else 1)
            if turn >= 1e6 and abs(q.get("cp") or 0) < 15 and pos < 80:
                stage1.append((sid, q, pos))
        if (i + 1) % 50 == 0:
            print("  %d/%d, %d candidates" % (i + 1, len(ids), len(stage1)), flush=True)

    save_skips(skips)
    publish(prices, measures)
    print("stage 1 done: %d candidates, %d prices" % (len(stage1), len(prices)), flush=True)

    # Measures for the whole market, ordered by turnover so the names he is most
    # likely to hold are covered first, within a time budget.
    t_measures = time.time()      # the budget below covers the measures only
    by_liquidity = sorted(
        prices.items(),
        key=lambda kv: -((kv[1].get("p") or 0) * (kv[1].get("v") or 0) * (0.01 if kv[0].startswith("a/") else 1)))
    for sid, q in by_liquidity:
        if sid in measures or ("M:" + sid) in skips:
            continue
        if len(measures) % 60 == 0 and measures:
            publish(prices, measures)
        if time.time() - t_measures > 3600:       # an hour for the measures themselves
            print("measure budget reached at %d symbols" % len(measures), flush=True)
            break
        rows = history(sid)
        time.sleep(0.3)
        M = analyze(rows, q)
        if M:
            measures[sid] = M
        else:
            skips.add("M:" + sid)
            save_skips(skips)
    publish(prices, measures)

    stage1.sort(key=lambda x: -(x[1].get("cp") or 0))
    picks = []
    for sid, q, pos in stage1[:70]:
        M = measures.get(sid)
        if M is None:
            rows = history(sid)
            time.sleep(0.5)
            M = analyze(rows, q)
        v = buy_score(M)
        if not v:
            continue
        sym = sid.replace("s/", "").replace("a/TLV-", "").upper()
        picks.append({
            "id": sid, "symbol": sym, "market": "US" if sid.startswith("s/") else "TASE",
            "price": q["p"], "ex": q.get("ex"), "asof": q.get("u"),
            "sp500": sid.startswith("s/") and sym in sp500,
            "M": M, "score": v["score"], "of": v["of"], "reasons": v["reasons"],
        })
        if len(picks) >= 12:
            break

    picks.sort(key=lambda p: (-p["score"], -(p["M"].get("r3m") or 0)))
    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scanned": len(ids),
        "candidates": len(stage1),
        "ideas": picks[:5],
    }
    if not out["ideas"]:
        print("no qualifying buys today", flush=True)
    json.dump(out, open("data/ideas.json", "w"), ensure_ascii=False, separators=(",", ":"))
    print("wrote data/ideas.json with %d ideas" % len(out["ideas"]), flush=True)

if __name__ == "__main__":
    main()
