"""
Integration test for Phase 1-6 of analytical persistence.
Tests: AnalysisResultRow, AnalysisAction models + session_recorder.

Run from backend/:
    python tests/test_analytical_persistence.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import traceback

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  ✅  {name}")
        PASS += 1
    else:
        print(f"  ❌  {name}{': ' + detail if detail else ''}")
        FAIL += 1

print("=" * 60)
print("PLEXIS — Analytical Persistence Integration Test")
print("=" * 60)

# ── Import tests ──────────────────────────────────────────────────────────────
print("\n[1] Import checks")
try:
    from db.models.result_row import AnalysisResultRow
    check("AnalysisResultRow importable", True)
except Exception as e:
    check("AnalysisResultRow importable", False, str(e))

try:
    from db.models.analysis_action import AnalysisAction
    check("AnalysisAction importable", True)
except Exception as e:
    check("AnalysisAction importable", False, str(e))

try:
    from db.repositories.result_row_repository import result_row_repository
    check("result_row_repository importable", True)
except Exception as e:
    check("result_row_repository importable", False, str(e))

try:
    from db.repositories.analysis_action_repository import analysis_action_repository
    check("analysis_action_repository importable", True)
except Exception as e:
    check("analysis_action_repository importable", False, str(e))

try:
    from db.services.analysis_action_service import analysis_action_service
    check("analysis_action_service importable", True)
except Exception as e:
    check("analysis_action_service importable", False, str(e))

try:
    from analytics.session_recorder import session_recorder
    check("session_recorder importable", True)
except Exception as e:
    check("session_recorder importable", False, str(e))

# ── ORM model attribute checks ────────────────────────────────────────────────
print("\n[2] ORM model attribute checks")
try:
    from db.models.operation import AnalysisOperation
    has_retry = hasattr(AnalysisOperation, 'retry_of_operation_id')
    check("AnalysisOperation.retry_of_operation_id exists", has_retry)
    has_result_rows = hasattr(AnalysisOperation, 'result_rows')
    check("AnalysisOperation.result_rows relationship exists", has_result_rows)
    has_actions = hasattr(AnalysisOperation, 'actions')
    check("AnalysisOperation.actions relationship exists", has_actions)
except Exception as e:
    check("AnalysisOperation extended attrs", False, str(e))

try:
    row = AnalysisResultRow()
    check("AnalysisResultRow instantiates", True)
    check("AnalysisResultRow has source_row_number", hasattr(row, 'source_row_number'))
    check("AnalysisResultRow has record_data_json", hasattr(row, 'record_data_json'))
    check("AnalysisResultRow has to_dict()", callable(getattr(row, 'to_dict', None)))
except Exception as e:
    check("AnalysisResultRow attributes", False, str(e))

try:
    action = AnalysisAction()
    check("AnalysisAction instantiates", True)
    check("AnalysisAction has action_type", hasattr(action, 'action_type'))
    check("AnalysisAction has action_metadata_json", hasattr(action, 'action_metadata_json'))
except Exception as e:
    check("AnalysisAction attributes", False, str(e))

# ── Executor _row_number check ─────────────────────────────────────────────────
print("\n[3] Executor _row_number check")
try:
    import pandas as pd
    from executor.pandas_executor import pandas_executor

    df = pd.DataFrame({
        'name': ['Alice', 'Bob', 'Charlie'],
        'age':  [28, 65, 41],
    })

    # Create a minimal plan-like object
    from planner.schema import AnalyticalPlan
    plan = AnalyticalPlan(
        intent='highest_age',
        operation='max',
        target_column='age',
        parameters={},
        raw={},
    )
    result = pandas_executor.execute(plan, df)
    check("Executor max(age) succeeds", result.success)
    if result.matching_rows:
        has_row_number = '_row_number' in result.matching_rows[0]
        check("matching_rows[0] has _row_number", has_row_number)
        if has_row_number:
            row_num = result.matching_rows[0]['_row_number']
            # Bob is at index 1 → source_row_number should be 2
            check(f"_row_number = {row_num} (expected 2 for index 1)", row_num == 2)
    else:
        check("matching_rows not empty", False, "empty result")
except Exception as e:
    check("Executor _row_number", False, str(e))
    traceback.print_exc()

# ── DB connectivity (optional) ─────────────────────────────────────────────────
print("\n[4] DB connectivity (skipped if no connection)")
try:
    from db.session import db_session
    from sqlalchemy import text
    with db_session() as db:
        result = db.execute(text("SELECT 1"))
        check("DB connection works", True)
        
        # Check tables exist
        result = db.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name IN ('analysis_result_rows','analysis_actions') "
            "ORDER BY table_name"
        ))
        tables = [r[0] for r in result]
        check("analysis_result_rows table exists", 'analysis_result_rows' in tables)
        check("analysis_actions table exists", 'analysis_actions' in tables)
        
        result = db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='analysis_operations' AND column_name='retry_of_operation_id'"
        ))
        cols = [r[0] for r in result]
        check("retry_of_operation_id column exists", bool(cols))

except Exception as e:
    print(f"  ⚠️  DB test skipped: {e}")

# ── Summary ────────────────────────────────────────────────────────────────────
print()
print("=" * 60)
total = PASS + FAIL
print(f"RESULTS: {PASS}/{total} PASS  {FAIL}/{total} FAIL")
if FAIL == 0:
    print("🎉 ALL TESTS PASSED")
else:
    print(f"⚠️  {FAIL} FAILURE(S)")
print("=" * 60)
