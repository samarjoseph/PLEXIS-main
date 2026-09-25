import sys
import os

# Add the backend directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from unittest.mock import MagicMock
from planner.core import planner_engine

def mock_dko():
    # Use MagicMock to mock the DKO and its properties
    dko = MagicMock()
    
    def make_col(name, role_val="Unknown"):
        col = MagicMock()
        col.name = name
        role_mock = MagicMock()
        role_mock.value = role_val
        col.role = role_mock
        return col

    dko.get_primary_metrics.return_value = [make_col("Revenue"), make_col("Quantity"), make_col("Discount")]
    dko.get_grouping_dimensions.return_value = [make_col("Region"), make_col("Category")]
    dko.get_time_dimensions.return_value = [make_col("Date")]
    
    # identifier is fetched from columns.values()
    dko.columns = {"Order_ID": make_col("Order_ID", "Identifier")}
    return dko

def test_planner():
    dko = mock_dko()
    
    queries = [
        "What is the total revenue by region?",
        "Show me a trend of quantity sold over time.",
        "Which category has the highest average discount?"
    ]
    
    for query in queries:
        print(f"\n--- Query: {query} ---")
        try:
            plan = planner_engine.plan(query, dko)
            print(f"Intent: {plan.intent}")
            print(f"Operation: {plan.operation}")
            print(f"Target Column: {plan.target_column}")
            print(f"Group By: {plan.group_by}")
            print(f"Confidence: {plan.confidence}")
            print(f"Reasoning: {plan.reasoning.why_operation}")
        except Exception as e:
            print(f"Error planning query: {e}")

if __name__ == "__main__":
    test_planner()
