"""Token pricing for cost accounting (USD per 1M tokens: input, output)."""

USD_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-nano": (0.20, 1.25),
}
DEFAULT_PRICE = (0.40, 1.60)
USD_TO_EUR = 0.92  # fixed planning rate, stated in the README assumptions


def cost_eur(model: str, tokens_in: int, tokens_out: int) -> float:
    p_in, p_out = USD_PER_1M.get(model, DEFAULT_PRICE)
    return round((tokens_in * p_in + tokens_out * p_out) / 1_000_000 * USD_TO_EUR, 6)
