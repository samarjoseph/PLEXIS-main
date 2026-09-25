"""
Analytical Persistence Integration Test — ASCII output (Windows console compatible).
Run: python tests/run_persistence_test.py
"""
import sys, os

# Force UTF-8 output
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PASS = 0
FAIL = 0

def check(name, ok, detail=''):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name}" + (f" -- {detail}" if detail else ""))

print("=" * 60)
print("PLEXIS - Analytical Persistence Integration Test")
print("=" * 60)

# ── [1] Import checks ────────────────────────────────────────────────────────
print("\n[1] Import checks")
try:
    from db.models.result_row import AnalysisResultRow
    check("AnalysisResultRow import", True)
except Exception as e:
    check("AnalysisResultRow import", False, str(e))

try:
    from db.models.analysis_action import AnalysisAction
    check("AnalysisAction import", True)
except Exception as e:
    check("AnalysisAction import", False, str(e))

try:
    from db.repositories.result_row_repository import result_row_repository
    check("ResultRowRepository import", True)
except Exception as e:
    check("ResultRowRepository import", False, str(e))

try:
    from db.repositories.analysis_action_repository import analysis_action_repository
    check("AnalysisActionRepository import", True)
except Exception as e:
    check("AnalysisActionRepository import", False, str(e))

try:
    from db.services.analysis_action_service import analysis_action_service
    check("AnalysisActionService import", True)
except Exception as e:
    check("AnalysisActionService import", False, str(e))

try:
    from analytics.session_recorder import session_recorder
    check("SessionRecorder import", True)
except Exception as e:
    check("SessionRecorder import", False, str(e))

# ── [2] ORM model attribute checks ──────────────────────────────────────────
print("\n[2] ORM model attribute checks")
try:
    from db.models.operation import AnalysisOperation
    check("AnalysisOperation.retry_of_operation_id", hasattr(AnalysisOperation, 'retry_of_operation_id'))
    check("AnalysisOperation.result_rows", hasattr(AnalysisOperation, 'result_rows'))
    check("AnalysisOperation.actions", hasattr(AnalysisOperation, 'actions'))
except Exception as e:
    check("AnalysisOperation attrs", False, str(e))

try:
    from db.models.result_row import AnalysisResultRow
    row = AnalysisResultRow()
    check("AnalysisResultRow.source_row_number", hasattr(row, 'source_row_number'))
    check("AnalysisResultRow.record_data_json", hasattr(row, 'record_data_json'))
    check("AnalysisResultRow.to_dict()", callable(getattr(row, 'to_dict', None)))
except Exception as e:
    check("AnalysisResultRow attrs", False, str(e))

try:
    from db.models.analysis_action import AnalysisAction
    action = AnalysisAction()
    check("AnalysisAction.action_type", hasattr(action, 'action_type'))
    check("AnalysisAction.action_metadata_json", hasattr(action, 'action_metadata_json'))
except Exception as e:
    check("AnalysisAction attrs", False, str(e))

# ── [3] Executor _row_number check ──────────────────────────────────────────
print("\n[3] Executor _row_number check")
try:
    import pandas as pd
    from executor.pandas_executor import pandas_executor
    from planner.schema import AnalyticalPlan

    df = pd.DataFrame({
        'name': ['Alice', 'Bob', 'Charlie'],
        'age':  [28, 65, 41],
    })
    plan = AnalyticalPlan(
        intent='highest_age',
        operation='max',
        target_column='age',
        parameters={},
        raw={},
    )
    result = pandas_executor.execute(plan, df)
    check("executor.execute(max, age) success", result.success)
    check("result.value == 65", result.value == 65)
    if result.matching_rows:
        has_row_num = '_row_number' in result.matching_rows[0]
        check("matching_rows[0] has _row_number", has_row_num)
        if has_row_num:
            rn = result.matching_rows[0]['_row_number']
            # Bob is at DataFrame index 1 → source_row_number should be 2
            check(f"_row_number=2 (Bob at df index 1)", rn == 2, f"got {rn}")
    else:
        check("matching_rows not empty", False, "no matching rows")
except Exception as e:
    import traceback
    check("Executor _row_number", False, str(e))
    traceback.print_exc()

# ── [4] DB connectivity + schema ────────────────────────────────────────────
print("\n[4] DB connectivity + migration 003 schema")
try:
    from db.session import db_session
    from sqlalchemy import text

    with db_session() as db:
        db.execute(text("SELECT 1"))
        check("DB connection", True)

        r = db.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name IN ('analysis_result_rows','analysis_actions') "
            "ORDER BY table_name"
        ))
        tables = [x[0] for x in r]
        check("analysis_result_rows table", 'analysis_result_rows' in tables)
        check("analysis_actions table", 'analysis_actions' in tables)

        r2 = db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='analysis_operations' "
            "AND column_name='retry_of_operation_id'"
        ))
        check("retry_of_operation_id column", bool(list(r2)))

except Exception as e:
    print(f"  SKIP: DB test - {e}")

# ── Summary ──────────────────────────────────────────────────────────────────
print()
print("=" * 60)
total = PASS + FAIL
print(f"RESULTS: {PASS}/{total} PASS  {FAIL}/{total} FAIL")
if FAIL == 0:
    print("ALL TESTS PASSED")
else:
    print(f"WARNING: {FAIL} FAILURE(S)")
print("=" * 60)

sys.exit(0 if FAIL == 0 else 1)
