"""watch_once.py - ONE monitoring pass, for GitHub Actions (cron).

Detects when the insider cluster funds a FRESH wallet (>= NEW_FUND_MIN USDC)
and when any watched wallet opens / flips a Hyperliquid position (esp. LONG).
Alerts go to Telegram. State persists in chain_watch_state.json (the workflow
commits it back so the next run remembers what it already saw).

Config via environment variables:
  ETHERSCAN_API_KEY   (required)
  TELEGRAM_BOT_TOKEN  (optional - needed for phone alerts)
  TELEGRAM_CHAT_ID    (optional)

Pure stdlib.
"""
import os
import json
import time
import datetime
import urllib.request
import urllib.parse

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
HL = "https://api.hyperliquid.xyz/info"
ARB = 42161

NEW_FUND_MIN = 10000.0
RECENT = 60
STATE_FILE = "chain_watch_state.json"
USDC_SYMBOLS = {"USDC", "USDC.e"}

KEY = os.environ.get("ETHERSCAN_API_KEY", "").strip()
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

SEEDS = [
    "0x20c2d95a3dfdca9e9ad12794d5fa6fad99da44f5",
    "0x40e7f70d8c5dbf7b27dab33ed826484b3c657e56",
    "0x511ccde9444216efc26e5744a0355eaebaaea82cb",
    "0x8ad9765c8613d3beb6fbfa9df44e5bd1de4934e1",
    "0x1e772565d78761d67796643941597c9f452da0d9",
]

IGNORE = {
    "0xee7ae85f2fe2239e27d9c1e23fffe168d63b4055",
    "0xb38e8c17e38363af6ebdcb3dae12e0243582891d",
    "0x28c6c06298d514db089934071355e5743bf21d60",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549",
    "0xdfd5293d8e347dfe59e90efd55b2956a1343963d",
    "0x25681ab599b4e2ceea31f8b498052c53fc2d74db",
    "0xa74e8ae2f83d2564af25420ad4d6a7fe224b053f",
    "0x2df1c51e09aecf9cacb7bc98cb1742757f163df7",
    "0x0000000000000000000000000000000000000000",
    "0x511cd5a8644ce7cc96eaab1938e873f4e03e82cb",
    "0xee7a8a1898bd47592aa1062e4f60608c993b4055",
    "0x40e7fb7ddcaee8e4bcb66180a350c00b3c657e56",
    "0x2df17470c5de6a5d2d41feb8fcf5fb0deeb43df7",
}
IGNORE |= set(SEEDS)


def now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def tg(text):
    print("ALERT:", text.replace("\n", " | "))
    if not (TG_TOKEN and TG_CHAT):
        return
    url = "https://api.telegram.org/bot{}/sendMessage".format(TG_TOKEN)
    data = urllib.parse.urlencode({
        "chat_id": TG_CHAT, "text": text, "disable_web_page_preview": "true",
    }).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20).read()
    except Exception as e:
        print("telegram error:", e)


def recent_out_usdc(addr):
    params = urllib.parse.urlencode({
        "chainid": ARB, "module": "account", "action": "tokentx",
        "address": addr, "page": 1, "offset": RECENT, "sort": "desc", "apikey": KEY,
    })
    try:
        with urllib.request.urlopen(ETHERSCAN_V2 + "?" + params, timeout=30) as r:
            data = json.load(r)
    except Exception as e:
        print("etherscan error", addr[:10], e)
        return []
    if str(data.get("status")) != "1":
        return []
    out = []
    al = addr.lower()
    for tx in data.get("result", []):
        if tx.get("tokenSymbol") not in USDC_SYMBOLS:
            continue
        if tx.get("from", "").lower() != al:
            continue
        try:
            val = int(tx["value"]) / (10 ** int(tx.get("tokenDecimal", 6)))
        except Exception:
            continue
        out.append((tx.get("hash"), tx.get("to", "").lower(), val))
    return out


def hl_positions(addr):
    req = urllib.request.Request(
        HL, data=json.dumps({"type": "clearinghouseState", "user": addr}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            st = json.load(r)
    except Exception:
        return None
    pos = {}
    for ap in st.get("assetPositions", []):
        p = ap["position"]
        szi = float(p.get("szi", 0) or 0)
        pos[p.get("coin")] = {
            "side": "LONG" if szi > 0 else "SHORT",
            "value": round(float(p.get("positionValue", 0) or 0)),
            "lev": p.get("leverage", {}).get("value"),
        }
    return pos


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"seen_tx": [], "watched_extra": [], "baseline": False, "prev_pos": {}}


def save_state(s):
    s["seen_tx"] = s["seen_tx"][-6000:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=0, sort_keys=True)


def main():
    if not KEY:
        print("ETHERSCAN_API_KEY yok, cikiliyor."); return

    s = load_state()
    seen = set(s["seen_tx"])
    watched_extra = list(s["watched_extra"])
    prev_pos = s.get("prev_pos", {})
    first_run = not s["baseline"]

    # 1) chain: fresh-wallet funding
    for addr in SEEDS + watched_extra:
        for h, to, amt in recent_out_usdc(addr):
            if h in seen:
                continue
            seen.add(h)
            if first_run:
                continue
            if to in IGNORE or to in watched_extra:
                continue
            if amt >= NEW_FUND_MIN:
                watched_extra.append(to)
                tg("YENI CUZDAN FONLANDI\n{}\n{} --{:,.0f} USDC--> {}\nizlemeye alindi.".format(
                    now(), addr, amt, to))
        time.sleep(0.25)

    # 2) HL: position changes
    for addr in SEEDS + watched_extra:
        pos = hl_positions(addr)
        if pos is None:
            continue
        old = prev_pos.get(addr, {})
        for coin, p in pos.items():
            if coin not in old:
                msg = "YENI POZISYON {} {}\n{}\ndeger ${:,.0f}  {}x\ncuzdan {}".format(
                    p["side"], coin, now(), p["value"], p["lev"], addr)
                if p["side"] == "LONG":
                    msg = "*** LONG ACILDI ***\n" + msg
                tg(msg)
            elif old[coin]["side"] != p["side"]:
                tg("YON DEGISTI {}  {} -> {}\n{}\ncuzdan {}".format(
                    coin, old[coin]["side"], p["side"], now(), addr))
        prev_pos[addr] = pos

    if first_run:
        tg("Monitor kuruldu ve baslatildi ({}).\n{} kume cuzdani izleniyor. "
           "Bundan sonra yeni cuzdan fonlanmasi / LONG acilmasi bildirilecek.".format(
               now(), len(SEEDS)))

    s["seen_tx"] = sorted(seen)
    s["watched_extra"] = watched_extra
    s["prev_pos"] = prev_pos
    s["baseline"] = True
    save_state(s)
    print("[{}] pass ok. extra watched: {}".format(now(), len(watched_extra)))


if __name__ == "__main__":
    main()
