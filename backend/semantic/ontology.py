"""
Ontology Dataclasses and Orchestrator

Defines the core semantic structures and the SemanticBuilder that coordinates
the creation of the dataset ontology.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

@dataclass
class ColumnOntology:
    """
    Semantic understanding of a single column.
    """
    name: str
    role: str  # Metric, Dimension, Identifier, Time, Attribute
    concept: Optional[str] = None  # e.g., 'revenue_metric', 'geographic_dimension'
    description: Optional[str] = None
    is_primary_metric: bool = False
    is_primary_date: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "concept": self.concept,
            "description": self.description,
            "is_primary_metric": self.is_primary_metric,
            "is_primary_date": self.is_primary_date
        }

@dataclass
class DatasetOntology:
    """
    Complete semantic understanding of a dataset.
    """
    dataset_name: str
    domain: str  # e.g., 'Sales/Retail', 'HR', 'Education'
    columns: Dict[str, ColumnOntology] = field(default_factory=dict)
    derived_metrics: List[Dict[str, str]] = field(default_factory=list)
    relationships: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "domain": self.domain,
            "columns": {k: v.to_dict() for k, v in self.columns.items()},
            "derived_metrics": self.derived_metrics,
            "relationships": self.relationships
        }
    
    def get_metrics(self) -> List[ColumnOntology]:
        return [col for col in self.columns.values() if col.role == "Metric"]
        
    def get_dimensions(self) -> List[ColumnOntology]:
        return [col for col in self.columns.values() if col.role == "Dimension"]
        
    def get_times(self) -> List[ColumnOntology]:
        return [col for col in self.columns.values() if col.role == "Time"]


class SemanticBuilder:
    """
    Orchestrates the construction of a DatasetOntology from a raw profile.
    """
    
    def build(self, dataset_name: str, schema_profile: Dict[str, Any], data_sample: Optional[Dict[str, Any]] = None) -> DatasetOntology:
        """
        Builds the complete semantic ontology for a dataset.
        
        Args:
            dataset_name: Name or fingerprint of the dataset.
            schema_profile: The technical profile (dtypes, nulls, unique counts) from the profiler.
            data_sample: A sample of row data for better LLM context (optional).
            
        Returns:
            A fully populated DatasetOntology.
        """
        # We will import these lazily to avoid circular dependencies 
        # and keep the orchestrator clean.
        from .classifier import classify_columns
        from .domain import detect_domain
        from .derived import discover_derived_metrics
        from .relationships import discover_relationships
        
        # 1. Classify columns
        columns = classify_columns(schema_profile, data_sample)
        
        # 2. Detect domain
        domain = detect_domain(dataset_name, columns, data_sample)
        
        # 3. Discover derived metrics
        derived = discover_derived_metrics(columns, domain)
        
        # 4. Discover relationships
        relationships = discover_relationships(columns)
        
        return DatasetOntology(
            dataset_name=dataset_name,
            domain=domain,
            columns=columns,
            derived_metrics=derived,
            relationships=relationships
        )

