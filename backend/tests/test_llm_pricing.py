from decimal import Decimal

from llm.pricing import compute_cost


def test_sonnet_cost_with_cache_and_search():
    cost = compute_cost(
        "claude-sonnet-5",
        input_tokens=1_000_000,  # $2
        output_tokens=100_000,  # $1
        cache_write_tokens=1_000_000,  # $2 * 1.25
        cache_read_tokens=1_000_000,  # $2 * 0.1
        web_search_requests=3,  # $0.03
    )
    assert cost == Decimal("5.730000")


def test_batch_discount_applies_to_tokens_only():
    full = compute_cost("claude-haiku-4-5-20251001", input_tokens=2_000_000, output_tokens=200_000)
    batch = compute_cost("claude-haiku-4-5-20251001", input_tokens=2_000_000, output_tokens=200_000, is_batch=True)
    assert full == Decimal("3.000000")
    assert batch == Decimal("1.500000")


def test_unknown_model_costs_zero():
    assert compute_cost("mystery-model", input_tokens=10**6) == 0
