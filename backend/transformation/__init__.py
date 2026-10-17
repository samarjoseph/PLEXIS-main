"""
Transformation package — deterministic data-mutation pipeline for Plexis.

Provides:
  - contracts.py  : dataclasses (TransformationPlan, TransformationResult, AffectedCell, VersionInfo)
  - planner.py    : TransformationPlanner — computes plans without mutating DataFrames
  - executor.py   : TransformationExecutor — applies approved plans, persists versions
  - store.py      : TransformationStore — L1 in-memory plan cache
"""
