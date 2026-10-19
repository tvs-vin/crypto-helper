"""11c: balances on-chain. Bitcoin addresses and xpubs (BIP test vectors, gap limit), EVM
addresses with the token list, through the API and the sync engine, against a local fake."""

import http.server
import json
import threading
import urllib.parse
from decimal import Decimal

import pytest
from embit.descriptor import Descriptor
from sqlalchemy import select

from app import networks as nets
from app.models import WalletSource
from app.sync import SourceError, chains
from tests.conftest import H

# The BIP84 / BIP86 test vectors (the well-known all-"abandon" test wallet: never real funds).
ZPUB = (
    "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkg"
    "DKf31mGDtKsAYz2oz2AGutZYs"
)
TR_XPUB = (
    "xpub6BgBgsespWvERF3LHQu6CnqdvfEvtMcQjYrcRzx53QJjSxarj2afYWcLteoGVky7D3UKDP9QyrLprQ3"
    "VCECoY49yfdDEHGCtMMj92pReUsQ"
)


def derive(key, kind, branch, i):
    text = f"{kind.replace('-', '(')}({key}/{branch}/*)" + (")" if "-" in kind else "")
    return Descriptor.from_string(text).derive(i).script_pubkey().address()


def test_vectors():
    assert derive(ZPUB, "wpkh", 0, 0) == "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
    assert derive(TR_XPUB, "tr", 0, 0) == (
        "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"
    )


class Chain:
    """A fake Esplora (`/address/<a>`) and EVM node (`/rpc/<network>`, JSON-RPC batches)."""

    def __init__(self):
        self.btc: dict[str, tuple[int, int, int]] = {}  # address -> (confirmed, pending, txs)
        self.evm: dict[tuple[str, str], int] = {}  # (address, contract or "native") -> units
        self.calls, self.batch_ok = [], True
        chain = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def send(self, payload, status=200):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = urllib.parse.unquote(self.path)
                chain.calls.append(path)
                if path.startswith("/address/"):
                    conf, pend, txs = chain.btc.get(path[9:], (0, 0, 0))
                    return self.send(
                        {
                            "chain_stats": {
                                "funded_txo_sum": conf + 1000,
                                "spent_txo_sum": 1000,
                                "tx_count": txs,
                            },
                            "mempool_stats": {
                                "funded_txo_sum": pend,
                                "spent_txo_sum": 0,
                                "tx_count": 1 if pend else 0,
                            },
                        }
                    )
                self.send({"error": "not found"}, 404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                chain.calls.append(("rpc", self.path, body))
                if not isinstance(body, list) or not chain.batch_ok:
                    return self.send(
                        {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {"code": -32600, "message": "batch not allowed"},
                        }
                    )
                out = []
                for c in body:
                    if c["method"] == "eth_getBalance":
                        units = chain.evm.get((c["params"][0], "native"), 0)
                    else:
                        call = c["params"][0]
                        holder = "0x" + call["data"][-40:]
                        assert call["data"].startswith("0x70a08231")
                        units = chain.evm.get((holder, call["to"].lower()), 0)
                    out.append({"jsonrpc": "2.0", "id": c["id"], "result": hex(units)})
                self.send(out)

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


@pytest.fixture
def chain():
    c = Chain()
    yield c
    c.srv.shutdown()


def settings_for(chain):
    return chains.ChainSettings(
        esplora_url=chain.url, rpc={n: f"{chain.url}/rpc/{n}" for n in chains.DEFAULT_RPC}
    )


# ---- what can be watched ---------------------------------------------------------------------

ETH_ADDR = "0x" + "ab" * 20


@pytest.mark.parametrize(
    "network, addresses, xpub, message",
    [
        ("solana", ["So11111111111111111111111111111111111111112"], None, "isn't supported"),
        ("ethereum", ["0x123"], None, "doesn't look like"),
        ("ethereum", [], ZPUB, "for Bitcoin wallets"),
        (
            "bitcoin",
            [],
            "xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxW"
            "UtL6LZNqEXrgLaxFbTmNfZ5ruHAMJGkxEGxV7oi",
            "PRIVATE key",
        ),
        (
            "bitcoin",
            [],
            "tpubD6NzVbkrYhZ4WaWSyoBvQwbpLkojyoTZPRsgXELWz3Popb3qkjcJyJUGLnL4qHHoQvao8ESaA"
            "WM4GuXz5LCcpZY8Tt5LMgEuDsr4vvGwBQx",
            "testnet",
        ),
        ("bitcoin", [], "xpubNOPE", "isn't a valid"),
        ("bitcoin", [], None, "at least one address"),
        ("ethereum", [ETH_ADDR[:-2] + f"{i:02x}" for i in range(51)], None, "At most 50"),
    ],
)
def test_refused(network, addresses, xpub, message):
    with pytest.raises(ValueError, match=message):
        chains.check_watch(network, addresses, xpub, "auto")


def test_settings_urls():
    chains.ChainSettings(esplora_url="https://mempool.example/api")
    chains.ChainSettings(esplora_url="http://192.168.1.20:3002/api")  # your own node at home
    chains.ChainSettings(esplora_url="http://localhost:3002")
    for bad in ("http://mempool.example/api", "ftp://x", "file:///etc/passwd", "javascript:x"):
        with pytest.raises(ValueError):
            chains.ChainSettings(esplora_url=bad)
    with pytest.raises(ValueError, match="Unknown networks"):
        chains.ChainSettings(rpc={"solana": "https://x.example"})


# ---- Bitcoin ---------------------------------------------------------------------------------


def test_bitcoin_addresses(chain):
    a, b = derive(ZPUB, "wpkh", 0, 0), derive(ZPUB, "wpkh", 0, 1)
    chain.btc[a] = (150_000_000, 0, 3)
    chain.btc[b] = (1, 2_000, 1)  # one satoshi confirmed, 2,000 on the way
    got = chains.read("bitcoin", chains.Watch([a, b]), settings_for(chain))
    assert got.balances == {"BTC": Decimal("1.50002001")}


def test_xpub_scans_receive_and_change_until_the_gap(chain):
    used = {(0, 0): 100_000, (0, 1): 20_000, (0, 19): 3, (1, 0): 5_000}
    for (branch, i), sats in used.items():
        chain.btc[derive(ZPUB, "wpkh", branch, i)] = (sats, 0, 1)
    chain.btc[derive(ZPUB, "wpkh", 0, 45)] = (999_999, 0, 1)  # after 20 unused: never looked at
    got = chains.read("bitcoin", chains.Watch([], ZPUB, "auto"), settings_for(chain))
    assert got.balances == {"BTC": Decimal("0.00125003")}
    assert got.info == {"used_addresses": 4, "types": ["Native SegWit (bc1q…)"]}
    asked = [c for c in chain.calls if isinstance(c, str)]
    assert len(asked) == (19 + 1 + chains.GAP_LIMIT) + (1 + chains.GAP_LIMIT)  # receive + change


def test_a_plain_xpub_finds_its_address_type(chain):
    chain.btc[derive(TR_XPUB, "tr", 0, 0)] = (42, 0, 1)
    got = chains.read("bitcoin", chains.Watch([], TR_XPUB, "auto"), settings_for(chain))
    assert got.balances == {"BTC": Decimal("4.2E-7")} and got.info["types"] == ["Taproot (bc1p…)"]
    chain.calls.clear()
    chains.read("bitcoin", chains.Watch([], TR_XPUB, "tr"), settings_for(chain))  # told the type
    assert len(chain.calls) == 2 * chains.GAP_LIMIT + 1


def test_bitcoin_server_problems(chain):
    with pytest.raises(SourceError, match="Couldn't reach"):
        chains.read(
            "bitcoin",
            chains.Watch(["bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"]),
            chains.ChainSettings(esplora_url="http://127.0.0.1:1"),
        )


# ---- EVM -------------------------------------------------------------------------------------


def contract(network, symbol, n=0):
    return [t for t in nets.TOKENS[network] if t.symbol == symbol][n].contract.lower()


def test_evm_native_and_tokens(chain):
    a = ETH_ADDR
    chain.evm[(a, "native")] = 1_500_000_000_000_000_000
    chain.evm[(a, contract("ethereum", "USDC"))] = 12_345_678
    chain.evm[(a, contract("ethereum", "SHIB"))] = 1
    got = chains.read(
        "ethereum", chains.Watch([a.upper().replace("0X", "0x")]), settings_for(chain)
    )
    assert got.balances == {
        "ETH": Decimal("1.5"),
        "USDC": Decimal("12.345678"),
        "SHIB": Decimal("1E-18"),
    }
    rpc = [c for c in chain.calls if isinstance(c, tuple)][0]
    assert rpc[1] == "/rpc/ethereum" and len(rpc[2]) == 1 + len(nets.TOKENS["ethereum"])


def test_both_usdt_tokens_on_optimism_add_up(chain):
    a = ETH_ADDR
    chain.evm[(a, contract("optimism", "USDT", 0))] = 1_000_000
    chain.evm[(a, contract("optimism", "USDT", 1))] = 2_500_000
    got = chains.read("optimism", chains.Watch([a]), settings_for(chain))
    assert got.balances == {"USDT": Decimal("3.5")}


def test_a_node_without_batches_is_explained(chain):
    chain.batch_ok = False
    with pytest.raises(SourceError, match="batch"):
        chains.read("base", chains.Watch([ETH_ADDR]), settings_for(chain))


# ---- through the app -------------------------------------------------------------------------


def onchain_wallet(c, network, address=None):
    body = {"name": f"{network} wallet", "kind": "onchain", "network": network}
    if address:
        body["address"] = address
    r = c.post("/api/wallets", json=body, headers=H)
    assert r.status_code == 201, r.text
    return r.json()


def point_at(c, chain):
    body = {
        "esplora_url": chain.url,
        "rpc": {n: f"{chain.url}/rpc/{n}" for n in chains.DEFAULT_RPC},
    }
    assert c.put("/api/sync/chains", json=body, headers=H).status_code == 200


def test_an_xpub_wallet_syncs(logged_in, app, chain):
    point_at(logged_in, chain)
    chain.btc[derive(ZPUB, "wpkh", 0, 0)] = (25_000_000, 0, 2)
    w = onchain_wallet(logged_in, "bitcoin")
    r = logged_in.put(
        f"/api/wallets/{w['id']}/source", json={"kind": "onchain", "xpub": ZPUB}, headers=H
    )
    assert r.status_code == 200, r.text
    assert r.json()["sync"]["label"] == "Bitcoin zpub…tZYs" and ZPUB not in r.text
    with app.state.session_factory() as db:
        src = db.get(WalletSource, w["id"])
        assert ZPUB not in src.watch_encrypted  # encrypted: it reveals every address
    out = logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H).json()
    assert out["ok"], out
    assert out["sync"]["info"]["used_addresses"] == 1
    holdings = logged_in.get(f"/api/wallets/{w['id']}").json()["holdings"]
    assert [(h["symbol"], h["amount"]) for h in holdings] == [("BTC", "0.25")]
    audit = " ".join(e["detail"] for e in logged_in.get("/api/audit?limit=20").json())
    assert ZPUB not in audit and "zpub…tZYs" in audit


def test_an_ethereum_wallet_syncs_from_its_own_address(logged_in, chain):
    point_at(logged_in, chain)
    w = onchain_wallet(logged_in, "polygon", ETH_ADDR)
    chain.evm[(ETH_ADDR, "native")] = 3 * 10**18  # POL: not a built-in coin
    chain.evm[(ETH_ADDR, contract("polygon", "USDC"))] = 7_000_000
    r = logged_in.put(f"/api/wallets/{w['id']}/source", json={"kind": "onchain"}, headers=H)
    assert r.status_code == 200, r.text  # no addresses given: the wallet's own
    out = logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H).json()
    assert out["ok"], out
    holdings = logged_in.get(f"/api/wallets/{w['id']}").json()["holdings"]
    assert [(h["symbol"], h["amount"]) for h in holdings] == [("USDC", "7")]
    assert out["sync"]["untracked"] == [{"asset": "POL", "amount": "3"}]


@pytest.mark.parametrize(
    "body, status, words",
    [
        (
            {
                "kind": "onchain",
                "xpub": "xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiCh"
                "kVvvNKmPGJxWUtL6LZNqEXrgLaxFbTmNfZ5ruHAMJGkxEGxV7oi",
            },
            422,
            "PRIVATE key",
        ),
        ({"kind": "onchain", "addresses": ["0x1234"]}, 422, "doesn't look like"),
        ({"kind": "exchange", "connection_id": 1}, 422, "Only exchange wallets"),
    ],
)
def test_onchain_refusals(logged_in, app, body, status, words):
    w = onchain_wallet(logged_in, "bitcoin")
    r = logged_in.put(f"/api/wallets/{w['id']}/source", json=body, headers=H)
    assert r.status_code == status and words in r.json()["detail"], r.text
    assert "xprv9s21" not in r.text
    with app.state.session_factory() as db:
        assert db.scalar(select(WalletSource)) is None


def test_exchange_wallets_dont_take_addresses(logged_in):
    w = logged_in.post("/api/wallets", json={"name": "Ex", "kind": "exchange"}, headers=H).json()
    r = logged_in.put(
        f"/api/wallets/{w['id']}/source",
        json={"kind": "onchain", "addresses": [ETH_ADDR]},
        headers=H,
    )
    assert r.status_code == 422 and "Only on-chain wallets" in r.json()["detail"]


def test_chain_settings_api(logged_in, app):
    from tests.wallet_helpers import user_with

    got = logged_in.get("/api/sync/chains").json()
    assert got["esplora_url"] == chains.DEFAULT_ESPLORA and got["defaults"]["rpc"]["base"]
    bad = {"esplora_url": "http://mempool.example/api"}
    assert logged_in.put("/api/sync/chains", json=bad, headers=H).status_code == 422
    good = {"esplora_url": "https://my-node.example/api", "rpc": {"base": "https://rpc.example"}}
    assert logged_in.put("/api/sync/chains", json=good, headers=H).status_code == 200
    entry = logged_in.get("/api/audit?q=sync.chains").json()[0]
    assert "base, bitcoin" in entry["detail"]
    viewer = user_with(app, logged_in, "viewer", ["wallets.view"])
    assert viewer.get("/api/sync/chains").status_code == 403
