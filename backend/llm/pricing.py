from decimal import Decimal

from django.conf import settings

MILLION = Decimal(1_000_000)


def _d(x) -> Decimal:
    return Decimal(str(x))


def compute_cost(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    web_search_requests: int = 0,
    is_batch: bool = False,
) -> Decimal:
    """USD cost of one call. Unknown models cost 0 (and should be added to LLM_PRICING)."""
    prices = settings.LLM_PRICING.get(model)
    if prices is None:
        return Decimal(0)
    inp, out = _d(prices["input"]), _d(prices["output"])
    token_cost = (
        input_tokens * inp
        + cache_write_tokens * inp * _d(settings.LLM_CACHE_WRITE_MULTIPLIER)
        + cache_read_tokens * inp * _d(settings.LLM_CACHE_READ_MULTIPLIER)
        + output_tokens * out
    ) / MILLION
    if is_batch:
        token_cost *= _d(settings.LLM_BATCH_DISCOUNT)
    search_cost = web_search_requests * _d(settings.LLM_WEB_SEARCH_USD_PER_REQUEST)
    return (token_cost + search_cost).quantize(Decimal("0.000001"))
