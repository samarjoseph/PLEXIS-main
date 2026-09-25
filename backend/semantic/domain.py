"""
Domain Detection

Infers the domain of the dataset (e.g., Sales, HR, Healthcare, Education)
based on the classified columns and available concepts.
"""
from typing import Dict, Any, Optional
from .ontology import ColumnOntology

def detect_domain(dataset_name: str, columns: Dict[str, ColumnOntology], data_sample: Optional[Dict[str, Any]] = None) -> str:
    """
    Detect the domain of the dataset.
    Uses heuristic scoring based on concepts and column names.
    """
    scores = {
        "Retail/Sales": 0,
        "Finance": 0,
        "HR": 0,
        "Education": 0,
        "Healthcare": 0,
        "Logistics": 0,
    }
    
    # Analyze by concepts
    for col in columns.values():
        concept = col.concept
        name = col.name.lower()
        
        if concept in ['revenue_metric', 'profit_metric', 'price_metric', 'cost_metric', 'discount_metric', 'margin_metric']:
            scores["Retail/Sales"] += 2
            scores["Finance"] += 1
            
        if concept in ['score_metric', 'gpa_metric', 'attendance_metric']:
            scores["Education"] += 3
            
        if concept in ['salary_metric', 'bonus_metric', 'tenure_metric', 'manager_dimension']:
            scores["HR"] += 3
            
        # Analyze by raw name patterns
        if any(w in name for w in ['order', 'product', 'customer', 'cart', 'checkout', 'sku']):
            scores["Retail/Sales"] += 2
            
        if any(w in name for w in ['student', 'teacher', 'class', 'course', 'school', 'grade', 'exam']):
            scores["Education"] += 2
            
        if any(w in name for w in ['employee', 'staff', 'hire', 'department', 'payroll', 'benefits']):
            scores["HR"] += 2
            
        if any(w in name for w in ['patient', 'doctor', 'diagnosis', 'treatment', 'hospital', 'ward']):
            scores["Healthcare"] += 3
            
        if any(w in name for w in ['shipment', 'delivery', 'warehouse', 'freight', 'tracking']):
            scores["Logistics"] += 3
            
        if any(w in name for w in ['stock', 'equity', 'dividend', 'portfolio', 'investment']):
            scores["Finance"] += 3

    # Analyze by dataset name
    ds_name = dataset_name.lower()
    if 'sales' in ds_name or 'order' in ds_name:
        scores["Retail/Sales"] += 3
    if 'hr' in ds_name or 'employee' in ds_name:
        scores["HR"] += 3
    if 'student' in ds_name or 'school' in ds_name:
        scores["Education"] += 3
        
    # Get the highest scoring domain
    max_score = 0
    best_domain = "Generic"
    
    for domain, score in scores.items():
        if score > max_score and score >= 3: # Threshold
            max_score = score
            best_domain = domain
            
    return best_domain
