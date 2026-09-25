"""
Relationship Discovery

Discovers relationships between columns.
e.g. Which dimensions make sense to slice which metrics.
"""
from typing import Dict, Any
from .ontology import ColumnOntology

def discover_relationships(columns: Dict[str, ColumnOntology]) -> Dict[str, Any]:
    """
    Detect relationships between dimensions and metrics.
    For now, this returns a generic mapping assuming all metrics can be
    sliced by all dimensions, but in a real system this would use correlation
    analysis from the profiler.
    """
    metrics = [c.name for c in columns.values() if c.role == "Metric"]
    dimensions = [c.name for c in columns.values() if c.role == "Dimension"]
    times = [c.name for c in columns.values() if c.role == "Time"]
    
    return {
        "metrics_to_dimensions": {m: dimensions for m in metrics},
        "metrics_to_time": {m: times for m in metrics},
    }
