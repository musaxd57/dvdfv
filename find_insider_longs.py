"""find_insider_longs.py
Map the money network around the 0x20c2 insider cluster on Arbitrum and find
every CONNECTED wallet that has Hyperliquid LONG activity - whether the long is
open NOW (flagged >= $49,000) or was opened earlier and already closed.

Logic:
  1. From the seed cluster, collect counterparties of USDC transfers >= $49k
     (both directions), 2 hops deep. Binance / bridge / decoys are terminals.
  2. For each connected wallet, query Hyperliquid: open positions + fill history.
  3. Report: (A) open LONGs >= $49k, (B) wallets that opened LONGs before,
     (C) connected HL traders currently flat.

Needs a free Etherscan API key (https://etherscan.io/apis). No pip install.
Run:  python find_insider_longs.py
"""
import json
import time
import datetime
import urllib.request
import urllib.parse
from collections import defaultdict

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
HL = "https://api.hyperliquid.xyz/info"
ARB = 42161

USDC_MIN = 49000.0        # follow USDC transfers >= this
LONG_MIN_USD = 49000.0    # flag open LONGs with position value >= this
HOPS = 2
MAX_SCAN = 100            # cap candidates scanned on HL
USDC_SYMBOLS = {"USDC", "USDC.e"}

SEEDS = [
    "0x20c2d95a3dfdca9e9ad12794d5fa6fad99da44f5",
    "0x40e7f70d8c5dbf7b27dab33ed826484b3c657e56",
    "0x511ccde9444216efc26e5744a0355eaebaaea82cb",
    "0x8ad9765c8613d3beb6fbfa9df44e5bd1de4934e1",
    "0x1e772565d78761d67796643941597c9f452da0d9",
]

# Terminals: exchanges / bridge / decoys -> never insider traders, never expand.
TERMINALS = {
    "0xee7ae85f2fe2239e27d9c1e23fffe168d63b4055": "Binance HW34",
    "0xb38e8c17e38363af6ebdcb3dae12e0243582891d": "Binance",
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance 14",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "Binance 15",
    "0xdfd5293d8e347dfe59e90efd55b2956a1343963d": "Binance 16",
    "0x25681ab599b4e2ceea31f8b498052c53fc2d74db": "Binance 94",
    "0xa74e8ae2f83d2564af25420ad4d6a7fe224b053f": "Binance US 9",
    "0x2df1c51e09aecf9cacb7bc98cb1742757f163df7": "Hyperliquid bridge",
    "0x0000000000000000000000000000000000000000": "null",
    "0x511cd5a8644ce7cc96eaab1938e873f4e03e82cb": "DECOY",
    "0xee7a8a1898bd47592aa1062e4f60608c993b4055": "DECOY",
    "0x40e7fb7ddcaee8e4bcb66180a350c00b3c657e56": "DECOY",
    "0x2df17470c5de6a5d2d41feb8fcf5fb0deeb43df7": "phishing",
}
SEED_SET = set(s.lower() for s in SEEDS)


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def hl_post(req_type, addr, extra=None):
    payload = {"type": req_type, "user": addr}
    if extra:
        payload.update(extra)
    req = urllib.request.Request(HL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception:
        return None


def usdc_edges(addr, key):
    """Return list of (other_addr, amount, direction) for USDC tx >= USDC_MIN."""
    params = urllib.parse.urlencode({
        "chainid": ARB, "module": "account", "action": "tokentx",
        "address": addr, "page": 1, "offset": 1000, "sort": "desc", "apikey": key,
    })
    for _ in range(3):
        try:
            data = get_json(ETHERSCAN_V2 + "?" + params)
        except Exception as e:
            print("   etherscan error:", e); return []
        if str(data.get("status")) == "1":
            break
        if "rate" in str(data.get("result", "")).lower():
            time.sleep(1.2); continue
        return []
    edges = []
    al = addr.lower()
    for tx in data.get("result", []):
        if tx.get("tokenSymbol") not in USDC_SYMBOLS:
            continue
        try:
            val = int(tx["value"]) / (10 ** int(tx.get("tokenDecimal", 6)))
        except Exception:
            continue
        if val < USDC_MIN:
            continue
        frm, to = tx.get("from", "").lower(), tx.get("to", "").lower()
        if frm == al and to:
            edges.append((to, val, "out"))
        elif to == al and frm:
            edges.append((frm, val, "in"))
    return edges


def ts(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def main():
    key = input("Etherscan API key yapistir ve Enter: ").strip()
    if not key:
        print("Key bos, cikiliyor."); return

    print("\n[1] Para agi {} hop cikariliyor (>= ${:,.0f} USDC)...".format(HOPS, USDC_MIN))
    flows = defaultdict(lambda: [0.0, 0])     # (from,to) -> [total, count]
    received = defaultdict(float)             # addr -> max amount seen
    frontier = list(SEED_SET)
    seen = set(SEED_SET)

    for hop in range(HOPS):
        nxt = []
        for addr in frontier:
            for other, amt, direction in usdc_edges(addr, key):
                if direction == "out":
                    flows[(addr, other)][0] += amt
                    flows[(addr, other)][1] += 1
                received[other] = max(received[other], amt)
                if other in TERMINALS:
                    continue
                if other not in seen:
                    seen.add(other)
                    nxt.append(other)
            time.sleep(0.3)
        frontier = nxt

    # show aggregated top money destinations
    print("\n   Paranin gittigi baslica adresler:")
    top = sorted(flows.items(), key=lambda x: -x[1][0])[:15]
    for (frm, to), (tot, cnt) in top:
        tag = TERMINALS.get(to, "")
        print("     {} -> {} {}  TOPLAM {:,.0f} USDC ({} tx)".format(
            frm[:10] + "...", to[:12] + "...", "[" + tag + "]" if tag else "", tot, cnt))

    candidates = [a for a in received
                  if a not in SEED_SET and a not in TERMINALS]
    candidates.sort(key=lambda x: -received[x])
    candidates = candidates[:MAX_SCAN]
    print("\n[2] {} bagli cuzdan Hyperliquid'de taraniyor...".format(len(candidates)))

    open_longs, past_longs, flat_traders = [], [], []
    for a in candidates:
        st = hl_post("clearinghouseState", a)
        time.sleep(0.12)
        if not st:
            continue
        positions = st.get("assetPositions", [])
        acct = float(st.get("marginSummary", {}).get("accountValue", 0) or 0)
        fills = hl_post("userFills", a) or []
        time.sleep(0.12)
        if not positions and acct == 0 and not fills:
            continue  # never touched Hyperliquid

        cur_long = None
        for ap in positions:
            p = ap["position"]
            if float(p.get("szi", 0) or 0) > 0:
                cur_long = (p.get("coin"), float(p.get("positionValue", 0) or 0),
                            p.get("entryPx"), float(p.get("unrealizedPnl", 0) or 0))
        opened_longs = [f for f in fills if "Open Long" in f.get("dir", "")]

        print("\n  {}   (kumeden ~{:,.0f} USDC)".format(a, received[a]))
        print("    HL value: {:,.0f} USD | fills: {} | Open-Long fills: {}".format(
            acct, len(fills), len(opened_longs)))
        for ap in positions:
            p = ap["position"]
            side = "LONG" if float(p.get("szi", 0) or 0) > 0 else "SHORT"
            print("    -> {} {} value={:,.0f} entry={} uPnL={:,.0f}".format(
                p.get("coin"), side, float(p.get("positionValue", 0) or 0),
                p.get("entryPx"), float(p.get("unrealizedPnl", 0) or 0)))

        if cur_long and cur_long[1] >= LONG_MIN_USD:
            print("      *** ACIK LONG >= $49k ***")
            open_longs.append((a, cur_long, received[a]))
        elif opened_longs:
            last = max(opened_longs, key=lambda x: x.get("time", 0))
            print("      (gecmiste LONG acmis, son: {} {})".format(
                ts(last.get("time", 0)), last.get("coin")))
            past_longs.append((a, last.get("coin"), ts(last.get("time", 0))))
        else:
            flat_traders.append(a)

    # ---- final report ----
    print("\n" + "=" * 58)
    print("A) ACIK LONG (>= $49,000) BAGLI CUZDANLAR:")
    if open_longs:
        for a, (coin, val, entry, pnl), rec in sorted(open_longs, key=lambda x: -x[1][1]):
            print("   {}  {} value={:,.0f} entry={} uPnL={:,.0f}".format(a, coin, val, entry, pnl))
    else:
        print("   (yok)")
    print("\nB) GECMISTE LONG ACMIS (simdi kapali) BAGLI CUZDANLAR:")
    if past_longs:
        for a, coin, d in past_longs:
            print("   {}  son long: {} {}".format(a, coin, d))
    else:
        print("   (yok)")
    print("\nC) BAGLI HL TRADER (su an flat): {} adet".format(len(flat_traders)))
    for a in flat_traders:
        print("   " + a)
    print("\nBitti.")


if __name__ == "__main__":
    main()
