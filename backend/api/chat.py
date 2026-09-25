"""Chat API blueprint — RFC Architecture Evolution v1.2."""
import logging
from flask import Blueprint, request, jsonify

from core.pipeline import request_pipeline
from router.master_router import master_router
from router.engine_registry import engine_registry
from engines.conversation import conversation_engine
from engines.analysis import analysis_engine
from utils.response import success_response, error_response

logger = logging.getLogger(__name__)


def _try_persist_messages(chat_id, user_message, assistant_answer, evidence_dict, ctx):
    """
    Persist user + assistant messages to PostgreSQL.
    Wrapped in try/except — DB errors NEVER affect the /api/ask response.
    """
    from config import Config
    if not Config.DATABASE_URL or not chat_id:
        return
    try:
        from db.session import db_session
        from db.repositories.user_repository import user_repository
        from db.repositories.message_repository import message_repository
        from db.repositories.chat_repository import chat_repository

        email = (request.headers.get('X-User-Email') or '').strip().lower() or 'dev@plexis.local'

        with db_session() as db:
            user = user_repository.get_or_create_by_email(db, email)
            import uuid as _uuid
            chat_uuid = _uuid.UUID(str(chat_id))

            # Verify ownership
            chat = chat_repository.get_by_id(db, chat_uuid, user.id)
            if not chat:
                logger.debug('[DB] chat_id=%s not found for user=%s — skipping message persist', chat_id, email)
                return

            # Persist user message
            message_repository.append_message(
                db, chat_uuid, role='user', content=user_message,
                message_type='conversation',
                metadata_json={'intent': getattr(ctx, 'intent', None)},
            )

            # Persist assistant message
            message_repository.append_message(
                db, chat_uuid, role='assistant', content=assistant_answer,
                message_type='conversation',
                metadata_json={
                    'evidence': evidence_dict,
                    'source': getattr(ctx, 'source', None),
                    'dataset_id': getattr(ctx, 'dataset_id', None),
                },
            )

            # Update chat's last_message_at
            chat_repository.update_last_message(db, chat_uuid)

            logger.debug('[DB] Messages persisted for chat=%s', chat_id)
    except Exception as e:
        logger.warning('[DB] Message persistence failed (non-fatal): %s', e)


def _build_response_actions(intent: str) -> dict:
    """
    Determine which result actions are available based on the resolved intent.

    Returns:
        {retry: bool, explain: bool, locate: bool}
    """
    is_analytical = intent in (
        "analysis", "DATA_OPERATION", "data_operation",
        "dataset_analysis", "analytical",
    )
    return {
        "retry": True,          # Always available
        "explain": is_analytical,
        "locate": is_analytical,
    }


def _build_result_block(ctx) -> dict | None:
    """
    Build the structured result block for analytical responses.

    Reads from ctx.analytical_result if it was set by the analysis engine.
    Returns None for non-analytical responses.
    """
    analytical_result = getattr(ctx, "analytical_result", None)
    if analytical_result is None:
        return None

    try:
        value = getattr(analytical_result, "value", None)
        operation = getattr(analytical_result, "operation", None)
        column = getattr(analytical_result, "column", None)
        row_indices = getattr(analytical_result, "row_indices", []) or []
        matching_rows = getattr(analytical_result, "matching_rows", []) or []
        verified = getattr(analytical_result, "verified", False)

        # Determine result type
        if isinstance(value, (int, float)) and matching_rows:
            result_type = "scalar_with_rows"
        elif isinstance(value, list):
            result_type = "list"
        elif isinstance(value, dict):
            result_type = "grouped"
        else:
            result_type = "scalar"

        # Build cleaned rows (strip internal _row_number from display data)
        rows = []
        for i, row in enumerate(matching_rows[:10]):
            clean = {k: v for k, v in row.items() if not k.startswith("_")}
            # Attach source_row_number from _row_number if present
            source_row_number = row.get("_row_number")
            if source_row_number is None:
                df_idx = row_indices[i] if i < len(row_indices) else i
                source_row_number = int(df_idx) + 1
            clean["source_row_number"] = source_row_number
            rows.append(clean)

        return {
            "type": result_type,
            "value": value,
            "operation": operation,
            "column": column,
            "row_count": len(row_indices),
            "verified": verified,
            "rows": rows,
        }
    except Exception as e:
        logger.warning("[chat] _build_result_block failed: %s", e)
        return None


chat_bp = Blueprint('chat', __name__, url_prefix='/api')

# Register engines on module load
engine_registry.register(conversation_engine, ['conversation', 'title_generation', 'help_system'])
engine_registry.register(analysis_engine, ['analysis'])
# web_search intent currently has no engine — router falls back to conversation

@chat_bp.route('/ask', methods=['POST'])
def ask():
    """
    Main ask endpoint — the heart of Plexis.

    Request body (JSON):
      message          (str, required)
      dataset_id       (str, optional)
      session_id       (str, optional) — frontend conversation ID
      workspace_state  (dict, optional) — current DatasetWorkspace state snapshot
      workspace_action (dict, optional) — explicit workspace action (e.g. explain_row)

    Response:
      Standard success_response plus:
        evidence         (dict | null)   — EvidenceReference or EvidenceCollection if produced
        analysis_id      (str | null)    — UUID of the persisted AnalysisOperation
        response_actions (dict)          — {retry, explain, locate} availability flags
        result           (dict | null)   — structured analytical result block
    """
    data = request.get_json(silent=True) or {}
    message = data.get('message', '').strip() if isinstance(data.get('message'), str) else ''
    dataset_id = data.get('dataset_id', '') or ''
    chat_id = data.get('chat_id') or None
    session_id = data.get('session_id') or request.headers.get('X-Session-Id')
    workspace_state = data.get('workspace_state') or None
    workspace_action = data.get('workspace_action') or None

    if not message:
        err_dict, status = error_response(message="Message cannot be empty", status_code=400)
        return jsonify(err_dict), status

    try:
        # 1. Run request through the pipeline (now workspace-aware + chat-scoped L2 restore)
        ctx = request_pipeline.process(
            message=message,
            dataset_id=dataset_id if dataset_id else None,
            session_id=session_id,
            workspace_state=workspace_state,
            workspace_action=workspace_action,
            chat_id=chat_id,    # enables chat-scoped dataset restore on L1 cache miss
        )

        # 2. Route to the correct engine
        result = master_router.route(ctx)

        # 3. Compose final response using ResponseComposer
        from core.composer import response_composer
        final_result = response_composer.compose(ctx, result)

        # 4. Record in conversation memory
        request_pipeline.record_response(ctx, message, final_result.answer)

        # 5. Serialize evidence (EvidenceReference or EvidenceCollection → dict)
        evidence_dict = None
        if final_result.evidence is not None:
            try:
                evidence_dict = final_result.evidence.to_dict()
            except Exception as ev_err:
                logger.warning(f"Evidence serialization failed: {ev_err}")

        # 6. Build analysis metadata
        analysis_id = getattr(ctx, "analysis_id", None)
        intent = getattr(ctx, "intent", "conversation") or "conversation"
        response_actions = _build_response_actions(intent)
        result_block = _build_result_block(ctx)

        # 7. Build response
        response = success_response(
            answer=final_result.answer,
            source=final_result.source,
            provider=final_result.provider,
            dataset_info=final_result.dataset_info,
            chart_data=final_result.chart_data,
        )

        # Attach evidence to response (null if none produced)
        response['evidence'] = evidence_dict

        # Attach analytical result metadata
        response['analysis_id'] = analysis_id
        response['response_actions'] = response_actions
        response['result'] = result_block

        # Expose chat_id to frontend — may have been auto-created by the
        # analytics pipeline to satisfy FK constraints on analysis_sessions
        resolved_chat_id = getattr(ctx, 'chat_id', None) or chat_id
        response['chat_id'] = str(resolved_chat_id) if resolved_chat_id else None

        # Add pipeline trace metadata for debugging
        response['_debug'] = {
            'intent': ctx.intent,
            'confidence': ctx.confidence,
            'session_id': ctx.session_id,
            'pipeline_ms': round(ctx.total_pipeline_ms(), 2),
            'trace': ctx.trace_summary(),
            'capability': final_result.metadata.get('capability') if final_result.metadata else None,
            'workspace_summary': ctx.workspace_summary or None,
        }

        # Persist messages to DB (non-blocking — errors never break response)
        _try_persist_messages(chat_id, message, final_result.answer, evidence_dict, ctx)

        # Register chat_id in ConversationMemory for L2 DB fallback
        # This allows get_history() to reconstruct from PostgreSQL on server restart
        if chat_id and ctx.session_id:
            try:
                from memory.conversation import conversation_memory
                conversation_memory.register_chat_id(ctx.session_id, str(chat_id))
            except Exception:
                pass  # Non-critical


        return jsonify(response)

    except Exception as e:
        logger.error(f"Ask endpoint error: {e}", exc_info=True)
        err_dict, status = error_response(message=f"An error occurred: {str(e)}", status_code=500)
        return jsonify(err_dict), status
