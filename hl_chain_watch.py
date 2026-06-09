"""hl_chain_watch.py - Self-expanding on-chain + Hyperliquid monitor.

Watches the insider cluster on Arbitrum. When a watched wallet sends USDC to a
FRESH wallet (not an exchange/bridge/known address), it alerts and starts
watching that new wallet too - then alerts again if the new wallet opens a
Hyperliquid position (especially a LONG). This catches the move to a clean
trading wallet before the crowd.

Needs a free Etherscan API key. No pip install.
Run:   python hl_chain_watch.py       Stop: Ctrl + C
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

INTERVAL = 180            # seconds between full sweeps
NEW_FUND_MIN = 10000.0    # USDC: a transfer >= this to a fresh wallet = lead
RECENT = 60               # how many recent token-tx to pull per wallet
STATE_FILE = "chain_watch_state.json"
LOGFILE = "chain_watch_log.txt"
USDC_SYMBOLS = {"USDC", "USDC.e"}

SEEDS = [
    "0x20c2d95a3dfdca9e9ad12794d5fa6fad99da44f5",
    "0x40e7f70d8c5dbf7b27dab33ed826484b3c657e56",
    "0x511ccde9444216efc26e5744a0355eaebaaea82cb",
    "0x8ad9765c8613d3beb6fbfa9df44e5bd1de4934e1",
    "0x1e772565d78761d67796643941597c9f452da0d9",
]

# Ignore as "fresh wallet": exchanges, bridge, decoys, the cluster's own funnel.
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

try:
    import winsound
    def beep(n=4):
        for _ in range(n):
            winsound.Beep(1100, 220); time.sleep(0.05)
except Exception:
    def beep(n=4):
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


def recent_out_usdc(addr, key):
    """Recent outgoing USDC transfers: list of (hash, to, amount, datestr)."""
    params = urllib.parse.urlencode({
        "chainid": ARB, "module": "account", "action": "tokentx",
        "address": addr, "page": 1, "offset": RECENT, "sort": "desc", "apikey": key,
    })
    try:
        with urllib.request.urlopen(ETHERSCAN_V2 + "?" + params, timeout=30) as r:
            data = json.load(r)
    except Exception as e:
        log("   etherscan error ({}): {}".format(addr[:10], e))
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
        d = datetime.datetime.fromtimestamp(int(tx.get("timeStamp", 0))).strftime("%Y-%m-%d %H:%M")
        out.append((tx.get("hash"), tx.get("to", "").lower(), val, d))
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
            "value": float(p.get("positionValue", 0) or 0),
            "lev": p.get("leverage", {}).get("value"),
            "pnl": float(p.get("unrealizedPnl", 0) or 0),
        }
    return pos


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                s = json.load(f)
            return set(s.get("seen_tx", [])), s.get("watched_extra", []), s.get("baseline", False)
        except Exception:
            pass
    return set(), [], False


def save_state(seen_tx, watched_extra, baseline):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"seen_tx": list(seen_tx)[-5000:],
                       "watched_extra": watched_extra,
                       "baseline": baseline}, f)
    except Exception:
        pass


def main():
    key = input("Etherscan API key yapistir ve Enter: ").strip()
    if not key:
        print("Key bos."); return

    seen_tx, watched_extra, baseline = load_state()
    prev_pos = {}

    log("=" * 60)
    log("ZINCIR IZLEYICI basladi {}  (her {} sn)".format(now(), INTERVAL))
    log("Yeni cuzdana >= ${:,.0f} USDC cikisinda ALARM. Durdur: Ctrl+C".format(NEW_FUND_MIN))
    if not baseline:
        log("Ilk tur: mevcut gecmis baz aliniyor (alarm yok), sonra yeni transferler izlenir.")
    log("=" * 60)

    while True:
        watch_addrs = SEEDS + watched_extra

        # 1) chain: detect funding of fresh wallets
        for addr in SEEDS + watched_extra:
            for h, to, amt, d in recent_out_usdc(addr, key):
                if h in seen_tx:
                    continue
                seen_tx.add(h)
                if not baseline:
                    continue
                if to in IGNORE or to in watched_extra:
                    continue
                if amt >= NEW_FUND_MIN:
                    log(">>> YENI CUZDAN FONLANDI [{}]".format(now()))
                    log("    {}  --{:,.0f} USDC-->  {}   ({})".format(addr[:12] + "...", amt, to, d))
                    log("    -> izleme listesine eklendi, Hyperliquid kontrol edilecek")
                    beep()
                    watched_extra.append(to)
            time.sleep(0.25)
        baseline = True

        # 2) HL: alert on position changes for everyone we watch
        for addr in watch_addrs:
            pos = hl_positions(addr)
            if pos is None:
                continue
            old = prev_pos.get(addr, {})
            for coin, s in pos.items():
                if coin not in old:
                    log(">>> ALARM [{}] {}  YENI {} {}  ${:,.0f} {}x".format(
                        now(), addr[:12] + "...", s["side"], coin, s["value"], s["lev"]))
                    beep()
                    if s["side"] == "LONG":
                        log("    *** LONG ACILDI - {} ${:,.0f} {}x - COPY FIRSATI ***".format(
                            coin, s["value"], s["lev"]))
                elif old[coin]["side"] != s["side"]:
                    log(">>> ALARM [{}] {}  {} YON: {} -> {}".format(
                        now(), addr[:12] + "...", coin, old[coin]["side"], s["side"]))
                    beep()
            prev_pos[addr] = pos

        save_state(seen_tx, watched_extra, baseline)
        print("[{}] tur bitti. Izlenen: {} kume + {} yeni cuzdan.".format(
            now(), len(SEEDS), len(watched_extra)), flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDurduruldu.")
