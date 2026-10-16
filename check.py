# -*- coding: utf-8 -*-
"""بررسی XAUUSD: RSI اشباع + واگرایی معمولی -> پیام تلگرام (اجرا روی GitHub Actions)"""
import json, os, time, requests
from datetime import datetime, timezone

RSI_LEN, SMA_LEN, OB, OS = 14, 14, 70, 30
PL, PR, RMIN, RMAX = 5, 5, 5, 60

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT = os.environ.get("CHAT_ID", "")
TDKEY = os.environ.get("TWELVEDATA_KEY", "")
TFS = [t.strip() for t in os.environ.get("TIMEFRAMES", "15m").split(",") if t.strip()]
STATE = "state.json"

# تایم‌فریم: (دقیقه، اینتروال TwelveData، اینتروال Yahoo، رنج Yahoo، ضریب تجمیع)
TF = {
 "1m": (1, "1min", "1m", "5d", 1), "2m": (2, "1min", "1m", "5d", 2), "3m": (3, "1min", "1m", "5d", 3),
 "5m": (5, "5min", "5m", "30d", 1), "10m": (10, "5min", "5m", "30d", 2), "15m": (15, "15min", "15m", "30d", 1),
 "30m": (30, "30min", "30m", "30d", 1), "1h": (60, "1h", "60m", "90d", 1), "2h": (120, "1h", "60m", "90d", 2),
 "3h": (180, "1h", "60m", "90d", 3), "4h": (240, "1h", "60m", "90d", 4), "6h": (360, "1h", "60m", "90d", 6),
 "12h": (720, "1h", "60m", "90d", 12), "1d": (1440, "1day", "1d", "2y", 1),
}

def api(method, **params):
    try:
        return requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", json=params, timeout=40).json()
    except Exception as e:
        print(method, "error:", e)
        return {}

def send(text, markup=None):
    print(text)
    if TOKEN and CHAT:
        p = {"chat_id": CHAT, "text": text}
        if markup:
            p["reply_markup"] = markup
        api("sendMessage", **p)

def fetch(tf):
    m, tdi, yi, yr, f = TF[tf]
    cs = []
    if TDKEY:
        size = min(5000, 160 * f + f)
        j = requests.get("https://api.twelvedata.com/time_series", params={
            "symbol": "XAU/USD", "interval": tdi, "outputsize": size, "order": "ASC",
            "timezone": "UTC", "apikey": TDKEY}, timeout=30).json()
        if j.get("status") == "error":
            raise RuntimeError(j.get("message"))
        for v in j["values"]:
            d = v["datetime"]
            d = d + "T00:00:00" if len(d) == 10 else d.replace(" ", "T")
            t = int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp())
            cs.append([t, float(v["open"]), float(v["high"]), float(v["low"]), float(v["close"])])
    else:
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD=X",
                         params={"interval": yi, "range": yr},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=30).json()["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        for t, o, h, l, c in zip(r["timestamp"], q["open"], q["high"], q["low"], q["close"]):
            if None not in (o, h, l, c):
                cs.append([t, o, h, l, c])
    if f > 1:
        size, out = m * 60, []
        for t, o, h, l, c in cs:
            b = t // size * size
            if out and out[-1][0] == b:
                out[-1][2] = max(out[-1][2], h); out[-1][3] = min(out[-1][3], l); out[-1][4] = c
            else:
                out.append([b, o, h, l, c])
        cs = out
    return cs[:-1]  # کندل در حال تشکیل حذف می‌شود

def rsi_calc(c, n):
    out = [None] * len(c)
    if len(c) <= n: return out
    g = l = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i-1]; g += max(d, 0); l += max(-d, 0)
    ag, al = g / n, l / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(c)):
        d = c[i] - c[i-1]
        ag = (ag * (n-1) + max(d, 0)) / n; al = (al * (n-1) + max(-d, 0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out

def is_piv(v, i, k):
    if i - PL < 0 or i + PR >= len(v): return False
    w = v[i-PL:i+PR+1]
    if any(x is None for x in w): return False
    return v[i] == (max(w) if k == "h" else min(w))

def prev_piv(v, i, k):
    for j in range(i - RMIN, max(i - RMAX, PL) - 1, -1):
        if is_piv(v, j, k): return j
    return None

def fmt(t): return datetime.fromtimestamp(t, timezone.utc).strftime("%m-%d %H:%M")

def analyze(tf, sent):
    cs = fetch(tf)
    if len(cs) < RSI_LEN + RMAX + 20:
        print(tf, "داده کافی نیست"); return None
    cl = [c[4] for c in cs]; hi = [c[2] for c in cs]; lo = [c[3] for c in cs]
    r = rsi_calc(cl, RSI_LEN); n = len(cs); i = n - 1 - PR
    ma = sum(r[-SMA_LEN:]) / SMA_LEN
    print(f"{tf}: price {cl[-1]:.2f} RSI {r[-1]:.1f}")
    res = (cl[-1], r[-1], ma)
    found = []
    if is_piv(r, i, "h") and r[i] >= OB:
        j = prev_piv(r, i, "h")
        if j is not None and hi[i] > hi[j] and r[i] < r[j]:
            found.append(("🔴 واگرایی نزولی + اشباع خرید (احتمال ریزش)", "h", i, j, hi[i], hi[j]))
    if is_piv(r, i, "l") and r[i] <= OS:
        j = prev_piv(r, i, "l")
        if j is not None and lo[i] < lo[j] and r[i] > r[j]:
            found.append(("🟢 واگرایی صعودی + اشباع فروش (احتمال رشد)", "l", i, j, lo[i], lo[j]))
    for title, k, i, j, pn, po in found:
        key = f"{tf}|{k}|{cs[i][0]}"
        if key in sent: continue
        sent.append(key)
        send(f"{title}\nXAUUSD | تایم‌فریم: {tf}\nقیمت: {cl[-1]:.2f}\nRSI: {r[-1]:.1f} | MA: {ma:.1f}\n"
             f"پیووت جدید: {fmt(cs[i][0])} UTC → قیمت {pn:.2f} | RSI {r[i]:.1f}\n"
             f"پیووت قبلی: {fmt(cs[j][0])} UTC → قیمت {po:.2f} | RSI {r[j]:.1f}")
    return res

ORDER = ["1m", "2m", "3m", "5m", "10m", "15m", "30m", "1h", "2h", "3h", "4h", "6h", "12h", "1d"]

def keyboard(st):
    rows, row = [], []
    for t in ORDER:
        row.append({"text": ("✅ " if t in st["tfs"] else "") + t, "callback_data": "tf:" + t})
        if len(row) == 4:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([{"text": "📊 وضعیت و RSI", "callback_data": "status"},
                 {"text": "▶️ ادامه هشدار" if st.get("paused") else "⏸ توقف هشدار", "callback_data": "toggle"}])
    return {"inline_keyboard": rows}

def menu_text(st):
    return ("⚙️ تنظیمات ربات XAUUSD\n"
            "روی هر تایم‌فریم بزنید تا روشن (✅) یا خاموش شود.\n"
            f"وضعیت: {'⏸ متوقف' if st.get('paused') else '▶️ فعال'}\n"
            f"تایم‌فریم‌ها: {', '.join(st['tfs'])}")

def status_text(st):
    lines = []
    for tf in st["tfs"]:
        try:
            r = analyze(tf, [])
            lines.append(f"{tf}: قیمت {r[0]:.2f} | RSI {r[1]:.1f} | MA {r[2]:.1f}" if r else f"{tf}: داده کافی نیست")
        except Exception as e:
            lines.append(f"{tf}: خطا در دریافت داده")
    return "\n".join(lines)

def refresh_menu(st, msg):
    api("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
        text=menu_text(st), reply_markup=keyboard(st))

def tg_commands(st, wait=0):
    """دستورها و دکمه‌های تلگرام"""
    global CHAT
    if not TOKEN:
        return
    ups = api("getUpdates", offset=st.get("offset", 0), timeout=wait,
              allowed_updates=["message", "callback_query"]).get("result", [])
    for u in ups:
        st["offset"] = u["update_id"] + 1
        cq = u.get("callback_query")
        m = cq["message"] if cq else (u.get("message") or {})
        if not m:
            continue
        chat = str(m["chat"]["id"])
        if st.get("chat_id") and chat != st["chat_id"]:
            continue  # فقط صاحب ربات
        st["chat_id"] = CHAT = chat

        if cq:  # ---- دکمه‌ها
            d = cq.get("data", "")
            note = None
            if d.startswith("tf:"):
                t = d[3:]
                if t in st["tfs"]:
                    if len(st["tfs"]) > 1: st["tfs"].remove(t)
                    else: note = "حداقل یک تایم‌فریم لازم است"
                elif t in TF:
                    st["tfs"] = [x for x in ORDER if x in st["tfs"] or x == t]
                refresh_menu(st, m)
            elif d == "toggle":
                st["paused"] = not st.get("paused", False)
                refresh_menu(st, m)
            elif d == "status":
                send(status_text(st))
            api("answerCallbackQuery", callback_query_id=cq["id"], **({"text": note} if note else {}))
            continue

        text = (m.get("text") or "").strip()  # ---- دستورها
        if not text.startswith("/"):
            continue
        parts = text.split(); cmd = parts[0].split("@")[0].lower()
        if cmd in ("/start", "/menu"):
            send(menu_text(st), keyboard(st))
        elif cmd == "/tf" and len(parts) > 1:
            new = [p.lower() for p in parts[1:] if p.lower() in TF]
            if new:
                st["tfs"] = [x for x in ORDER if x in new]; send("✅ تایم‌فریم: " + ", ".join(st["tfs"]))
        elif cmd == "/status":
            send(status_text(st))
        elif cmd == "/pause":
            st["paused"] = True; send("⏸ متوقف شد")
        elif cmd == "/resume":
            st["paused"] = False; send("▶️ ادامه یافت")
        else:
            send(menu_text(st), keyboard(st))
    if ups:  # تأیید دریافت در خود تلگرام تا تکرار نشوند
        api("getUpdates", offset=st["offset"], timeout=0)

def scan(st):
    if st.get("paused"):
        return
    for tf in st["tfs"]:
        try:
            analyze(tf, st["sent"])
        except Exception as e:
            print("خطا", tf, e)

def main():
    global CHAT
    try:
        st = json.load(open(STATE))
    except Exception:
        st = {}
    st.setdefault("sent", []); st.setdefault("offset", 0); st.setdefault("paused", False)
    st.setdefault("tfs", [t for t in TFS if t in TF] or ["15m"])
    if st.get("chat_id") and not CHAT:
        CHAT = st["chat_id"]
    end = time.time() + int(os.environ.get("LOOP_SECONDS", "230"))
    tg_commands(st, 0)
    if os.environ.get("EVENT") == "workflow_dispatch":
        send(f"✅ ربات ابری فعال است. تایم‌فریم: {', '.join(st['tfs'])}")
    scan(st)
    # تا پایان این اجرا منتظر دکمه‌ها می‌ماند تا پاسخ تقریباً فوری باشد
    while TOKEN and time.time() < end - 2:
        tg_commands(st, int(min(20, max(1, end - time.time()))))
    st["sent"] = st["sent"][-300:]
    json.dump(st, open(STATE, "w"))

if __name__ == "__main__":
    main()
