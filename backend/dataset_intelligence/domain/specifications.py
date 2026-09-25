from abc import ABC, abstractmethod
from typing import Any, List, Generic, TypeVar

T = TypeVar('T')

class Specification(ABC, Generic[T]):
    """Base class for the Specification Pattern in the Knowledge Query Layer."""

    @abstractmethod
    def is_satisfied_by(self, candidate: T) -> bool:
        pass

    def __and__(self, other: 'Specification[T]') -> 'Specification[T]':
        return AndSpecification(self, other)

    def __or__(self, other: 'Specification[T]') -> 'Specification[T]':
        return OrSpecification(self, other)

    def __invert__(self) -> 'Specification[T]':
        return NotSpecification(self)


class AndSpecification(Specification[T]):
    def __init__(self, *specs: Specification[T]):
        self.specs = specs

    def is_satisfied_by(self, candidate: T) -> bool:
        return all(spec.is_satisfied_by(candidate) for spec in self.specs)


class OrSpecification(Specification[T]):
    def __init__(self, *specs: Specification[T]):
        self.specs = specs

    def is_satisfied_by(self, candidate: T) -> bool:
        return any(spec.is_satisfied_by(candidate) for spec in self.specs)


class NotSpecification(Specification[T]):
    def __init__(self, spec: Specification[T]):
        self.spec = spec

    def is_satisfied_by(self, candidate: T) -> bool:
        return not self.spec.is_satisfied_by(candidate)


# Domain-specific specifications

class ColumnRoleSpecification(Specification[Any]):
    def __init__(self, *roles: str):
        self.roles = roles

    def is_satisfied_by(self, candidate: Any) -> bool:
        from dataset_intelligence.models_v2 import ColumnIntelligence
        if not isinstance(candidate, ColumnIntelligence):
            return False
        return candidate.role.value in self.roles


class SemanticTypeSpecification(Specification[Any]):
    def __init__(self, semantic_type: str):
        self.semantic_type = semantic_type

    def is_satisfied_by(self, candidate: Any) -> bool:
        from dataset_intelligence.models_v2 import ColumnIntelligence
        if not isinstance(candidate, ColumnIntelligence):
            return False
        return candidate.semantic_type.value == self.semantic_type


class ImportanceSpecification(Specification[Any]):
    def __init__(self, min_importance: float):
        self.min_importance = min_importance

    def is_satisfied_by(self, candidate: Any) -> bool:
        return hasattr(candidate, 'metadata') and candidate.metadata.importance >= self.min_importance
