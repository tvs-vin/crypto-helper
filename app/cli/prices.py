"""`crypto-helper prices check`: fetch live prices straight from the source and show them.

It bypasses the server's cache, so it's the way to check that CoinGecko (or the mock)
really answers from this machine.
"""

from app.cli.common import CliError, bad, dim, load_settings, ok
from app.prices.catalog import BUILTIN_COINS, FIATS
from app.prices.providers import ProviderError, make_provider


def prices_check(fiat: str) -> int:
    fiat = fiat.lower()
    if fiat not in FIATS:
        raise CliError(f"fiat must be one of {', '.join(FIATS)}")
    settings = load_settings()
    provider = make_provider(settings)
    ids = {cid: (symbol, name) for symbol, (cid, name) in BUILTIN_COINS.items()}
    print(dim(f"Asking {provider.name} for {len(ids)} coins in {fiat.upper()}..."))
    try:
        quotes = provider.fetch(sorted(ids), [fiat])
    except ProviderError as e:
        print(bad(f"Failed: {e}"))
        return 1
    print(f"{'COIN':6} {'NAME':14} {'PRICE':>22} {'24H':>9}")
    for cid, (symbol, name) in sorted(ids.items(), key=lambda kv: kv[1][0]):
        q = quotes.get(cid, {}).get(fiat)
        if q is None:
            print(f"{symbol:6} {name:14} {'(no price)':>22}")
            continue
        change = f"{q.change_24h:+.2f}%" if q.change_24h is not None else "-"
        print(f"{symbol:6} {name:14} {format(q.price, 'f'):>22} {change:>9}")
    missing = len(ids) - len(quotes)
    print(
        ok(f"{len(quotes)} of {len(ids)} coins priced.")
        if not missing
        else bad(f"{missing} coin(s) had no price.")
    )
    print(dim(provider.attribution))
    return 0 if not missing else 1
