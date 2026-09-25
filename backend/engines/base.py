"""Base engine interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Union
from core.context import ExecutionContext

@dataclass
class EngineResult:
    """Standardized result from any engine."""
    answer: str
    source: str = 'system'
    provider: Optional[str] = None
    dataset_info: Optional[Dict[str, Any]] = None
    chart_data: Optional[Dict[str, Any]] = None
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    facts: Dict[str, Any] = field(default_factory=dict)
    should_compose: bool = True
    # Evidence: EvidenceReference | EvidenceCollection | None
    # Typed as Any to avoid circular imports; capability layer sets this.
    # Passed through untouched to the API response layer.
    evidence: Optional[Any] = None

class BaseEngine(ABC):
    """Abstract base class for all Plexis engines."""
    
    @property
    @abstractmethod
    def engine_name(self) -> str: ...
    
    @abstractmethod
    def can_handle(self, context: ExecutionContext) -> bool: ...
    
    @abstractmethod
    def handle(self, context: ExecutionContext) -> EngineResult: ...
