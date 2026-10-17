"""Regression coverage for typed transformation snapshots and cold restore."""
from types import SimpleNamespace
import gzip

import numpy as np
import pandas as pd
import pytest

from datasets.version_codec import deserialize_dataframe, serialize_dataframe
from db.services.dataset_service import DatasetService
from router.master_router import MasterRouter, _parse_transform_from_message
from core.context import ExecutionContext
from transformation.executor import transformation_executor
from transformation.planner import transformation_planner


def test_typed_snapshot_round_trips_mixed_values_and_physical_dtypes():
    original = pd.DataFrame({"value": pd.Series([0, 0.0, "0", False, None], dtype=object)})
    restored = deserialize_dataframe(serialize_dataframe(original))

    assert restored["value"].tolist()[:4] == [0, 0.0, "0", False]
    assert type(restored.at[0, "value"]) is int
    assert type(restored.at[1, "value"]) is float
    assert type(restored.at[2, "value"]) is str
    assert type(restored.at[3, "value"]) is bool
    assert pd.isna(restored.at[4, "value"])


def test_cold_restore_uses_latest_version_snapshot(monkeypatch):
    base = SimpleNamespace(id="logical-dataset", original_filename="source.csv")
    versioned = SimpleNamespace(id="version-dataset", original_filename="source_v1.plexis.json")
    latest = SimpleNamespace(version_dataset_id="version-dataset", version_number=1)
    # This is the persisted result of fill-missing with 0; the uploaded source
    # has no such zeros and must not be used after a cold restore.
    upload_df = pd.DataFrame({"amount": pd.Series([np.nan, 0, "0", 7], dtype=object)})
    fill_plan = transformation_planner.plan(
        upload_df, {"type": "FILL_MISSING", "value": 0}, "logical-dataset"
    )
    post_fill = transformation_executor._execute(upload_df.copy(), fill_plan)
    snapshot = serialize_dataframe(post_fill)
    calls = []

    import importlib
    module = importlib.import_module("db.services.dataset_service")
    trans_repo = importlib.import_module("db.repositories.transformation_repository")
    monkeypatch.setattr(module.dataset_repository, "get_by_id", lambda db, did, uid: base if did == "logical-dataset" else versioned)
    monkeypatch.setattr(module.dataset_repository, "get_file_bytes", lambda db, did, uid: calls.append(did) or snapshot)
    monkeypatch.setattr(trans_repo.transformation_repository, "get_latest_version", lambda db, did: latest)
    monkeypatch.setattr(DatasetService, "_register_in_cache", lambda self, dataset, df: calls.append((dataset.id, df.copy())))

    logical, restored = DatasetService().restore_dataset_df(object(), "logical-dataset", "user")
    assert logical is base
    assert calls[0] == "version-dataset"
    assert restored["amount"].tolist() == [0, 0, "0", 7]
    assert type(restored.at[0, "amount"]) is int
    assert type(restored.at[1, "amount"]) is int
    assert type(restored.at[2, "amount"]) is str

    operation = _parse_transform_from_message('replace 0 with "unknown"')
    plan = transformation_planner.plan(restored, operation, "logical-dataset")
    preview = transformation_executor._execute(restored.copy(), plan)
    assert plan.affected_cells_count == 2
    assert preview["amount"].tolist() == ["unknown", "unknown", "0", 7]


def test_executor_persists_typed_snapshot_in_version_rows(monkeypatch):
    from db.models.dataset import DatasetFile
    from db.repositories import transformation_repository as repo_module

    class MemoryDB:
        def __init__(self):
            self.rows = []
        def add(self, row):
            self.rows.append(row)
        def flush(self):
            pass
        def commit(self):
            pass

    monkeypatch.setattr(repo_module.transformation_repository, "get_latest_version", lambda db, did: None)
    monkeypatch.setattr(
        repo_module.transformation_repository, "create_version",
        lambda db, **kwargs: SimpleNamespace(id="version-id", version_number=1),
    )
    monkeypatch.setattr(repo_module.transformation_repository, "mark_plan_applied", lambda db, pid: None)
    df = pd.DataFrame({"amount": pd.Series([0, 0.0, "0", False], dtype=object)})
    fill_plan = transformation_planner.plan(
        pd.DataFrame({"amount": [np.nan, 0, "0"]}),
        {"type": "FILL_MISSING", "value": 0}, "logical-dataset",
    )
    db = MemoryDB()
    version_id, _, _ = transformation_executor._persist_version(
        db, df, fill_plan, "11111111-1111-4111-8111-111111111111",
        "user-id", "source.csv",
    )
    stored_file = next(row for row in db.rows if isinstance(row, DatasetFile))
    decoded = deserialize_dataframe(gzip.decompress(stored_file.content))
    assert version_id
    assert decoded["amount"].tolist() == [0, 0.0, "0", False]
    assert [type(value) for value in decoded["amount"].tolist()] == [int, float, str, bool]


def test_quoted_replace_uses_typed_fast_path_and_semantic_matcher():
    message = 'replace "0" with "zero-string"'
    operation = _parse_transform_from_message(message)
    assert operation["_old_typed"]["value_type"] == "string"
    context = ExecutionContext(message=message, dataset_id="ds")
    result = MasterRouter()._fast_path(context)
    assert result and result.get("intent") == "TRANSFORM"
    routed_op = result.get("operation") or result.get("data", {}).get("operation")
    assert routed_op and routed_op.get("_old_typed", {}).get("value_type") == "string"

    df = pd.DataFrame({"amount": pd.Series([0, 0.0, "0", False], dtype=object)})
    plan = transformation_planner.plan(df, operation, "ds")
    preview = transformation_executor._execute(df.copy(), plan)
    assert plan.affected_cells_count == 1
    assert preview["amount"].tolist() == [0, 0.0, "zero-string", False]


def test_integer_zero_matches_float_zero_but_not_string_or_boolean():
    df = pd.DataFrame({"value": pd.Series([0, 0.0, "0", False], dtype=object)})
    operation = _parse_transform_from_message('replace 0 with "unknown"')
    plan = transformation_planner.plan(df, operation, "ds")
    result = transformation_executor._execute(df.copy(), plan)
    assert plan.affected_cells_count == 2
    assert result["value"].tolist() == ["unknown", "unknown", "0", False]


@pytest.mark.parametrize("token", [
    "none", "null", "missing", "true", "false", "0", "123", "1.5", "2026-01-01"
])
@pytest.mark.parametrize("quote", ["'", '"'])
def test_quoted_destination_never_reclassifies_null_like_or_numeric_text(token, quote):
    operation = _parse_transform_from_message(f"replace 0 with {quote}{token}{quote}")
    assert operation["new_value"] == token
    assert operation["_new_typed"]["value_type"] == "string"
    assert operation["_new_typed"]["was_quoted"] is True


def test_typed_destination_metadata_overrides_stale_raw_none_payload():
    from datasets.semantics.typed_literal import parse_literal
    df = pd.DataFrame({"phone": pd.Series([0, 7], dtype=object)})
    operation = {
        "type": "REPLACE_VALUES", "column": "phone", "columns": ["phone"],
        "old_value": 0, "new_value": None,
        "_old_typed": parse_literal("0").to_dict(),
        "_new_typed": parse_literal("none", was_quoted=True).to_dict(),
    }
    plan = transformation_planner.plan(df, operation, "typed-destination-ds")
    assert 'string("none")' in plan.operation_label
    assert plan.operation_payload["new_value"] == "none"
    assert plan.before_sample[0].after == "none"
    result = transformation_executor._execute(df.copy(), plan)
    assert result.loc[0, "phone"] == "none"
    assert type(result.loc[0, "phone"]) is str


def test_fast_path_extracts_quotes_from_original_message_not_normalized_query():
    context = ExecutionContext(
        message='replace 0 with "none"', dataset_id="quote-route-ds"
    )
    context.normalized_query = "replace 0 with none"
    routed = MasterRouter()._fast_path(context)
    assert routed and routed["intent"] == "TRANSFORM"
    assert routed["operation"]["_new_typed"]["value_type"] == "string"
    assert routed["operation"]["new_value"] == "none"


def test_ambiguous_transform_response_is_not_overwritten_by_composer(monkeypatch):
    from engines.transform import TransformEngine
    from core.composer import ResponseComposer
    from engines.base import EngineResult
    from datasets import registry as registry_module

    df = pd.DataFrame({
        "name": pd.Series([0, "Alex", "Mina"], dtype=object),
        "phone": pd.Series([0, "555", "666"], dtype=object),
        "age": pd.Series([0.0, 0.0, 32.0]),
    })
    monkeypatch.setattr(
        registry_module.dataset_registry,
        "get",
        lambda dataset_id: SimpleNamespace(dataframe=df),
    )
    context = ExecutionContext(message="replace 0 with 'none'", dataset_id="ds")
    context.intent = "transform"
    context.llm_operation = _parse_transform_from_message(context.message)

    result = TransformEngine().handle(context)
    assert result.success
    assert "Found integer(0) in 3 columns" in result.answer
    assert "Please specify which column" in result.answer
    assert result.should_compose is False
    clarification = result.metadata["clarification"]
    assert clarification["status"] == "AWAITING_CLARIFICATION"
    assert clarification["operation"] == "REPLACE_VALUES"
    assert clarification["source"]["value_type"] == "integer"
    assert clarification["destination"]["value_type"] == "string"
    assert clarification["candidate_columns"] == ["name", "phone", "age"]
    assert clarification["suggested_scopes"][0]["type"] == "ALL_MATCHING_COLUMNS"

    def unexpected_generate(_request):
        raise AssertionError("transform results must not be rewritten by an LLM")

    from core import composer as composer_module
    monkeypatch.setattr(composer_module.provider_engine, "generate", unexpected_generate)
    composed = ResponseComposer().compose(context, result)
    assert composed.answer == result.answer


def test_llm_null_destination_is_recovered_from_quoted_request_before_scope_clarification(monkeypatch):
    from datasets import registry as registry_module
    from engines.transform import TransformEngine
    from transformation.store import transformation_store

    dataset_id, chat_id = "quoted-null-recovery-ds", "quoted-null-recovery-chat"
    df = pd.DataFrame({
        "name": pd.Series([0, "Alex", "Mina"], dtype=object),
        "phone": pd.Series([0, "555", "666"], dtype=object),
        "age": pd.Series([0.0, 0.0, 32.0]),
    })
    monkeypatch.setattr(
        registry_module.dataset_registry,
        "get",
        lambda did: SimpleNamespace(dataframe=df) if did == dataset_id else None,
    )
    monkeypatch.setattr(TransformEngine, "_persist_plan", lambda *args: None)

    # Reproduce the faulty interpreter payload from the screenshot: it parsed
    # the unquoted word `none` as NULL and supplied no TypedLiteral metadata.
    first_turn = ExecutionContext(
        message="replace 0 with 'none'", dataset_id=dataset_id, chat_id=chat_id
    )
    first_turn.intent = "transform"
    first_turn.llm_operation = {
        "type": "REPLACE_VALUES", "old_value": 0, "new_value": None,
    }
    clarification_result = TransformEngine().handle(first_turn)
    clarification = clarification_result.metadata["clarification"]
    assert clarification["destination"]["value_type"] == "string"
    assert clarification["destination"]["value"] == "none"

    # The structured all-matching action must use the literal retained in
    # pending state rather than the stale raw None value.
    second_turn = ExecutionContext(
        message="All matching columns", dataset_id=dataset_id, chat_id=chat_id
    )
    second_turn.workspace_action = {
        "type": "TRANSFORMATION_CLARIFICATION",
        "clarification_type": "COLUMN_SCOPE",
        "value": "ALL_MATCHING_COLUMNS",
    }
    routed = MasterRouter()._fast_path(second_turn)
    operation = routed["operation"]
    assert operation["_new_typed"]["value_type"] == "string"
    assert operation["new_value"] == "none"
    second_turn.intent, second_turn.llm_operation = "transform", operation
    plan_result = TransformEngine().handle(second_turn)
    plan = plan_result.metadata["transform_plan"]
    assert 'string("none")' in plan["operation_label"]
    assert plan["affected_cells_count"] == 4


@pytest.mark.parametrize(
    "reply, expected_columns, expected_scope, expected_cells",
    [
        ("phone column", ["phone"], "EXPLICIT_COLUMNS", 1),
        ("all columns", ["name", "phone", "age"], "ALL_MATCHING_COLUMNS", 4),
    ],
)
def test_free_text_scope_clarification_restores_canonical_typed_literals(
    monkeypatch, reply, expected_columns, expected_scope, expected_cells
):
    from datasets import registry as registry_module
    from engines.transform import TransformEngine
    from transformation.store import transformation_store

    dataset_id = f"free-text-scope-{expected_scope.lower()}"
    chat_id = f"free-text-chat-{expected_scope.lower()}"
    df = pd.DataFrame({
        "name": pd.Series([0, "Alex", "Mina"], dtype=object),
        "phone": pd.Series([0, "555", "666"], dtype=object),
        "age": pd.Series([0.0, 0.0, 32.0]),
    })
    entry = SimpleNamespace(dataframe=df.copy(), filename="scope-test.csv")
    monkeypatch.setattr(
        registry_module.dataset_registry, "get",
        lambda did: entry if did == dataset_id else None,
    )
    monkeypatch.setattr(TransformEngine, "_persist_plan", lambda *args: None)

    original = "replace 0 with 'none'"
    operation = _parse_transform_from_message(original)
    assert operation["new_value"] == "none"
    assert operation["_new_typed"]["value_type"] == "string"
    first_turn = ExecutionContext(
        message=original, dataset_id=dataset_id, chat_id=chat_id
    )
    first_turn.intent, first_turn.llm_operation = "transform", operation
    clarification = TransformEngine().handle(first_turn).metadata["clarification"]
    assert clarification["source"]["value_type"] == "integer"
    assert clarification["destination"]["value_type"] == "string"

    # Reproduce a pending payload whose untyped compatibility values have gone
    # stale. The dedicated PendingTransformationContext literals stay canonical.
    pending = transformation_store.pending_for(chat_id, dataset_id)
    pending.operation_payload.pop("_old_typed", None)
    pending.operation_payload.pop("_new_typed", None)
    pending.operation_payload["new_value"] = None
    transformation_store.update_pending(pending)

    follow_up = ExecutionContext(message=reply, dataset_id=dataset_id, chat_id=chat_id)
    routed = MasterRouter()._fast_path(follow_up)
    resolved = routed["operation"]
    assert resolved["_old_typed"]["value_type"] == "integer"
    assert resolved["old_value"] == 0
    assert resolved["_new_typed"]["value_type"] == "string"
    assert resolved["new_value"] == "none"
    assert resolved["columns"] == expected_columns
    assert resolved["scope"]["type"] == expected_scope

    follow_up.intent, follow_up.llm_operation = "transform", resolved
    plan_result = TransformEngine().handle(follow_up)
    plan_dict = plan_result.metadata["transform_plan"]
    assert 'string("none")' in plan_dict["operation_label"]
    assert plan_dict["affected_cells_count"] == expected_cells
    plan = transformation_store.get(plan_dict["plan_id"])
    assert plan.before_sample[0].after == "none"
    preview = transformation_executor._execute(df.copy(), plan)

    if expected_scope == "EXPLICIT_COLUMNS":
        assert preview.loc[0, "phone"] == "none"
        assert type(preview.loc[0, "phone"]) is str
    else:
        assert preview.loc[0, "name"] == "none"
        assert preview.loc[0, "phone"] == "none"
        assert preview.loc[:1, "age"].tolist() == ["none", "none"]
        assert all(type(value) is str for value in preview["age"].iloc[:2])

    applied = transformation_executor.apply(
        plan, entry.dataframe, dataset_id, db=None
    )
    assert applied.success and applied.changed_cells == expected_cells
    if expected_scope == "EXPLICIT_COLUMNS":
        assert entry.dataframe.loc[0, "phone"] == "none"
        assert type(entry.dataframe.loc[0, "phone"]) is str
    else:
        assert entry.dataframe.loc[0, "name"] == "none"
        assert entry.dataframe.loc[0, "phone"] == "none"
        assert entry.dataframe.loc[:1, "age"].tolist() == ["none", "none"]
    transformation_store.finish_plan_context(plan.plan_id, "APPLIED")


def _pending_replace_fixture(monkeypatch, dataset_id="pending-ds", chat_id="pending-chat"):
    from datasets import registry as registry_module
    from engines.transform import TransformEngine
    df = pd.DataFrame({
        "name": pd.Series([0, "Alex", "Mina"], dtype=object),
        "phone": pd.Series([0, "555", "666"], dtype=object),
        "age": pd.Series([0.0, 0.0, 32.0]),
    })
    monkeypatch.setattr(
        registry_module.dataset_registry, "get",
        lambda did: SimpleNamespace(dataframe=df) if did == dataset_id else None,
    )
    context = ExecutionContext(
        message="replace 0 with 'none'", dataset_id=dataset_id,
        session_id="turn-one", chat_id=chat_id,
    )
    context.intent = "transform"
    context.llm_operation = _parse_transform_from_message(context.message)
    result = TransformEngine().handle(context)
    assert result.metadata["clarification"]["status"] == "AWAITING_CLARIFICATION"
    return df, result


def test_pending_transform_all_columns_resolves_in_new_session_without_llm(monkeypatch):
    from engines.transform import TransformEngine
    from transformation.store import transformation_store
    monkeypatch.setattr(TransformEngine, "_persist_plan", lambda *args: None)
    df, first = _pending_replace_fixture(monkeypatch)
    assert "name, phone, age" in first.answer

    followup = ExecutionContext(
        message="i want to change all columns", dataset_id="pending-ds",
        session_id="turn-two", chat_id="pending-chat",
    )
    payload = MasterRouter()._fast_path(followup)
    assert payload and payload["intent"] == "TRANSFORM"
    operation = payload["operation"]
    assert operation["_old_typed"]["value_type"] == "integer"
    assert operation["_new_typed"]["value_type"] == "string"
    assert operation["_new_typed"]["value"] == "none"
    assert operation["scope"]["type"] == "ALL_MATCHING_COLUMNS"
    assert operation["columns"] == ["name", "phone", "age"]

    followup.intent = "transform"
    followup.llm_operation = operation
    result = TransformEngine().handle(followup)
    plan = result.metadata["transform_plan"]
    assert plan["affected_cells_count"] == 4
    assert plan["affected_columns"] == ["name", "phone", "age"]
    assert "Replace integer(0) with string(\"none\")" in plan["operation_label"]
    preview = transformation_executor._execute(df.copy(), transformation_planner.plan(
        df, operation, "pending-ds"
    ))
    assert preview["name"].tolist() == ["none", "Alex", "Mina"]
    assert preview["phone"].tolist() == ["none", "555", "666"]
    assert preview["age"].tolist() == ["none", "none", 32.0]
    active = transformation_store.pending_for("pending-chat", "pending-ds")
    assert active is not None and active.status == "READY_FOR_REVIEW"

    from transformation.history import transformation_history
    transformation_history.clear("pending-ds")
    version_before = transformation_history.get_version("pending-ds")
    apply_plan = transformation_planner.plan(df, operation, "pending-ds")
    applied = transformation_executor.apply(apply_plan, df.copy(), "pending-ds", db=None)
    assert applied.success and applied.changed_cells == 4
    assert transformation_history.get_version("pending-ds") == version_before + 1
    undo_entry = transformation_history.pop("pending-ds")
    assert undo_entry is not None
    pd.testing.assert_frame_equal(undo_entry.previous_df, df)
    assert transformation_history.get_version("pending-ds") == version_before + 2


def test_all_columns_correction_repairs_destination_and_preserves_scope(monkeypatch):
    from engines.transform import TransformEngine
    from datasets.semantics.typed_literal import parse_literal
    from transformation.store import transformation_store
    monkeypatch.setattr(TransformEngine, "_persist_plan", lambda *args: None)
    df, _ = _pending_replace_fixture(monkeypatch, "all-correct-ds", "all-correct-chat")
    router = MasterRouter()
    choose_all = ExecutionContext(
        message="all columns", dataset_id="all-correct-ds", chat_id="all-correct-chat"
    )
    first_op = router._fast_path(choose_all)["operation"]
    choose_all.intent, choose_all.llm_operation = "transform", first_op
    first_result = TransformEngine().handle(choose_all)
    first_plan = first_result.metadata["transform_plan"]
    assert first_plan["affected_cells_count"] == 4
    assert first_plan["affected_columns"] == ["name", "phone", "age"]

    active = transformation_store.pending_for("all-correct-chat", "all-correct-ds")
    assert active and active.status == "READY_FOR_REVIEW"
    # Recreate the erroneous all-columns plan reported by the user.
    active.operation_payload["new_value"] = None
    active.operation_payload["_new_typed"] = parse_literal("null").to_dict()
    active.destination_typed_literal = parse_literal("null").to_dict()
    transformation_store.update_pending(active)

    correction = ExecutionContext(
        message='I asked you to replace 0 with "none" in all columns.',
        dataset_id="all-correct-ds", session_id="correct-turn", chat_id="all-correct-chat",
    )
    route = router._fast_path(correction)
    assert route and route["intent"] == "TRANSFORM"
    corrected = route["operation"]
    assert corrected["_old_typed"]["value_type"] == "integer"
    assert corrected["_new_typed"]["value_type"] == "string"
    assert corrected["_new_typed"]["value"] == "none"
    assert corrected["scope"]["type"] == "ALL_MATCHING_COLUMNS"
    assert corrected["columns"] == ["name", "phone", "age"]
    assert corrected["_supersedes_plan_id"] == first_plan["plan_id"]

    correction.intent, correction.llm_operation = "transform", corrected
    corrected_result = TransformEngine().handle(correction)
    corrected_plan = corrected_result.metadata["transform_plan"]
    assert corrected_plan["plan_id"] != first_plan["plan_id"]
    assert corrected_plan["affected_cells_count"] == 4
    assert 'string("none")' in corrected_plan["operation_label"]
    preview = transformation_executor._execute(
        df.copy(), transformation_planner.plan(df, corrected, "all-correct-ds")
    )
    assert preview["name"].iloc[0] == "none"
    assert preview["phone"].iloc[0] == "none"
    assert preview["age"].iloc[0] == "none"
    from datasets import registry as registry_module
    entry = SimpleNamespace(dataframe=df.copy())
    monkeypatch.setattr(registry_module.dataset_registry, "get", lambda did: entry)
    corrected_plan_object = transformation_store.get(corrected_plan["plan_id"])
    applied = transformation_executor.apply(
        corrected_plan_object, entry.dataframe, "all-correct-ds", db=None
    )
    assert applied.success and applied.changed_cells == 4
    assert entry.dataframe["name"].iloc[0] == "none"
    assert entry.dataframe["phone"].iloc[0] == "none"
    assert entry.dataframe["age"].iloc[:2].tolist() == ["none", "none"]
    assert type(entry.dataframe["name"].iloc[0]) is str
    assert type(entry.dataframe["phone"].iloc[0]) is str
    assert type(entry.dataframe["age"].iloc[0]) is str
    transformation_store.finish_plan_context(corrected_plan["plan_id"], "APPLIED")
    from transformation.history import transformation_history
    undo_entry = transformation_history.pop("all-correct-ds")
    assert undo_entry is not None
    pd.testing.assert_frame_equal(undo_entry.previous_df, df)


def test_repeating_active_all_columns_request_does_not_create_duplicate_plan(monkeypatch):
    from engines.transform import TransformEngine
    from transformation.store import transformation_store
    monkeypatch.setattr(TransformEngine, "_persist_plan", lambda *args: None)
    _, _ = _pending_replace_fixture(monkeypatch, "dedupe-ds", "dedupe-chat")
    router = MasterRouter()
    choose_all = ExecutionContext(message="all columns", dataset_id="dedupe-ds", chat_id="dedupe-chat")
    choose_all.intent = "transform"
    choose_all.llm_operation = router._fast_path(choose_all)["operation"]
    plan_result = TransformEngine().handle(choose_all)
    plan_id = plan_result.metadata["transform_plan"]["plan_id"]

    repeated = ExecutionContext(
        message='I asked you to replace 0 with "none" in all columns.',
        dataset_id="dedupe-ds", chat_id="dedupe-chat",
    )
    result = router._fast_path(repeated)
    assert result["intent"] == "conversation"
    assert "already replaces integer(0) with string(\"none\")" in result["direct_answer"]
    assert transformation_store.get(plan_id) is not None


def test_review_correction_replans_destination_and_preserves_phone_scope(monkeypatch):
    from engines.transform import TransformEngine
    from transformation.store import transformation_store
    from datasets.semantics.typed_literal import parse_literal
    monkeypatch.setattr(TransformEngine, "_persist_plan", lambda *args: None)
    df, _ = _pending_replace_fixture(monkeypatch, "correct-ds", "correct-chat")
    router = MasterRouter()
    choose_phone = ExecutionContext(
        message="change the phone column", dataset_id="correct-ds",
        session_id="turn-two", chat_id="correct-chat",
    )
    selected = router._fast_path(choose_phone)["operation"]
    choose_phone.intent = "transform"
    choose_phone.llm_operation = selected
    first = TransformEngine().handle(choose_phone)
    first_plan = first.metadata["transform_plan"]
    assert 'string("none")' in first_plan["operation_label"]
    assert first_plan["affected_columns"] == ["phone"]

    # Model the reported bad intermediate plan while retaining the other
    # already-resolved slots in the structured conversation state.
    active = transformation_store.pending_for("correct-chat", "correct-ds")
    assert active and active.status == "READY_FOR_REVIEW"
    active.operation_payload["new_value"] = None
    active.operation_payload["_new_typed"] = parse_literal("null").to_dict()
    active.destination_typed_literal = parse_literal("null").to_dict()
    transformation_store.update_pending(active)

    correction = ExecutionContext(
        message='I asked to replace 0 with "none" why are you replacing to null?',
        dataset_id="correct-ds", session_id="turn-three", chat_id="correct-chat",
    )
    corrected_route = router._fast_path(correction)
    assert corrected_route and corrected_route["intent"] == "TRANSFORM"
    corrected_op = corrected_route["operation"]
    assert corrected_op["_old_typed"]["value_type"] == "integer"
    assert corrected_op["_old_typed"]["value"] == 0
    assert corrected_op["_new_typed"]["value_type"] == "string"
    assert corrected_op["_new_typed"]["value"] == "none"
    assert corrected_op["columns"] == ["phone"]
    assert corrected_op["scope"]["type"] == "EXPLICIT_COLUMNS"
    assert transformation_store.get(first_plan["plan_id"]) is None

    correction.intent = "transform"
    correction.llm_operation = corrected_op
    replanned = TransformEngine().handle(correction)
    second_plan = replanned.metadata["transform_plan"]
    assert second_plan["plan_id"] != first_plan["plan_id"]
    assert second_plan["affected_columns"] == ["phone"]
    assert 'string("none")' in second_plan["operation_label"]
    plan_object = transformation_store.get(second_plan["plan_id"])
    from datasets import registry as registry_module
    entry = SimpleNamespace(dataframe=df.copy())
    monkeypatch.setattr(registry_module.dataset_registry, "get", lambda did: entry)
    applied = transformation_executor.apply(
        plan_object, entry.dataframe, "correct-ds", db=None
    )
    assert applied.success and applied.changed_cells == 1
    assert entry.dataframe.loc[0, "phone"] == "none"
    assert type(entry.dataframe.loc[0, "phone"]) is str
    assert entry.dataframe.loc[0, "name"] == 0
    transformation_store.finish_plan_context(second_plan["plan_id"], "APPLIED")
    assert transformation_store.pending_for("correct-chat", "correct-ds") is None

    from transformation.history import transformation_history
    undo = transformation_history.pop("correct-ds")
    assert undo is not None
    pd.testing.assert_frame_equal(undo.previous_df, df)


def test_pending_scope_resolves_specific_and_semantic_columns(monkeypatch):
    _pending_replace_fixture(monkeypatch, "scope-ds", "scope-chat")
    router = MasterRouter()

    for message, expected_columns, expected_scope in (
        ("only age", ["age"], "EXPLICIT_COLUMNS"),
        ("name and phone", ["name", "phone"], "EXPLICIT_COLUMNS"),
    ):
        # Recreate the pending state for each answer.
        from transformation.store import transformation_store
        transformation_store.finish_pending("scope-chat", "scope-ds", "CANCELLED")
        _pending_replace_fixture(monkeypatch, "scope-ds", "scope-chat")
        ctx = ExecutionContext(message=message, dataset_id="scope-ds", chat_id="scope-chat")
        payload = router._fast_path(ctx)
        assert payload["operation"]["columns"] == expected_columns
        assert payload["operation"]["scope"]["type"] == expected_scope

    from transformation.store import transformation_store
    transformation_store.finish_pending("scope-chat", "scope-ds", "CANCELLED")
    _pending_replace_fixture(monkeypatch, "scope-ds", "scope-chat")
    ctx = ExecutionContext(message="all numeric columns", dataset_id="scope-ds", chat_id="scope-chat")
    payload = router._fast_path(ctx)
    assert payload["operation"]["columns"] == ["age"]
    assert payload["operation"]["scope"] == {
        "type": "SEMANTIC_COLUMN_SCOPE", "semantic_type": "NUMBER", "columns": ["age"]
    }


def test_structured_clarification_action_resolves_scope_without_reparsing_literals(monkeypatch):
    _pending_replace_fixture(monkeypatch, "action-ds", "action-chat")
    context = ExecutionContext(
        message="All matching columns", dataset_id="action-ds", chat_id="action-chat",
    )
    context.workspace_action = {
        "type": "TRANSFORMATION_CLARIFICATION",
        "clarification_type": "COLUMN_SCOPE",
        "value": "ALL_MATCHING_COLUMNS",
    }
    route = MasterRouter()._fast_path(context)
    operation = route["operation"]
    assert operation["_old_typed"]["value_type"] == "integer"
    assert operation["_new_typed"]["value_type"] == "string"
    assert operation["_new_typed"]["value"] == "none"
    assert operation["columns"] == ["name", "phone", "age"]
    assert operation["scope"]["type"] == "ALL_MATCHING_COLUMNS"


def test_correction_and_scope_can_be_resolved_together_and_unrelated_turn_preserves_pending(monkeypatch):
    _pending_replace_fixture(monkeypatch, "combo-ds", "combo-chat")
    router = MasterRouter()
    unrelated = ExecutionContext(message="what is the weather?", dataset_id="combo-ds", chat_id="combo-chat")
    assert router._fast_path(unrelated) is None

    correction = ExecutionContext(
        message='Actually I meant the string "0", and do it in all columns.',
        dataset_id="combo-ds", chat_id="combo-chat",
    )
    payload = router._fast_path(correction)
    operation = payload["operation"]
    assert operation["_old_typed"]["value_type"] == "string"
    assert operation["_old_typed"]["value"] == "0"
    assert operation["_new_typed"]["value"] == "none"
    assert operation["scope"]["type"] == "ALL_MATCHING_COLUMNS"


def test_pending_transform_invalidates_when_dataset_fingerprint_changes(monkeypatch):
    from datasets import registry as registry_module
    from transformation.store import transformation_store
    df, _ = _pending_replace_fixture(monkeypatch, "stale-ds", "stale-chat")
    changed = df.copy()
    changed.loc[0, "name"] = "changed"
    monkeypatch.setattr(
        registry_module.dataset_registry, "get",
        lambda did: SimpleNamespace(dataframe=changed),
    )
    ctx = ExecutionContext(message="all columns", dataset_id="stale-ds", chat_id="stale-chat")
    payload = MasterRouter()._fast_path(ctx)
    assert payload["intent"] == "conversation"
    assert transformation_store.pending_for("stale-chat", "stale-ds") is None


def test_pending_transformation_can_be_cancelled_without_reusing_it(monkeypatch):
    from transformation.store import transformation_store
    _pending_replace_fixture(monkeypatch, "cancel-ds", "cancel-chat")
    ctx = ExecutionContext(message="cancel that", dataset_id="cancel-ds", chat_id="cancel-chat")
    assert MasterRouter()._fast_path(ctx) is None
    assert transformation_store.pending_for("cancel-chat", "cancel-ds") is None


def test_yes_and_no_resolve_only_an_explicit_all_matching_confirmation(monkeypatch):
    from transformation.store import transformation_store
    _pending_replace_fixture(monkeypatch, "confirm-ds", "confirm-chat")
    pending = transformation_store.pending_for("confirm-chat", "confirm-ds")
    pending.clarification_type = "ALL_MATCHING_CONFIRMATION"
    pending.latest_question = "Should I apply this to all matching columns?"
    transformation_store.update_pending(pending)

    yes = ExecutionContext(message="yes", dataset_id="confirm-ds", chat_id="confirm-chat")
    yes_payload = MasterRouter()._fast_path(yes)
    assert yes_payload["operation"]["scope"]["type"] == "ALL_MATCHING_COLUMNS"

    no = ExecutionContext(message="no", dataset_id="confirm-ds", chat_id="confirm-chat")
    no_payload = MasterRouter()._fast_path(no)
    assert no_payload["intent"] == "conversation"
    pending = transformation_store.pending_for("confirm-chat", "confirm-ds")
    assert pending is not None and pending.clarification_type == "COLUMN_SCOPE"
    transformation_store.finish_pending("confirm-chat", "confirm-ds", "CANCELLED")


def test_fill_value_clarification_resolves_without_restarting_request(monkeypatch):
    from datasets import registry as registry_module
    from engines.transform import TransformEngine
    from transformation.store import transformation_store
    dataset_id, chat_id = "fill-ds", "fill-chat"
    df = pd.DataFrame({"score": [1.0, np.nan, 3.0]})
    monkeypatch.setattr(registry_module.dataset_registry, "get", lambda did: SimpleNamespace(dataframe=df))
    monkeypatch.setattr(TransformEngine, "_persist_plan", lambda *args: None)
    initial = ExecutionContext(message="fill missing values", dataset_id=dataset_id, chat_id=chat_id)
    initial.intent = "transform"
    initial.llm_operation = _parse_transform_from_message(initial.message)
    first = TransformEngine().handle(initial)
    assert first.metadata["clarification"]["missing_slots"] == ["fill_value"]

    answer = ExecutionContext(message="median", dataset_id=dataset_id, chat_id=chat_id)
    payload = MasterRouter()._fast_path(answer)
    assert payload["intent"] == "TRANSFORM"
    assert payload["operation"]["value"] == "median"
    answer.intent = "transform"
    answer.llm_operation = payload["operation"]
    result = TransformEngine().handle(answer)
    assert result.metadata["transform_plan"]["affected_cells_count"] == 1
    preview = transformation_executor._execute(df.copy(), transformation_planner.plan(
        df, payload["operation"], dataset_id
    ))
    assert preview["score"].tolist() == [1.0, 2.0, 3.0]
    active = transformation_store.pending_for(chat_id, dataset_id)
    assert active is not None and active.status == "READY_FOR_REVIEW"


def test_rename_column_selection_and_names_resolve_in_separate_turns(monkeypatch):
    from datasets import registry as registry_module
    from engines.transform import TransformEngine
    from transformation.store import transformation_store
    dataset_id, chat_id = "rename-ds", "rename-chat"
    df = pd.DataFrame({"name": ["Alex"], "phone": ["555"]})
    monkeypatch.setattr(registry_module.dataset_registry, "get", lambda did: SimpleNamespace(dataframe=df))
    monkeypatch.setattr(TransformEngine, "_persist_plan", lambda *args: None)
    initial = ExecutionContext(message="rename the columns", dataset_id=dataset_id, chat_id=chat_id)
    initial.intent = "transform"
    initial.llm_operation = _parse_transform_from_message(initial.message)
    first = TransformEngine().handle(initial)
    assert first.metadata["clarification"]["missing_slots"] == ["target_scope", "new_names"]

    select = ExecutionContext(message="name and phone", dataset_id=dataset_id, chat_id=chat_id)
    route = MasterRouter()._fast_path(select)
    assert route["operation"]["columns"] == ["name", "phone"]
    select.intent = "transform"
    select.llm_operation = route["operation"]
    second = TransformEngine().handle(select)
    assert second.metadata["clarification"]["missing_slots"] == ["new_names"]

    names = ExecutionContext(
        message="name to full_name and phone to contact_number",
        dataset_id=dataset_id, chat_id=chat_id,
    )
    route = MasterRouter()._fast_path(names)
    assert route["operation"]["renames"] == {
        "name": "full_name", "phone": "contact_number"
    }
    names.intent = "transform"
    names.llm_operation = route["operation"]
    plan_result = TransformEngine().handle(names)
    plan = transformation_planner.plan(df, route["operation"], dataset_id)
    renamed = transformation_executor._execute(df.copy(), plan)
    assert list(renamed.columns) == ["full_name", "contact_number"]
    assert plan_result.metadata["transform_plan"]["affected_columns"] == ["name", "phone"]
    active = transformation_store.pending_for(chat_id, dataset_id)
    assert active is not None and active.status == "READY_FOR_REVIEW"
