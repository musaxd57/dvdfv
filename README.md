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

```bash
pip install -r requirements.txt
cp .env.example .env       # then put your ETHERSCAN_API_KEY in .env
```

Get a free key at https://etherscan.io/apis. The Hyperliquid Info API needs no key.

> The legacy `api.arbiscan.io` host is deprecated — this tool uses
> `https://api.etherscan.io/v2/api?chainid=42161` instead. A single Etherscan
> key covers Arbitrum, Ethereum and every other supported chain.

## Run

```bash
python wallet_tracker.py                      # uses defaults (the target below)
python wallet_tracker.py --target 0xABC... --depth 4
python wallet_tracker.py --no-hl              # skip Hyperliquid
```

## Investigation context (this repo's default target)

| Address | Role |
|---|---|
| `0x20c2d95a3dfdca9e9ad12794d5fa6fad99da44f5` | **Target** — the well-known Hyperliquid 50x ETH-short whale |
| `0x511cCDe9444216EFC26e5744a0355EaEBAeA82cB` | First hop — unlabeled intermediary EOA |
| `0xEe7aE85f2Fe2239E27D9c1E23fFFe168D63b4055` | **Binance: Hot Wallet 34** — on-chain trail ends here |

**Note on the trail ending:** a Binance hot wallet is a shared omnibus deposit
address. Once funds land there they merge into Binance's internal books, so a
block explorer cannot follow them further. Continuing past that point requires
Binance's KYC/account records (i.e. a legal/exchange process), not OSINT.

## Why it must be run locally / on an unrestricted network

Sandboxed CI-style environments often allowlist outbound hosts. This tool needs
egress to `api.etherscan.io` and `api.hyperliquid.xyz`; if those are blocked the
on-chain pull returns empty. Run it from a machine (or environment) whose network
policy permits those hosts.
