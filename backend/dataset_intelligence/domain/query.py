from typing import List, Any
from .specifications import Specification
from dataset_intelligence.models_v2 import DatasetKnowledgeObject, ColumnIntelligence, KnowledgeGraph, DatasetIdentity

class KnowledgeQueryAPI:
    """
    Read Model (CQRS) for the Dataset Knowledge Object.
    Executes Specifications against an immutable DKO.
    """
    def __init__(self, dko: DatasetKnowledgeObject):
        self._dko = dko

    def query(self, specification: Specification) -> List[Any]:
        """Generic query method applying a specification to all columns."""
        return [col for col in self._dko.columns.values() if specification.is_satisfied_by(col)]

    def find_columns(self, specification: Specification) -> List[ColumnIntelligence]:
        """Find columns matching a specification."""
        return [col for col in self._dko.columns.values() if specification.is_satisfied_by(col)]

    def find_relationships(self, specification: Specification) -> KnowledgeGraph:
        """
        Find relationships matching a specification. 
        (Implementation depends on Relationship Specification specifics)
        """
        # For now, returning full graph, filtering should be implemented based on specs.
        return self._dko.knowledge_graph

    def find_entities(self, specification: Specification) -> List[str]:
        """Find business entities matching a specification."""
        return [entity for entity in self._dko.identity.primary_entities if specification.is_satisfied_by(entity)]

    @property
    def identity(self) -> DatasetIdentity:
        """Returns the dataset identity."""
        return self._dko.identity
