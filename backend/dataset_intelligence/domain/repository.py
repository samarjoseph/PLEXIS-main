from abc import ABC, abstractmethod
from typing import Optional, List
from dataset_intelligence.models_v2 import DatasetKnowledgeObject

class IDKORepository(ABC):
    """
    Interface for Dataset Knowledge Object persistence.
    Abstracts storage implementation (Memory, Redis, PostgreSQL).
    """

    @abstractmethod
    def save(self, dko: DatasetKnowledgeObject) -> None:
        """Save a fully synthesized DKO."""
        pass

    @abstractmethod
    def load(self, fingerprint: str) -> Optional[DatasetKnowledgeObject]:
        """Load a full DKO by fingerprint."""
        pass
        
    @abstractmethod
    def load_partial(self, fingerprint: str, sections: List[str]) -> Optional[DatasetKnowledgeObject]:
        """
        Lazy-load partial sections of a DKO for enterprise datasets.
        Sections can be 'columns', 'knowledge_graph', etc.
        """
        pass

    @abstractmethod
    def exists(self, fingerprint: str) -> bool:
        """Check if a DKO exists."""
        pass

    @abstractmethod
    def invalidate(self, fingerprint: str) -> None:
        """Remove a DKO from the repository."""
        pass
