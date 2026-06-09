"""find_insider_longs.py  (v3)
Follow the insider money network on Arbitrum up to 3 hops, SKIPPING exchange
pools (Binance) because the trail is unattributable past them, and only
following the biggest outflows of any pool-like node. For every connected,
non-exchange wallet, check Hyperliquid: open LONGs (flagged >= $49k) and
historically opened longs.

Needs a free Etherscan API key (https://etherscan.io/apis). No pip install.
Run:  python find_insider_longs.py
"""
import json
import time
import datetime
import urllib.request
import urllib.parse
from collections import defaultdict, deque

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
HL = "https://api.hyperliquid.xyz/info"
ARB = 42161

USDC_MIN = 49000.0        # follow USDC transfers >= this
LONG_MIN_USD = 49000.0    # flag open LONGs >= this position value
HOPS = 3
MAX_FETCH = 70            # max Etherscan address-pulls (rate/quota guard)
POOL_FANOUT = 30          # > this many USDC counterparties => treat as pool
POOL_TOP_KEEP = 6         # for a pool, only follow its biggest N outflows
USDC_SYMBOLS = {"USDC", "USDC.e"}

SEEDS = [
    "0x20c2d95a3dfdca9e9ad12794d5fa6fad99da44f5",
    "0x40e7f70d8c5dbf7b27dab33ed826484b3c657e56",
    "0x511ccde9444216efc26e5744a0355eaebaaea82cb",
    "0x8ad9765c8613d3beb6fbfa9df44e5bd1de4934e1",
    "0x1e772565d78761d67796643941597c9f452da0d9",
]

# Exchange pools / bridge / decoys -> terminal: never expand, never a candidate.
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


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def hl_post(req_type, addr):
    req = urllib.request.Request(
        HL, data=json.dumps({"type": req_type, "user": addr}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception:
        return None


def usdc_out_edges(addr, key):
    """USDC transfers FROM addr >= USDC_MIN -> list of (to_addr, amount)."""
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
        if val >= USDC_MIN and tx.get("to"):
            out.append((tx["to"].lower(), val))
    return out


def ts(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def main():
    key = input("Etherscan API key yapistir ve Enter: ").strip()
    if not key:
        print("Key bos, cikiliyor."); return
    custom = input("Baska bir baslangic adresi? (bos birak = varsayilan kume): ").strip().lower()
    seeds = [custom] if custom.startswith("0x") and len(custom) == 42 else SEEDS

    print("\n[1] Para agi {} hop takip ediliyor (havuzlar atlanir)...".format(HOPS))
    received = defaultdict(float)
    flows = defaultdict(lambda: [0.0, 0])
    seen = set(seeds)
    queue = deque((s, 0) for s in seeds)
    fetched = 0

    while queue and fetched < MAX_FETCH:
        addr, depth = queue.popleft()
        if depth >= HOPS:
            continue
        edges = usdc_out_edges(addr, key)
        fetched += 1
        time.sleep(0.25)

        agg = defaultdict(float)
        for to_addr, amt in edges:
            agg[to_addr] += amt
            flows[(addr, to_addr)][0] += amt
            flows[(addr, to_addr)][1] += 1
            received[to_addr] = max(received[to_addr], amt)

        items = sorted(agg.items(), key=lambda x: -x[1])
        is_pool = len(agg) > POOL_FANOUT
        if is_pool:
            items = items[:POOL_TOP_KEEP]
            print("   {} havuz-benzeri ({} alici) -> sadece en buyuk {} takip".format(
                addr[:10] + "...", len(agg), POOL_TOP_KEEP))
        for to_addr, amt in items:
            if to_addr in TERMINALS or to_addr in seen:
                continue
            seen.add(to_addr)
            queue.append((to_addr, depth + 1))

    print("   ({} adres tarandi)".format(fetched))
    print("\n   Baslica para akislari:")
    for (frm, to), (tot, cnt) in sorted(flows.items(), key=lambda x: -x[1][0])[:15]:
        tag = TERMINALS.get(to, "")
        print("     {} -> {} {}  {:,.0f} USDC ({}tx)".format(
            frm[:10] + "...", to[:12] + "...", "[" + tag + "]" if tag else "", tot, cnt))

    candidates = [a for a in received if a not in TERMINALS and a not in set(seeds)]
    candidates.sort(key=lambda x: -received[x])
    print("\n[2] {} bagli (borsa-disi) cuzdan Hyperliquid'de taraniyor...".format(len(candidates)))

    open_longs, past_longs, flat = [], [], []
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
            continue

        cur_long = None
        for ap in positions:
            p = ap["position"]
            if float(p.get("szi", 0) or 0) > 0:
                cur_long = (p.get("coin"), float(p.get("positionValue", 0) or 0),
                            p.get("entryPx"), float(p.get("unrealizedPnl", 0) or 0))
        opened = [f for f in fills if "Open Long" in f.get("dir", "")]

        print("\n  {}  (~{:,.0f} USDC aldi)".format(a, received[a]))
        print("    HL value: {:,.0f} | fills: {} | Open-Long: {}".format(
            acct, len(fills), len(opened)))
        for ap in positions:
            p = ap["position"]
            side = "LONG" if float(p.get("szi", 0) or 0) > 0 else "SHORT"
            print("    -> {} {} value={:,.0f} entry={} uPnL={:,.0f}".format(
                p.get("coin"), side, float(p.get("positionValue", 0) or 0),
                p.get("entryPx"), float(p.get("unrealizedPnl", 0) or 0)))

        if cur_long and cur_long[1] >= LONG_MIN_USD:
            print("      *** ACIK LONG >= $49k ***")
            open_longs.append((a, cur_long, received[a]))
        elif opened:
            last = max(opened, key=lambda x: x.get("time", 0))
            past_longs.append((a, last.get("coin"), ts(last.get("time", 0))))
        else:
            flat.append(a)

    print("\n" + "=" * 58)
    print("A) ACIK LONG (>= $49,000) BAGLI CUZDANLAR:")
    for a, (coin, val, entry, pnl), rec in sorted(open_longs, key=lambda x: -x[1][1]):
        print("   {}  {} value={:,.0f} entry={} uPnL={:,.0f}".format(a, coin, val, entry, pnl))
    if not open_longs:
        print("   (yok)")
    print("\nB) GECMISTE LONG ACMIS BAGLI CUZDANLAR:")
    for a, coin, d in past_longs:
        print("   {}  son long: {} {}".format(a, coin, d))
    if not past_longs:
        print("   (yok)")
    print("\nC) BAGLI HL TRADER (su an flat): {} adet".format(len(flat)))
    for a in flat:
        print("   " + a)
    print("\nBitti.")


if __name__ == "__main__":
    main()
