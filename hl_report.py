"""hl_report.py - Full Hyperliquid history report for the wallet cluster.
Shows: perp value+positions, spot balances, fill direction breakdown
(Open/Close Long/Short), recent fills, and deposits/withdrawals.
Pure stdlib. Run:  python hl_report.py
"""
import json
import urllib.request
import urllib.error
import datetime

URL = "https://api.hyperliquid.xyz/info"

WALLETS = [
    ("MAIN        0x20c2...44f5",  "0x20c2d95a3dfdca9e9ad12794d5fa6fad99da44f5"),
    ("BIG FEEDER  0x40e7f70D...",  "0x40e7f70d8c5dbf7b27dab33ed826484b3c657e56"),
    ("FEEDER      0x8ad9765C...",  "0x8ad9765c8613d3beb6fbfa9df44e5bd1de4934e1"),
    ("FEEDER      0x1e772565d...", "0x1e772565d78761d67796643941597c9f452da0d9"),
    ("TWCOIN      0x9E0dEE69...",  "0x9e0dee69b9e8efb9ab6408ad4a3e133db2da283b"),
]


def hl(req_type, addr, extra=None):
    payload = {"type": req_type, "user": addr}
    if extra:
        payload.update(extra)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print("       (api error {} on {})".format(e.code, req_type))
        return None
    except Exception as e:
        print("       (error {} on {})".format(e, req_type))
        return None


def ts(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


for name, addr in WALLETS:
    print("\n" + "=" * 60)
    print(name + "   " + addr)
    print("=" * 60)

    # ---- PERP ----
    st = hl("clearinghouseState", addr) or {}
    acct = float(st.get("marginSummary", {}).get("accountValue", 0) or 0)
    print("  PERP account value: {:,.2f} USD".format(acct))
    for ap in st.get("assetPositions", []):
        p = ap["position"]
        side = "LONG" if float(p.get("szi", 0) or 0) > 0 else "SHORT"
        print("    -> {} {}  value={:,.0f}  entry={}  uPnL={:,.0f}  lev={}x".format(
            p.get("coin"), side, float(p.get("positionValue", 0) or 0),
            p.get("entryPx"), float(p.get("unrealizedPnl", 0) or 0),
            p.get("leverage", {}).get("value")))
    if not st.get("assetPositions"):
        print("    (no open perp positions)")

    # ---- SPOT ----
    sp = hl("spotClearinghouseState", addr) or {}
    bals = [b for b in sp.get("balances", []) if float(b.get("total", 0) or 0) > 0]
    if bals:
        print("  SPOT balances:")
        for b in bals:
            print("    {}: {}".format(b.get("coin"), b.get("total")))

    # ---- FILLS (trade history direction) ----
    fills = hl("userFills", addr) or []
    if fills:
        dirs = {}
        pnl = 0.0
        for f in fills:
            dirs[f.get("dir", "?")] = dirs.get(f.get("dir", "?"), 0) + 1
            pnl += float(f.get("closedPnl", 0) or 0)
        print("  FILLS: {} total  | realized PnL on these: {:,.0f} USD".format(len(fills), pnl))
        for d, c in sorted(dirs.items(), key=lambda x: -x[1]):
            print("    {:>14}: {}".format(d, c))
        print("  LAST 8 TRADES:")
        for f in sorted(fills, key=lambda x: x.get("time", 0), reverse=True)[:8]:
            print("    {}  {:>5}  {:<12} px={} sz={}".format(
                ts(f.get("time", 0)), f.get("coin"), f.get("dir", "?"),
                f.get("px"), f.get("sz")))
    else:
        print("  FILLS: none returned")

    # ---- DEPOSITS / WITHDRAWALS ----
    led = hl("userNonFundingLedgerUpdates", addr, {"startTime": 0}) or []
    dw = [l for l in led if l.get("delta", {}).get("type") in ("deposit", "withdraw")]
    if dw:
        print("  DEPOSIT/WITHDRAW (last 8):")
        for l in sorted(dw, key=lambda x: x.get("time", 0), reverse=True)[:8]:
            d = l["delta"]
            print("    {}  {:<9} {:,.2f} USD".format(
                ts(l.get("time", 0)), d.get("type"), float(d.get("usdc", 0) or 0)))

print("\nBitti.")
