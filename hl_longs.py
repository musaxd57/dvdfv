"""hl_longs.py - Hyperliquid LONG-hunt. Pure stdlib, no pip install, no API key.
Run:  python hl_longs.py
"""
import json
import urllib.request
import datetime

URL = "https://api.hyperliquid.xyz/info"

# Owner cluster (real addresses; 0x40e7f70D is the REAL big feeder, not the decoy).
WALLETS = [
    ("MAIN        0x20c2...44f5",  "0x20c2d95a3dfdca9e9ad12794d5fa6fad99da44f5"),
    ("BIG FEEDER  0x40e7f70D...",  "0x40e7f70d8c5dbf7b27dab33ed826484b3c657e56"),
    ("FUNNEL      0x511cCDe9...",  "0x511ccde9444216efc26e5744a0355eaebaaea82cb"),
    ("FEEDER      0x8ad9765C...",  "0x8ad9765c8613d3beb6fbfa9df44e5bd1de4934e1"),
    ("FEEDER      0x1e772565d...", "0x1e772565d78761d67796643941597c9f452da0d9"),
    ("TWCOIN      0x9E0dEE69...",  "0x9e0dee69b9e8efb9ab6408ad4a3e133db2da283b"),
]


def hl(req_type, addr):
    body = json.dumps({"type": req_type, "user": addr}).encode()
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


for name, addr in WALLETS:
    print("\n==== " + name + " ====")
    print("     " + addr)
    try:
        s = hl("clearinghouseState", addr)
    except Exception as e:
        print("     ERROR:", e)
        continue

    acct = float(s.get("marginSummary", {}).get("accountValue", 0) or 0)
    print("     Account value: {:,.2f} USD".format(acct))

    positions = s.get("assetPositions", [])
    if not positions:
        print("     no open positions")
    for ap in positions:
        p = ap["position"]
        szi = float(p.get("szi", 0) or 0)
        side = "LONG" if szi > 0 else "SHORT"
        print("     -> {} {}  value={:,.0f} USD  entry={}  uPnL={:,.0f} USD  lev={}x".format(
            p.get("coin"), side, float(p.get("positionValue", 0) or 0),
            p.get("entryPx"), float(p.get("unrealizedPnl", 0) or 0),
            p.get("leverage", {}).get("value")))
        if side == "LONG":
            print("        *** LONG! <-- bu cuzdan LONG acmis ***")

    try:
        fills = hl("userFills", addr)
    except Exception:
        fills = []
    open_longs = [f for f in fills if "Open Long" in f.get("dir", "")]
    if open_longs:
        print("     OPEN LONG fills: {}".format(len(open_longs)))
        for f in sorted(open_longs, key=lambda x: x.get("time", 0), reverse=True)[:5]:
            t = datetime.datetime.fromtimestamp(f.get("time", 0) / 1000).strftime("%Y-%m-%d %H:%M")
            print("        {}  {}  px={}  sz={}".format(t, f.get("coin"), f.get("px"), f.get("sz")))

print("\nBitti. 'LONG' yazan cuzdan = aradigin cevap.")
