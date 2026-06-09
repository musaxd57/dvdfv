"""find_insider_longs.py
Discover wallets CONNECTED to the 0x20c2 insider cluster (via large USDC
transfers on Arbitrum) and report any that currently hold an open Hyperliquid
position - especially LONGs.

Needs a free Etherscan API key (https://etherscan.io/apis). No pip install.
Run:  python find_insider_longs.py
"""
import json
import time
import datetime
import urllib.request
import urllib.parse
import urllib.error

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
HL = "https://api.hyperliquid.xyz/info"
ARB = 42161
USDC_MIN = 100000.0          # only follow USDC transfers >= this (token units)
USDC_SYMBOLS = {"USDC", "USDC.e"}

# Confirmed cluster wallets to expand from.
SEEDS = [
    "0x20c2d95a3dfdca9e9ad12794d5fa6fad99da44f5",
    "0x40e7f70d8c5dbf7b27dab33ed826484b3c657e56",
    "0x511ccde9444216efc26e5744a0355eaebaaea82cb",
    "0x8ad9765c8613d3beb6fbfa9df44e5bd1de4934e1",
    "0x1e772565d78761d67796643941597c9f452da0d9",
]

# Not insider traders -> ignore as counterparties.
IGNORE = {
    "0xee7ae85f2fe2239e27d9c1e23fffe168d63b4055",  # Binance HW34
    "0x2df1c51e09aecf9cacb7bc98cb1742757f163df7",  # Hyperliquid bridge
    "0x0000000000000000000000000000000000000000",
    "0x511cd5a8644ce7cc96eaab1938e873f4e03e82cb",  # decoy
    "0xee7a8a1898bd47592aa1062e4f60608c993b4055",  # decoy
    "0x40e7fb7ddcaee8e4bcb66180a350c00b3c657e56",  # decoy
    "0x2df17470c5de6a5d2d41feb8fcf5fb0deeb43df7",  # phishing
}
IGNORE.update(SEEDS)


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def hl_post(req_type, addr):
    body = json.dumps({"type": req_type, "user": addr}).encode()
    req = urllib.request.Request(HL, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception:
        return None


def usdc_counterparties(addr, key):
    """Addresses that traded >= USDC_MIN real USDC with `addr` on Arbitrum."""
    params = urllib.parse.urlencode({
        "chainid": ARB, "module": "account", "action": "tokentx",
        "address": addr, "page": 1, "offset": 300, "sort": "desc", "apikey": key,
    })
    try:
        data = get_json(ETHERSCAN_V2 + "?" + params)
    except Exception as e:
        print("   etherscan error:", e)
        return set()
    if str(data.get("status")) != "1":
        if "rate" in str(data.get("result", "")).lower():
            time.sleep(1.0)
        return set()
    found = set()
    for tx in data.get("result", []):
        if tx.get("tokenSymbol") not in USDC_SYMBOLS:
            continue
        try:
            val = int(tx["value"]) / (10 ** int(tx.get("tokenDecimal", 6)))
        except Exception:
            continue
        if val < USDC_MIN:
            continue
        for side in ("from", "to"):
            a = tx.get(side, "").lower()
            if a and a not in IGNORE:
                found.add(a)
    return found


def main():
    key = input("Etherscan API key yapistir ve Enter: ").strip()
    if not key:
        print("Key bos, cikiliyor."); return

    print("\n[1/2] Kume cuzdanlarinin USDC karsi taraflari toplaniyor...")
    candidates = set()
    for s in SEEDS:
        cps = usdc_counterparties(s, key)
        print("   {} -> {} yeni karsi taraf".format(s[:10] + "...", len(cps)))
        candidates |= cps
        time.sleep(0.3)

    print("\n[2/2] {} aday Hyperliquid'de taraniyor...".format(len(candidates)))
    longs_found = []
    for a in sorted(candidates):
        st = hl_post("clearinghouseState", a)
        time.sleep(0.15)
        if not st:
            continue
        positions = st.get("assetPositions", [])
        acct = float(st.get("marginSummary", {}).get("accountValue", 0) or 0)
        if not positions and acct == 0:
            continue  # never traded / empty
        print("\n  {}".format(a))
        print("    HL value: {:,.0f} USD".format(acct))
        for ap in positions:
            p = ap["position"]
            side = "LONG" if float(p.get("szi", 0) or 0) > 0 else "SHORT"
            line = "    -> {} {}  value={:,.0f}  entry={}  uPnL={:,.0f}  lev={}x".format(
                p.get("coin"), side, float(p.get("positionValue", 0) or 0),
                p.get("entryPx"), float(p.get("unrealizedPnl", 0) or 0),
                p.get("leverage", {}).get("value"))
            print(line)
            if side == "LONG":
                print("       *** LONG! ***")
                longs_found.append((a, p.get("coin"), p.get("positionValue")))

    print("\n" + "=" * 50)
    if longs_found:
        print("ACIK LONG TUTAN BAGLI CUZDANLAR:")
        for a, coin, val in longs_found:
            print("  {}  {}  {}".format(a, coin, val))
    else:
        print("Bagli cuzdanlarda acik LONG bulunamadi.")
    print("Bitti.")


if __name__ == "__main__":
    main()
