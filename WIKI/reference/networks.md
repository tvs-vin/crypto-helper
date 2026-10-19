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

## Tokens read on-chain
Synced EVM wallets read the network's own coin and only these tokens (`app/networks.py`
`NATIVE` and `TOKENS`). Each contract was checked on 2026-10-18 on the chain (symbol and
decimals) and against the issuer's own list (Circle for USDC, Tether's USDT0 deployments).
Anything else sent to an address is ignored.

| Network | Coin | Tokens: contract (decimals) |
|---|---|---|
| ethereum | ETH | USDC: `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48` (6)<br>USDT: `0xdAC17F958D2ee523a2206206994597C13D831ec7` (6)<br>LINK: `0x514910771AF9Ca656af840dff83E8264EcF986CA` (18)<br>SHIB: `0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE` (18) |
| base | ETH | USDC: `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` (6) |
| arbitrum | ETH | USDC: `0xaf88d065e77c8cC2239327C5EDb3A432268e5831` (6)<br>USDT: `0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9` (6) |
| optimism | ETH | USDC: `0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85` (6)<br>USDT: `0x01bFF41798a0BcF287b996046Ca68b395DbC1071` (6)<br>USDT: `0x94b008aA00579c1307B0EF2c499aD98a8ce58e58` (6) |
| polygon | POL | USDC: `0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359` (6)<br>USDT: `0xc2132D05D31c914a87C6611C10748AEb04B58e8F` (6) |

On Arbitrum, Optimism and Polygon, USDT is Tether's USD₮0. Optimism also still has the older
bridged USDT; both count as USDT. Bitcoin balances come from an Esplora server (mempool.space
by default).
