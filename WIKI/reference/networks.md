---
title: Networks
---

# Networks

The single source is `app/networks.py`; `GET /api/meta/networks` returns the same data.

## Known networks
| Slug | Network | Address format checked |
|---|---|---|
| `bitcoin` | Bitcoin | `bc1…`, `1…`, `3…` |
| `ethereum` | Ethereum | `0x` + 40 hex |
| `base` | Base | `0x` + 40 hex |
| `arbitrum` | Arbitrum One | `0x` + 40 hex |
| `optimism` | OP Mainnet (Optimism) | `0x` + 40 hex |
| `polygon` | Polygon PoS | `0x` + 40 hex |
| `bsc` | BNB Smart Chain | `0x` + 40 hex |
| `avalanche` | Avalanche C-Chain | `0x` + 40 hex |
| `solana` | Solana | 32-44 base58 |
| `tron` | Tron | `T…` |
| `cardano` | Cardano | `addr1…` |
| `xrp` | XRP Ledger | `r…` |
| `dogecoin` | Dogecoin | `D…` |
| `litecoin` | Litecoin | `ltc1…`, `L…`, `M…`, `3…` |
| `polkadot` | Polkadot | `1…` |
| `cosmos` | Cosmos Hub | `cosmos1…` |
| `stellar` | Stellar | `G…` |
| `bitcoin-cash` | Bitcoin Cash | `q…`, `p…` |

You can also use networks that aren't listed (lowercase letters, digits and dashes, 2-32
characters); their addresses only get a basic length and character check.

The EVM checks don't verify the mixed-case checksum (EIP-55) yet.

## Where each coin exists
A coin outside this list is a *different* token (a wrapped or bridged copy with its own
symbol), so it's refused. Coins not in the table are allowed on any network.

| Coin | Networks |
|---|---|
| BTC | bitcoin |
| ETH | ethereum, arbitrum, optimism, base |
| SOL | solana |
| ADA | cardano |
| XRP | xrp |
| DOGE | dogecoin |
| LTC | litecoin |
| DOT | polkadot |
| AVAX | avalanche |
| LINK | ethereum, arbitrum, optimism, base, polygon, bsc, avalanche |
| USDT | ethereum, tron, solana, bsc, polygon, arbitrum, avalanche, optimism |
| USDC | ethereum, solana, base, polygon, arbitrum, optimism, avalanche, stellar |
| BNB | bsc |
| BCH | bitcoin-cash |
| XLM | stellar |
| ATOM | cosmos |
| TRX | tron |
| SHIB | ethereum |

## Transfer rules
| From | To | Rule |
|---|---|---|
| has a network | has a different network | Refused: needs a bridge |
| any | has a network | The coin must exist on that network |
| exchange | on-chain | Allowed (a withdrawal on the destination's network), with a reminder |
| on-chain | exchange | Allowed (a deposit), with a reminder |
| exchange | exchange | Allowed, with a reminder |
| paper without network | anything | Only the destination's rules apply |
