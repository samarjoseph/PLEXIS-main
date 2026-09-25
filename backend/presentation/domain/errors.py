"""
Presentation Layer — Domain Errors

All custom exceptions for the presentation layer.
"""


class BundleExpiredError(Exception):
    """
    Raised when a KnowledgeBundle is requested from the ModuleRegistry
    but the session TTL has expired or the bundle was evicted under LRU policy.

    Callers should re-decompose from the cached DKO on disk.
    """
    def __init__(self, session_id: str):
        super().__init__(
            f"KnowledgeBundle for session '{session_id}' has expired or been evicted. "
            f"Re-decompose from the DKO cache."
        )
        self.session_id = session_id


class ModuleNotAvailableError(Exception):
    """
    Raised when a specific module is requested but its richness_score < threshold
    or the DKO had no data to populate it.
    """
    def __init__(self, module_id: str, reason: str = ""):
        super().__init__(
            f"Module '{module_id}' is not available for this dataset. {reason}"
        )
        self.module_id = module_id
