"""
Derived Metric Discovery

Identifies potential analytical metrics that can be derived from existing columns.
e.g. Revenue + Cost -> Profit Margin.
"""
from typing import Dict, List
from .ontology import ColumnOntology

def discover_derived_metrics(columns: Dict[str, ColumnOntology], domain: str) -> List[Dict[str, str]]:
    """
    Discover metrics that can be calculated from existing columns.
    """
    derived = []
    
    concepts = {col.concept: col.name for col in columns.values() if col.concept}
    names = {col.name.lower(): col.name for col in columns.values()}
    
    # Financial: Profit
    if 'revenue_metric' in concepts and 'cost_metric' in concepts:
        rev_col = concepts['revenue_metric']
        cost_col = concepts['cost_metric']
        derived.append({
            "name": "Profit",
            "formula": f"[{rev_col}] - [{cost_col}]",
            "description": "Calculated by subtracting Cost from Revenue"
        })
        derived.append({
            "name": "Profit Margin",
            "formula": f"([{rev_col}] - [{cost_col}]) / [{rev_col}]",
            "description": "Percentage of revenue that remains as profit"
        })
        
    # Financial: Discount Rate
    if 'revenue_metric' in concepts and 'discount_metric' in concepts:
        rev_col = concepts['revenue_metric']
        disc_col = concepts['discount_metric']
        derived.append({
            "name": "Discount Rate",
            "formula": f"[{disc_col}] / ([{rev_col}] + [{disc_col}])",
            "description": "Effective discount percentage applied"
        })

    # Generic: Growth Rate
    times = [col for col in columns.values() if col.role == "Time"]
    primary_metric = next((col.name for col in columns.values() if col.is_primary_metric), None)
    
    if times and primary_metric:
        derived.append({
            "name": f"{primary_metric} Growth Rate",
            "formula": f"Requires time-series calculation over [{times[0].name}]",
            "description": f"Period-over-period growth of {primary_metric}"
        })
        
    return derived
