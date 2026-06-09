"""find_insider_longs.py
Follow the big USDC transfers out of the 0x20c2 insider cluster (2 hops deep on
Arbitrum) and report every connected wallet that currently holds an open
Hyperliquid position - flagging LONGs, and especially LONGs >= $49,000.

Needs a free Etherscan API key (https://etherscan.io/apis). No pip install.
Run:  python find_insider_longs.py
"""
import json
import time
import urllib.request
import urllib.parse

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
HL = "https://api.hyperliquid.xyz/info"
ARB = 42161

USDC_MIN = 100000.0       # follow USDC transfers >= this (token units)
LONG_MIN_USD = 49000.0    # highlight open LONGs with position value >= this
HOPS = 2                  # how many hops to follow the money
USDC_SYMBOLS = {"USDC", "USDC.e"}

SEEDS = [
    "0x20c2d95a3dfdca9e9ad12794d5fa6fad99da44f5",
    "0x40e7f70d8c5dbf7b27dab33ed826484b3c657e56",
    "0x511ccde9444216efc26e5744a0355eaebaaea82cb",
    "0x8ad9765c8613d3beb6fbfa9df44e5bd1de4934e1",
    "0x1e772565d78761d67796643941597c9f452da0d9",
]

# Not insider traders -> ignore as candidates (but still printed in flow).
TERMINALS = {
    "0xee7ae85f2fe2239e27d9c1e23fffe168d63b4055": "Binance HW34",
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


def hl_state(addr):
    body = json.dumps({"type": "clearinghouseState", "user": addr}).encode()
    req = urllib.request.Request(HL, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception:
        return None


def outgoing_usdc(addr, key):
    """List of (to_addr, amount) for USDC transfers FROM addr >= USDC_MIN."""
    params = urllib.parse.urlencode({
        "chainid": ARB, "module": "account", "action": "tokentx",
        "address": addr, "page": 1, "offset": 400, "sort": "desc", "apikey": key,
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
    for tx in data.get("result", []):
        if tx.get("tokenSymbol") not in USDC_SYMBOLS:
            continue
        if tx.get("from", "").lower() != addr.lower():
            continue
        try:
            val = int(tx["value"]) / (10 ** int(tx.get("tokenDecimal", 6)))
        except Exception:
            continue
        if val >= USDC_MIN:
            out.append((tx.get("to", "").lower(), val))
    return out


def main():
    key = input("Etherscan API key yapistir ve Enter: ").strip()
    if not key:
        print("Key bos, cikiliyor."); return

    print("\n[1] Buyuk USDC transferleri {} hop takip ediliyor...".format(HOPS))
    received = {}                 # addr -> max USDC received
    frontier = list(SEEDS)
    seen = set(s.lower() for s in SEEDS)

    for hop in range(HOPS):
        next_frontier = []
        for addr in frontier:
            for to_addr, amt in outgoing_usdc(addr, key):
                time.sleep(0.0)
                tag = TERMINALS.get(to_addr, "")
                if amt >= USDC_MIN:
                    print("   hop{}  {}  --{:,.0f} USDC-->  {} {}".format(
                        hop + 1, addr[:10] + "...", amt, to_addr[:12] + "...", tag))
                if to_addr in TERMINALS:
                    continue
                received[to_addr] = max(received.get(to_addr, 0), amt)
                if to_addr not in seen:
                    seen.add(to_addr)
                    next_frontier.append(to_addr)
            time.sleep(0.3)
        frontier = next_frontier

    candidates = [a for a in received if a not in [s.lower() for s in SEEDS]]
    print("\n[2] {} aday cuzdan Hyperliquid'de taraniyor...".format(len(candidates)))

    longs = []          # (addr, coin, value, received)
    for a in sorted(candidates, key=lambda x: -received[x]):
        st = hl_state(a)
        time.sleep(0.15)
        if not st:
            continue
        positions = st.get("assetPositions", [])
        acct = float(st.get("marginSummary", {}).get("accountValue", 0) or 0)
        if not positions and acct == 0:
            continue
        print("\n  {}   (aldigi: {:,.0f} USDC)".format(a, received[a]))
        print("    HL value: {:,.0f} USD".format(acct))
        for ap in positions:
            p = ap["position"]
            val = float(p.get("positionValue", 0) or 0)
            side = "LONG" if float(p.get("szi", 0) or 0) > 0 else "SHORT"
            print("    -> {} {}  value={:,.0f}  entry={}  uPnL={:,.0f}  lev={}x".format(
                p.get("coin"), side, val, p.get("entryPx"),
                float(p.get("unrealizedPnl", 0) or 0),
                p.get("leverage", {}).get("value")))
            if side == "LONG":
                flag = "  *** LONG >= $49k ***" if val >= LONG_MIN_USD else "  (long < $49k)"
                print("      " + flag.strip())
                if val >= LONG_MIN_USD:
                    longs.append((a, p.get("coin"), val, received[a]))

    print("\n" + "=" * 55)
    if longs:
        print("BAGLI CUZDANLARDA ACIK LONG (>= $49,000):")
        for a, coin, val, rec in sorted(longs, key=lambda x: -x[2]):
            print("  {}  {}  value={:,.0f} USD  (kumeden aldigi {:,.0f})".format(
                a, coin, val, rec))
    else:
        print("Bagli cuzdanlarda $49k uzeri acik LONG bulunamadi.")
    print("Bitti.")


if __name__ == "__main__":
    main()
