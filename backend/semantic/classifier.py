"""
Column Classifier

Analyzes a dataset schema profile and classifies each column into a semantic role:
- Metric (numeric values to be aggregated)
- Dimension (categorical values to group by)
- Identifier (unique IDs, not for analysis)
- Time (temporal data)
- Attribute (descriptive text, not for grouping)
"""
import json
import logging
from typing import Dict, Any, Optional

from providers import provider_engine
from .ontology import ColumnOntology
from .concepts import map_concept

logger = logging.getLogger(__name__)

CLASSIFIER_SYSTEM_PROMPT = """You are an expert Data Architect.
Your task is to analyze a dataset schema and classify each column into one of these semantic roles:

1. "Metric" - Numeric values that make sense to aggregate (sum, average). Examples: Revenue, Profit, Age, Score, Quantity, Price.
2. "Dimension" - Categorical values used to slice or group data. Examples: Region, Category, Gender, Department, Status, Grade.
3. "Identifier" - Unique keys or IDs that should NOT be analyzed or grouped. Examples: Student_ID, UUID, Order_Number, SSN.
4. "Time" - Temporal dates or times. Examples: Order_Date, Created_At, Year, Month.
5. "Attribute" - Descriptive text that isn't really a category. Examples: Notes, Description, Comments, Full Name (usually).

RULES:
- A column with many unique strings is an Identifier or Attribute.
- A numeric column (like Year or ID) might not be a Metric. If it's a Year, it's Time. If it's CustomerID, it's Identifier.
- A numeric column with very few unique values (e.g., 0/1 for Is_Active) is a Dimension.
- You must output ONLY a valid JSON object where keys are column names and values are the exact role strings (Metric, Dimension, Identifier, Time, Attribute). Do not include markdown formatting or backticks around the JSON.
"""

def classify_columns(schema_profile: Dict[str, Any], data_sample: Optional[Dict[str, Any]] = None) -> Dict[str, ColumnOntology]:
    """
    Classify columns using a mix of heuristics and LLM reasoning.
    """
    
    # Format the prompt context
    context = {
        "schema": schema_profile,
    }
    if data_sample:
        context["sample"] = data_sample
        
    prompt = f"Analyze the following dataset profile and classify each column.\n\n{json.dumps(context, indent=2)}\n\nOutput only a JSON object."
    
    from providers.domain.contracts import AIRequest
    response = provider_engine.generate(
        AIRequest(
            task="chat",
            messages=[{"role": "user", "content": prompt}],
            system_prompt=CLASSIFIER_SYSTEM_PROMPT,
            temperature=0.1,
        )
    )
    
    classifications = {}
    
    if response.success:
        try:
            # Strip potential markdown formatting
            text = response.text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
                
            raw_classifications = json.loads(text.strip())
            
            for col_name, role in raw_classifications.items():
                if role not in ["Metric", "Dimension", "Identifier", "Time", "Attribute"]:
                    role = "Attribute" # fallback
                    
                concept = map_concept(col_name, role)
                
                classifications[col_name] = ColumnOntology(
                    name=col_name,
                    role=role,
                    concept=concept,
                )
        except Exception as e:
            logger.error(f"Failed to parse classification JSON: {e}\nResponse: {response.text}")
            classifications = _fallback_classification(schema_profile)
    else:
        logger.error(f"Classification generation failed: {response.error}")
        classifications = _fallback_classification(schema_profile)
        
    # Mark primary metric/date based on heuristics
    _mark_primaries(classifications)
        
    return classifications


def _fallback_classification(schema_profile: Dict[str, Any]) -> Dict[str, ColumnOntology]:
    """Fallback heuristic classifier if LLM fails."""
    columns = {}
    for col_name, dtype in schema_profile.items():
        # In this simplistic fallback, we just check dtype strings
        # A real profiler would pass more rich metadata, but we'll approximate.
        dt = str(dtype).lower()
        role = "Attribute"
        if "int" in dt or "float" in dt:
            if "id" in col_name.lower():
                role = "Identifier"
            elif "year" in col_name.lower():
                role = "Time"
            else:
                role = "Metric"
        elif "datetime" in dt or "date" in col_name.lower():
            role = "Time"
        elif "id" in col_name.lower():
            role = "Identifier"
        else:
            role = "Dimension"
            
        columns[col_name] = ColumnOntology(name=col_name, role=role, concept=map_concept(col_name, role))
        
    return columns


def _mark_primaries(columns: Dict[str, ColumnOntology]):
    """Identify the most likely primary metric and primary date."""
    # Find primary date
    times = [c for c in columns.values() if c.role == "Time"]
    if times:
        # Simple heuristic: prioritize column containing 'date' or just the first one
        primary = next((c for c in times if 'date' in c.name.lower()), times[0])
        primary.is_primary_date = True
        
    # Find primary metric
    metrics = [c for c in columns.values() if c.role == "Metric"]
    if metrics:
        # Prioritize revenue, profit, total, score
        priorities = ['revenue', 'sales', 'profit', 'total', 'amount', 'score', 'price']
        primary = None
        for p in priorities:
            matches = [c for c in metrics if p in c.name.lower()]
            if matches:
                primary = matches[0]
                break
        
        if not primary:
            primary = metrics[0]
            
        primary.is_primary_metric = True
