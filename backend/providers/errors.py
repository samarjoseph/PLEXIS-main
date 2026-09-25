class ProviderExecutionError(Exception):
    """Base class for provider execution errors."""
    pass

class ProviderAuthenticationError(ProviderExecutionError):
    """Raised when authentication with the provider fails."""
    pass

class ProviderRateLimitError(ProviderExecutionError):
    """Raised when the provider's rate limit is exceeded."""
    pass
