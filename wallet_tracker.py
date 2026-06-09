#!/usr/bin/env python3
"""
wallet_tracker.py - Blockchain fund-flow tracer (Arbitrum + Ethereum + Hyperliquid)

Traces ERC-20, native, and internal transfers outward from a target wallet,
following large transfers up to a configurable hop depth (BFS). Stops expanding
known terminal addresses (exchanges / bridges) because tracing ends there
on-chain. Also pulls the address's Hyperliquid perp/spot state and the
deposit/withdrawal ledger that links the L1 trading account to its on-chain
funding source.

Usage:
    1. cp .env.example .env  and put your ETHERSCAN_API_KEY in it
    2. pip install -r requirements.txt
    3. python wallet_tracker.py

Notes:
    * Uses the Etherscan V2 unified API (one key works across all chains via the
      `chainid` param). ETH mainnet = 1, Arbitrum One = 42161. The legacy
      api.arbiscan.io host is deprecated in favour of this.
    * The Hyperliquid Info API needs no key.
"""

import os
import sys
import json
import time
import argparse
from collections import defaultdict, deque

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional; env vars may be set another way


# ============================== SETTINGS =====================================

TARGET = os.getenv("TARGET", "0x20c2d95a3dfdca9e9ad12794d5fa6fad99da44f5").lower()

ETHERSCAN_KEY = os.getenv("ETHERSCAN_API_KEY", "").strip()

# Etherscan V2 unified endpoint (single key, all chains via chainid)
ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
CHAINS = {1: "ETH", 42161: "ARB"}      # chains to scan, name for reporting

DEPTH = int(os.getenv("DEPTH", "3"))   # how many hops deep to follow
BIG_TRANSFER = float(os.getenv("BIG_TRANSFER", "10000"))  # follow transfers >= this (token units)
MAX_TX_PER_ADDR = int(os.getenv("MAX_TX_PER_ADDR", "500"))  # cap pulled txs per addr per type
REQUEST_SLEEP = 0.25   # be polite to the free tier (5 req/s)

HYPERLIQUID_INFO = "https://api.hyperliquid.xyz/info"


# Known address labels. Lower-cased keys. Addresses flagged terminal=True are
# NOT expanded further (exchange omnibus / bridges -> on-chain trail ends).
KNOWN_LABELS = {
    # --- target & hops in this investigation ---
    "0x20c2d95a3dfdca9e9ad12794d5fa6fad99da44f5": ("TARGET_ETH_Short_Whale", False),
    "0x511ccde9444216efc26e5744a0355eaebaaea82cb": ("HOP_1_Intermediary", False),

    # --- Binance (terminal: omnibus exchange wallets, can't trace past) ---
    "0xee7ae85f2fe2239e27d9c1e23fffe168d63b4055": ("Binance_Hot_Wallet_34", True),
    "0x28c6c06298d514db089934071355e5743bf21d60": ("Binance_14", True),
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": ("Binance_15", True),
    "0xdfd5293d8e347dfe59e90efd55b2956a1343963d": ("Binance_16", True),
    "0xb38e8c17e38363af6ebdcb3dae12e0243582891d": ("Binance_Hot_Wallet", True),
    "0x25681ab599b4e2ceea31f8b498052c53fc2d74db": ("Binance_94", True),
    "0xa74e8ae2f83d2564af25420ad4d6a7fe224b053f": ("Binance_US_9", True),

    # --- Hyperliquid bridge (terminal: deposits/withdrawals cross to L1) ---
    "0x2df1c51e09aecf9cacb7bc98cb1742757f163df7": ("Hyperliquid_Bridge2", True),
    "0x2222222222222222222222222222222222222222": ("Hyperliquid_System", True),
}


def label_for(addr):
    addr = addr.lower()
    if addr in KNOWN_LABELS:
        return KNOWN_LABELS[addr][0]
    return addr[:8] + "..." + addr[-4:]


def is_terminal(addr):
    addr = addr.lower()
    return KNOWN_LABELS.get(addr, (None, False))[1]


# ============================ ETHERSCAN V2 ===================================

def etherscan_call(chainid, action, address, retries=4):
    """One Etherscan V2 'account' call with rate-limit-aware retry/backoff."""
    if not ETHERSCAN_KEY:
        print("  !! ETHERSCAN_API_KEY not set - skipping on-chain pull. "
              "Get a free key at https://etherscan.io/apis")
        return []
    params = {
        "chainid": chainid,
        "module": "account",
        "action": action,
        "address": address,
        "startblock": 0,
        "endblock": 99999999,
        "page": 1,
        "offset": MAX_TX_PER_ADDR,
        "sort": "desc",
        "apikey": ETHERSCAN_KEY,
    }
    backoff = 2
    for attempt in range(retries):
        try:
            r = requests.get(ETHERSCAN_V2, params=params, timeout=30)
            data = r.json()
        except Exception as e:
            print(f"  !! request error ({action}): {e}")
            time.sleep(backoff); backoff *= 2
            continue

        status = str(data.get("status"))
        result = data.get("result")
        if status == "1":
            return result if isinstance(result, list) else []
        # status == "0": either no txns, or an error/rate-limit string in result
        msg = (data.get("message") or "").lower()
        if "no transactions found" in msg or result == []:
            return []
        if isinstance(result, str) and ("rate limit" in result.lower() or "max" in result.lower()):
            time.sleep(backoff); backoff *= 2
            continue
        # other NOTOK -> log once and bail
        print(f"  !! etherscan {action} chain={chainid}: {data.get('message')} / {result}")
        return []
    return []


def fetch_all_transfers(chainid, address):
    """Return normalized outgoing edges for native, internal and ERC-20 txs."""
    edges = []

    # ERC-20 token transfers
    for tx in etherscan_call(chainid, "tokentx", address):
        if tx.get("from", "").lower() != address.lower():
            continue
        try:
            dec = int(tx.get("tokenDecimal") or 18)
            val = int(tx.get("value", 0)) / (10 ** dec)
        except (ValueError, ZeroDivisionError):
            val = 0
        edges.append(_edge(chainid, address, tx, val, tx.get("tokenSymbol", "?")))
    time.sleep(REQUEST_SLEEP)

    # Native coin (ETH) transfers
    for tx in etherscan_call(chainid, "txlist", address):
        if tx.get("from", "").lower() != address.lower():
            continue
        if tx.get("value", "0") == "0":
            continue
        val = int(tx.get("value", 0)) / 1e18
        edges.append(_edge(chainid, address, tx, val, "ETH"))
    time.sleep(REQUEST_SLEEP)

    # Internal transfers (value moved via contracts, e.g. withdrawals)
    for tx in etherscan_call(chainid, "txlistinternal", address):
        if tx.get("from", "").lower() != address.lower():
            continue
        if tx.get("value", "0") == "0":
            continue
        val = int(tx.get("value", 0)) / 1e18
        edges.append(_edge(chainid, address, tx, val, "ETH(internal)"))
    time.sleep(REQUEST_SLEEP)

    return edges


def _edge(chainid, frm, tx, value, token):
    ts = int(tx.get("timeStamp", 0) or 0)
    to_addr = (tx.get("to") or "").lower()
    return {
        "chain": CHAINS.get(chainid, str(chainid)),
        "from": label_for(frm),
        "from_addr": frm.lower(),
        "to": label_for(to_addr) if to_addr else "(contract creation)",
        "to_addr": to_addr,
        "amount": round(value, 4),
        "token": token,
        "hash": tx.get("hash", ""),
        "timestamp": ts,
        "age_days": round((time.time() - ts) / 86400, 1) if ts else None,
    }


# ============================ HYPERLIQUID ====================================

def hl_post(payload):
    try:
        r = requests.post(HYPERLIQUID_INFO, json=payload, timeout=15)
        return r.json()
    except Exception as e:
        print(f"  !! hyperliquid error ({payload.get('type')}): {e}")
        return None


def hyperliquid_report(address):
    print("\n" + "=" * 64)
    print("HYPERLIQUID ACCOUNT")
    print("=" * 64)

    perp = hl_post({"type": "clearinghouseState", "user": address}) or {}
    spot = hl_post({"type": "spotClearinghouseState", "user": address}) or {}
    fills = hl_post({"type": "userFills", "user": address}) or []
    ledger = hl_post({"type": "userNonFundingLedgerUpdates",
                      "user": address, "startTime": 0}) or []

    summary = {}

    ms = perp.get("marginSummary", {})
    if ms:
        print(f"  Account value:  ${float(ms.get('accountValue', 0)):,.2f}")
        print(f"  Total margin:   ${float(ms.get('totalMarginUsed', 0)):,.2f}")
        summary["account_value"] = float(ms.get("accountValue", 0))

    positions = perp.get("assetPositions", [])
    if positions:
        print("\n  OPEN PERP POSITIONS:")
        summary["positions"] = []
        for ap in positions:
            p = ap.get("position", {})
            szi = float(p.get("szi", 0))
            side = "LONG" if szi > 0 else "SHORT"
            row = {
                "coin": p.get("coin"), "side": side, "size": szi,
                "entry": p.get("entryPx"),
                "unrealized_pnl": p.get("unrealizedPnl"),
                "position_value": p.get("positionValue"),
                "leverage": p.get("leverage", {}).get("value"),
            }
            summary["positions"].append(row)
            print(f"    {row['coin']:>6} {side:<5} size={szi:<14} "
                  f"entry={row['entry']:<10} uPnL=${float(row['unrealized_pnl'] or 0):,.0f} "
                  f"lev={row['leverage']}x")
    else:
        print("\n  No open perp positions.")

    bals = spot.get("balances", [])
    if bals:
        print("\n  SPOT BALANCES:")
        for b in bals:
            print(f"    {b.get('coin'):>8}: {b.get('total')}")

    # Deposits / withdrawals = the on-chain <-> L1 money trail
    deps = [l for l in ledger if l.get("delta", {}).get("type") in ("deposit", "withdraw")]
    if deps:
        print(f"\n  DEPOSITS/WITHDRAWALS (last {min(len(deps),15)} of {len(deps)}):")
        for l in deps[-15:]:
            d = l["delta"]
            t = time.strftime("%Y-%m-%d", time.localtime(l.get("time", 0) / 1000))
            print(f"    {t}  {d['type']:<9} ${float(d.get('usdc', 0)):,.2f}")
    summary["deposit_withdraw_count"] = len(deps)
    summary["fills_count"] = len(fills)
    print(f"\n  Total fills on record: {len(fills)}")

    return summary


# ================================ BFS ========================================

def trace(target, depth_limit):
    edges_all = []
    visited = set()
    queue = deque([(target.lower(), 0)])

    while queue:
        addr, depth = queue.popleft()
        if addr in visited or depth > depth_limit:
            continue
        visited.add(addr)

        indent = "  " * depth
        print(f"{indent}> {label_for(addr)} (depth={depth})")

        if depth > 0 and is_terminal(addr):
            print(f"{indent}  [terminal - exchange/bridge, not expanding]")
            continue

        for chainid in CHAINS:
            edges = fetch_all_transfers(chainid, addr)
            edges_all.extend(edges)
            # follow big outgoing transfers
            big = sorted([e for e in edges if e["amount"] >= BIG_TRANSFER],
                         key=lambda e: e["amount"], reverse=True)
            for e in big:
                dest = e["to_addr"]
                if not dest:
                    continue
                print(f"{indent}  {e['amount']:>14,.2f} {e['token']:<14} "
                      f"-> {e['to']}  [{e['chain']}]")
                if dest not in visited and depth + 1 <= depth_limit:
                    queue.append((dest, depth + 1))

    return edges_all


# ================================ MAIN =======================================

def main():
    ap = argparse.ArgumentParser(description="Wallet fund-flow tracer")
    ap.add_argument("--target", default=TARGET, help="address to trace")
    ap.add_argument("--depth", type=int, default=DEPTH)
    ap.add_argument("--no-hl", action="store_true", help="skip Hyperliquid lookup")
    args = ap.parse_args()

    target = args.target.lower()

    print("=" * 64)
    print("WALLET FORENSICS")
    print(f"Target : {target}  ({label_for(target)})")
    print(f"Chains : {', '.join(CHAINS.values())}   Depth: {args.depth}   "
          f"Follow >= {BIG_TRANSFER:,.0f} tokens")
    print("=" * 64)

    edges = trace(target, args.depth)

    # ---- Hyperliquid ----
    hl_summary = {}
    if not args.no_hl:
        hl_summary = hyperliquid_report(target)

    # ---- Reports ----
    print("\n" + "=" * 64)
    print("FLOW SUMMARY")
    print("=" * 64)

    if not edges:
        print("No outgoing transfers found (check ETHERSCAN_API_KEY / network).")
    else:
        # rollup: where did value end up, by destination label
        dest = defaultdict(lambda: defaultdict(float))
        for e in edges:
            dest[e["to"]][e["token"]] += e["amount"]
        print(f"\nValue out by destination (top 20):")
        flat = []
        for d, toks in dest.items():
            for tok, amt in toks.items():
                flat.append((d, tok, amt))
        for d, tok, amt in sorted(flat, key=lambda x: -x[2])[:20]:
            print(f"  {amt:>16,.2f} {tok:<14} -> {d}")

        # write artifacts
        import csv
        with open("wallet_trace_results.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(edges[0].keys()))
            w.writeheader()
            w.writerows(edges)
        print("\n  -> wallet_trace_results.csv")

    summary = {
        "target": target,
        "label": label_for(target),
        "chains": list(CHAINS.values()),
        "depth": args.depth,
        "total_outgoing_edges": len(edges),
        "unique_destinations": len({e["to_addr"] for e in edges}),
        "hyperliquid": hl_summary,
    }
    with open("wallet_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print("  -> wallet_summary.json")
    print("\nDone.")


if __name__ == "__main__":
    main()
