"""hl_watch.py - Live Hyperliquid position monitor for the insider cluster.
Checks the watched wallets every INTERVAL seconds and ALERTS (sound + log)
when a position opens / closes / flips - especially when a LONG opens.

Pure stdlib (winsound beep on Windows). No pip, no API key.
Run:   python hl_watch.py
Stop:  Ctrl + C
"""
import json
import time
import datetime
import urllib.request

INTERVAL = 120          # seconds between checks
LOGFILE = "hl_watch_log.txt"
HL = "https://api.hyperliquid.xyz/info"

# Wallets to watch (confirmed insider Hyperliquid accounts).
WATCH = [
    ("MAIN  0x20c2...44f5", "0x20c2d95a3dfdca9e9ad12794d5fa6fad99da44f5"),
    ("2ND   0x40e7f70D...", "0x40e7f70d8c5dbf7b27dab33ed826484b3c657e56"),
]

try:
    import winsound
    def beep():
        for _ in range(4):
            winsound.Beep(1100, 220)
            time.sleep(0.05)
except Exception:
    def beep():
        print("\a", end="", flush=True)


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(line):
    print(line, flush=True)
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_positions(addr):
    """Return (account_value, {coin: {...}}) or (None, None) on error."""
    req = urllib.request.Request(
        HL, data=json.dumps({"type": "clearinghouseState", "user": addr}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            st = json.load(r)
    except Exception as e:
        return None, None
    pos = {}
    for ap in st.get("assetPositions", []):
        p = ap["position"]
        szi = float(p.get("szi", 0) or 0)
        pos[p.get("coin")] = {
            "side": "LONG" if szi > 0 else "SHORT",
            "value": float(p.get("positionValue", 0) or 0),
            "entry": p.get("entryPx"),
            "pnl": float(p.get("unrealizedPnl", 0) or 0),
            "lev": p.get("leverage", {}).get("value"),
        }
    acct = float(st.get("marginSummary", {}).get("accountValue", 0) or 0)
    return acct, pos


def fmt(pos):
    if not pos:
        return "flat (pozisyon yok)"
    return " | ".join(
        "{} {} ${:,.0f} {}x uPnL ${:,.0f}".format(
            c, s["side"], s["value"], s["lev"], s["pnl"])
        for c, s in pos.items())


def diff(old, new):
    """Return list of human-readable change strings."""
    changes = []
    for coin, s in new.items():
        if coin not in old:
            changes.append("YENI {} {}  deger ${:,.0f}  {}x".format(
                s["side"], coin, s["value"], s["lev"]))
        elif old[coin]["side"] != s["side"]:
            changes.append("YON DEGISTI {}  {} -> {}".format(
                coin, old[coin]["side"], s["side"]))
    for coin, s in old.items():
        if coin not in new:
            changes.append("KAPANDI {} {}".format(s["side"], coin))
    return changes


def main():
    log("=" * 60)
    log("HL WATCH basladi {}  (her {} sn)  - durdurmak: Ctrl+C".format(now(), INTERVAL))
    for name, addr in WATCH:
        log("  izleniyor: {}  {}".format(name, addr))
    log("=" * 60)

    prev = {}
    first = True
    while True:
        for name, addr in WATCH:
            acct, pos = get_positions(addr)
            if pos is None:
                log("[{}] {}: API hatasi, atlandi".format(now(), name))
                continue

            line = "[{}] {}: {}  | hesap ${:,.0f}".format(now(), name, fmt(pos), acct)
            print(line, flush=True)

            if not first:
                for ch in diff(prev.get(name, {}), pos):
                    alert = ">>> ALARM [{}] {}: {}".format(now(), name, ch)
                    log(alert)
                    beep()
                    if "LONG" in ch:
                        log("    *** LONG ACILDI - COPY-TRADE FIRSATI ***")
            prev[name] = pos
        first = False
        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDurduruldu.")
