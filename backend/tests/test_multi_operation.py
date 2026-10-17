import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
import uuid

from router.master_router import MasterRouter
from core.context import ExecutionContext
from engines.analysis import AnalysisEngine

@pytest.fixture
def mock_df():
    return pd.DataFrame({
        "id": range(1, 101),  # This makes all rows unique
        "name": ["A"] * 100,
        "age": [20] * 50 + [None] * 50
    })

def test_multi_operation_analytics(mock_df):
    """Test that multiple deterministic requests are supported in one go."""
    
    context = ExecutionContext(message="How many missing values are there in total? Are there any duplicate rows? How many unique values does each column have?")
    context.dataset_id = str(uuid.uuid4())
    
    router = MasterRouter()
    
    # Mock LLM to return our expected JSON
    with patch.object(router, '_llm_interpret', return_value={
        "intent": "analysis",
        "operations": [
            {"type": "MISSING_VALUES"},
            {"type": "FIND_DUPLICATES"},
            {"type": "UNIQUE_VALUES"}
        ]
    }):
        payload = router.route(context)
        
        assert hasattr(context, "llm_operations")
        assert len(context.llm_operations) == 3
        
        # Now run AnalysisEngine
        engine = AnalysisEngine()
        
        with patch.object(engine, '_resolve_dataframe', return_value=mock_df):
            # Mock DB to avoid DB hit
            with patch.object(engine, '_get_db', return_value=MagicMock()):
                result = engine.handle(context)
                
                assert result.success is True
                assert result.should_compose is True
                assert "operations" in result.facts
                
                ops = result.facts["operations"]
                assert len(ops) == 3
                
                # Check missing values
                assert ops[0]["operation"] == "missing_values"
                assert ops[0]["value"]["total"] == 50
                
                # Check duplicates
                assert ops[1]["operation"] == "duplicates"
                assert ops[1]["value"]["duplicate_count"] == 0  # id makes rows unique
                
                # Check unique values
                assert ops[2]["operation"] == "unique_values"
                assert ops[2]["value"]["id"] == 100

def test_get_schema_with_types(mock_df):
    """Test get_schema now returns canonical types."""
    context = ExecutionContext(message="What are the data types of each column?")
    context.dataset_id = str(uuid.uuid4())
    
    router = MasterRouter()
    with patch.object(router, '_llm_interpret', return_value={
        "intent": "analysis",
        "operations": [
            {"type": "GET_SCHEMA"}
        ]
    }):
        router.route(context)
        
        engine = AnalysisEngine()
        with patch.object(engine, '_resolve_dataframe', return_value=mock_df):
            with patch.object(engine, '_get_db', return_value=MagicMock()):
                result = engine.handle(context)
                
                ops = result.facts["operations"]
                assert len(ops) == 1
                assert ops[0]["operation"] == "get_schema"
                
                columns = ops[0]["value"]["columns"]
                assert columns[0]["name"] == "id"
                assert columns[0]["dtype"] == "integer"

if __name__ == "__main__":
    pass
