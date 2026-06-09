# Wallet Fund-Flow Tracer

Traces where funds move out of a target wallet across **Arbitrum One** and
**Ethereum mainnet**, following large transfers hop-by-hop (BFS), and pulls the
target's **Hyperliquid** perp/spot state plus its deposit/withdrawal ledger.

## What it does

- Pulls **ERC-20**, **native ETH**, and **internal** transfers for each address
  via the Etherscan **V2 unified API** (one key, all chains).
- Follows outgoing transfers `>= BIG_TRANSFER` (default 10,000 token units) up to
  `DEPTH` hops (default 3).
- **Stops at terminal addresses** — exchange omnibus wallets (Binance hot
  wallets) and the Hyperliquid bridge — because on-chain tracing genuinely ends
  there (funds enter the exchange's internal ledger / cross to the L1).
- Pulls Hyperliquid `clearinghouseState` (perps), `spotClearinghouseState`,
  `userFills`, and `userNonFundingLedgerUpdates` (deposits/withdrawals).
- Writes `wallet_trace_results.csv` (every edge) and `wallet_summary.json`.

## Setup

Get a free key at https://etherscan.io/apis. The Hyperliquid Info API needs no key.

### Windows (your `'pip' is not recognized` error = Python not installed / not on PATH)

1. Install Python from https://www.python.org/downloads/ — **tick "Add python.exe to PATH"** in the installer.
2. Open a **new** Command Prompt (`cmd`) in the project folder, then:

```bat
py -m pip install -r requirements.txt
copy .env.example .env
notepad .env            REM paste your ETHERSCAN_API_KEY, save, close
py wallet_tracker.py
py wallet_tracker.py --longs
```

> Use `py` (the Windows Python launcher) instead of `python`/`pip` if those aren't found.

### macOS / Linux

```bash
pip install -r requirements.txt
cp .env.example .env       # then put your ETHERSCAN_API_KEY in .env
python wallet_tracker.py
```

> The legacy `api.arbiscan.io` host is deprecated — this tool uses
> `https://api.etherscan.io/v2/api?chainid=42161` instead. A single Etherscan
> key covers Arbitrum, Ethereum and every other supported chain.

## Run

```bash
python wallet_tracker.py                      # uses defaults (the target below)
python wallet_tracker.py --target 0xABC... --depth 4
python wallet_tracker.py --no-hl              # skip Hyperliquid
```

## Investigation context (owner cluster, from the CSV fund-flow)

Real money is **USDC only**. The flow consolidates through one funnel into Binance:

```
Hyperliquid  <->  0x20c2…44f5 (MAIN, public ETH-short whale) ─┐
                  0x40e7f70D…7e56 (2nd big wallet) ───────────┤
                  0x8ad9765C…34e1 ───────────────────────────┼─► 0x511cCDe9…82cB ─► Binance HW34
                  0x1e772565d…a0D9 ──────────────────────────┘      (funnel)         (trail ends)
```

~$19M was cashed out to **Binance Hot Wallet 34** (`0xEe7aE85f…4055`) Mar–May 2026.
A Binance hot wallet is a shared omnibus address — once funds land there they merge
into Binance's books, so on-chain tracing ends. Going further needs Binance KYC
records (legal process), not OSINT.

### Address-poisoning decoys (ignore these — they are NOT real)

| Decoy | Mimics |
|---|---|
| `0x511cd5A8…03e82Cb` (fake "U5DC" token) | `0x511cCDe9…BaeA82cB` funnel |
| `0xee7a8a18…993b4055` | `0xEe7aE85f…D63b4055` Binance HW34 |
| `0x40e7fb7d…0B3C657E56` | `0x40e7f70D…3c657e56` feeder |
| token `U5DC` | real `USDC` |

### Hunting a hidden LONG

The owner is famous for ETH **shorts** on the MAIN wallet. To check whether he
flipped **long** (e.g. during a BTC/ETH rally) on a less-watched sister wallet:

```bash
python wallet_tracker.py --longs
```

This queries Hyperliquid `clearinghouseState` for every cluster wallet and flags
any open LONG. Prime suspect: `0x40e7f70D…7e56`.

## Why it must be run locally / on an unrestricted network

Sandboxed CI-style environments often allowlist outbound hosts. This tool needs
egress to `api.etherscan.io` and `api.hyperliquid.xyz`; if those are blocked the
on-chain pull returns empty. Run it from a machine (or environment) whose network
policy permits those hosts.
