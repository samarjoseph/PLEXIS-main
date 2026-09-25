"""
Concept Mapping

Maps specific column names to universal analytical concepts.
This allows the system to understand that "Sales", "Revenue", and "Income"
all represent the `revenue_metric` concept.
"""
from typing import Optional

# Mappings of normalized column names to universal concepts
CONCEPT_MAP = {
    # Financial Metrics
    'revenue': 'revenue_metric',
    'sales': 'revenue_metric',
    'income': 'revenue_metric',
    'profit': 'profit_metric',
    'margin': 'margin_metric',
    'cost': 'cost_metric',
    'expense': 'cost_metric',
    'discount': 'discount_metric',
    'tax': 'tax_metric',
    'price': 'price_metric',
    
    # Educational Metrics
    'score': 'score_metric',
    'grade': 'score_metric',
    'gpa': 'gpa_metric',
    'attendance': 'attendance_metric',
    
    # HR Metrics
    'salary': 'salary_metric',
    'bonus': 'bonus_metric',
    'tenure': 'tenure_metric',
    'age': 'age_metric',
    
    # Geographic Dimensions
    'country': 'country_dimension',
    'state': 'state_dimension',
    'region': 'region_dimension',
    'city': 'city_dimension',
    'zip': 'zip_dimension',
    'postal': 'zip_dimension',
    
    # Organizational Dimensions
    'department': 'department_dimension',
    'team': 'team_dimension',
    'manager': 'manager_dimension',
    'role': 'role_dimension',
    
    # Product Dimensions
    'category': 'category_dimension',
    'product': 'product_dimension',
    'brand': 'brand_dimension',
    
    # Demographic Dimensions
    'gender': 'gender_dimension',
    'sex': 'gender_dimension',
    'ethnicity': 'ethnicity_dimension',
    
    # Time
    'date': 'date_time',
    'year': 'year_time',
    'month': 'month_time',
    'quarter': 'quarter_time',
    'day': 'day_time',
}

def map_concept(column_name: str, role: str) -> Optional[str]:
    """
    Map a column name to a universal concept based on its name and role.
    """
    normalized = column_name.lower().strip()
    
    # Exact match or substring match for common concepts
    for key, concept in CONCEPT_MAP.items():
        if key in normalized:
            # Simple sanity check: don't map a Dimension to a Metric concept
            if role == "Metric" and not concept.endswith("_metric"):
                continue
            if role == "Dimension" and not concept.endswith("_dimension"):
                continue
            if role == "Time" and not concept.endswith("_time"):
                continue
            return concept
            
    return None
