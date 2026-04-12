class RateLimitExhausted(Exception):
    """Raised when all LLM providers return 429 Rate Limit Exhausted."""
    pass
