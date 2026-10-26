"""Executor package — hybrid analytical execution engine (DuckDB + Pandas)."""
from executor.pandas_executor import pandas_executor, PandasExecutor, ExecutorResult
from executor.duckdb_executor import duckdb_executor, DuckDBExecutor
from executor.hybrid_executor import hybrid_executor, HybridExecutor

__all__ = [
    "pandas_executor",
    "PandasExecutor",
    "duckdb_executor",
    "DuckDBExecutor",
    "hybrid_executor",
    "HybridExecutor",
    "ExecutorResult",
]
