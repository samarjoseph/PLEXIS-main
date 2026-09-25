"""
MasterRouter — 80/20 LLM-first semantic intent dispatcher.

ARCHITECTURE:
  80% LLM semantic interpretation (primary authority)
  20% deterministic supporting signals (schema, workspace, column types)

FLOW:
  1. Fast-path check (greetings, title gen, explicit commands — no LLM)
  2. SemanticContextBuilder → builds context package (20% layer)
  3. LLM Interpreter → receives full context → returns typed JSON (80% layer)
  4. SchemaValidator → validates operation against dataset schema
  5. Intent + context → AnalysisEngine / ConversationEngine

WHAT CHANGED FROM v1:
  - Removed keyword-based primary classification (ANALYSIS_KEYWORDS, HELP_PATTERNS)
  - Removed heuristic-first / LLM-as-fallback pattern
  - LLM is now the primary semantic decision maker
  - Dataset schema is always passed to the LLM when a dataset is loaded
  - Added dataset-aware operation injection into context
  - Added schema validation before execution

WHAT STAYS THE SAME:
  - AnalysisEngine + CapabilityRegistry (untouched)
  - ConversationEngine (untouched)
  - provider_engine / model routing (untouched)
  - EngineResult contract (untouched)
  - Evidence contracts (untouched)
"""
import json
import logging
import re

from core.context import ExecutionContext
from core.events import (
    event_bus, IntentClassifiedEvent, EngineSelectedEvent, EngineCompletedEvent
)
from engines.base import EngineResult
from router.engine_registry import engine_registry
from router.semantic_context import semantic_context_builder
from router.schema_validator import schema_validator
from providers.engine import provider_engine

logger = logging.getLogger(__name__)

# ── Fast-path patterns — never need LLM classification ───────────────────────
# IMPORTANT: Must use word boundary \b AND end-of-string anchor to prevent
# "highest", "hello world dataset" etc. from matching as greetings.
# Only exact short greetings should match (e.g. "hi", "hey", "good morning").
_GREETING_RX = re.compile(
    r'^(hi|hello|hey|greetings|good\s+(morning|afternoon|evening)|'
    r'how are you|howdy|thanks|thank you|thx|bye|goodbye)\b[!.,\s]*$',
    re.IGNORECASE,
)
_TITLE_RX = re.compile(
    r'generate.*(?:title|heading)|(?:concise|short).*title|'
    r'title.*(?:conversation|chat)|create.*title',
    re.IGNORECASE,
)

# Intents the AnalysisEngine can handle
_ANALYSIS_INTENTS = {"analysis", "DATA_OPERATION"}


class MasterRouter:
    """
    Routes requests to the correct engine using LLM-primary semantic interpretation.

    The LLM makes the final semantic decision.
    Keyword/heuristic signals are supporting evidence only — they are NOT the decision.
    """

    def route(self, context: ExecutionContext) -> EngineResult:
        """Classify intent and dispatch to the correct engine."""

        stage = context.start_stage('intent_classification')

        # ── Step 1: Fast-path (no LLM needed) ────────────────────────────────
        payload = self._fast_path(context)

        if payload is None:
            # ── Step 2: Build semantic supporting context (20% layer) ─────────
            semantic_ctx = semantic_context_builder.build(context)

            # ── Step 3: LLM interpretation (80% layer — primary authority) ────
            payload = self._llm_interpret(context, semantic_ctx)

            # ── Step 4: Schema validation (structural check only) ─────────────
            payload = self._validate_and_enrich(payload, context, semantic_ctx)

        # ── Step 5: Apply intent + route ──────────────────────────────────────
        # Map LLM intent schema to engine intent names
        raw_intent = payload.get("intent", "conversation")
        intent = self._map_intent(raw_intent)
        confidence = float(payload.get("confidence", 0.8))

        context.route_payload = payload
        context.intent = intent
        context.confidence = confidence
        context.complete_stage(stage)

        event_bus.publish(IntentClassifiedEvent(
            request_id=context.request_id,
            intent=intent,
            confidence=confidence,
        ))

        logger.info(
            f"[Router] intent={intent} confidence={confidence:.2f} "
            f"query='{context.message[:80]}'"
        )

        # Inject structured operation into context when available
        operation = payload.get("operation")
        if operation and intent == "analysis":
            context.llm_operation = operation  # Available to AnalysisEngine
            logger.info(
                f"[Router] operation={operation.get('type')} "
                f"column={operation.get('column') or operation.get('columns', [])}"
            )

        # Attach interpretation reason for observability
        context.interpretation_reason = payload.get("reason", "")

        # ── Step 6: Engine dispatch ───────────────────────────────────────────
        stage = context.start_stage('engine_dispatch')
        engine = engine_registry.get_engine_for_intent(intent)

        if not engine:
            logger.warning(f"No engine for intent '{intent}', falling back to conversation")
            engine = engine_registry.get_engine('conversation')

        if not engine:
            context.complete_stage(stage, success=False, error='No engine available')
            return EngineResult(
                answer="I'm sorry, I'm not able to process that request right now.",
                source='system',
                provider='system',
                success=False,
                error='No engine available',
            )

        event_bus.publish(EngineSelectedEvent(
            request_id=context.request_id,
            engine_type=engine.engine_name,
            confidence=confidence,
        ))
        context.complete_stage(stage)

        # ── Step 7: Engine execution ──────────────────────────────────────────
        stage = context.start_stage(f'engine_{engine.engine_name}')
        try:
            result = engine.handle(context)
            context.complete_stage(stage, success=result.success)
            event_bus.publish(EngineCompletedEvent(
                request_id=context.request_id,
                duration_ms=stage.duration_ms or 0.0,
            ))
            return result
        except Exception as e:
            logger.error(f"Engine '{engine.engine_name}' error: {e}", exc_info=True)
            context.complete_stage(stage, success=False, error=str(e))
            return EngineResult(
                answer="An unexpected error occurred while processing your request.",
                source='system',
                provider='system',
                success=False,
                error=str(e),
            )

    # ── Fast-path ─────────────────────────────────────────────────────────────

    def _fast_path(self, context: ExecutionContext) -> dict | None:
        """
        Check if this request can be classified without an LLM call.

        Only handles structurally deterministic cases:
          - Greetings and farewells
          - Title generation requests
          - Explicit workspace actions (explain_evidence handled by ConversationEngine)

        Returns a payload dict if fast-path matched, None otherwise.
        All other queries go through the LLM interpreter.
        """
        message = getattr(context, 'normalized_query', '') or context.message.lower()

        # Title generation — exact pattern match
        if _TITLE_RX.search(message):
            logger.debug("[Router] fast-path: title_generation")
            return {"intent": "title_generation", "confidence": 0.99, "operation": None, "reason": "title generation pattern"}

        # Greeting — obvious conversational
        # Only fire for very short messages that are clearly greetings
        if _GREETING_RX.match(message.strip()) and len(message.split()) <= 5:
            logger.debug("[Router] fast-path: greeting → conversation")
            return {"intent": "conversation", "confidence": 0.98, "operation": None, "reason": "greeting pattern"}

        return None  # Everything else goes through LLM

    # ── LLM interpretation ────────────────────────────────────────────────────

    def _llm_interpret(self, context: ExecutionContext, semantic_ctx: dict) -> dict:
        """
        Call the LLM to interpret the user's query.

        This is the 80% layer — the LLM makes the final semantic decision.
        The LLM receives:
          - The user query (normalized)
          - Full dataset schema with column names, types, sample values
          - Schema-compatible capabilities (structural, not keyword-matched)
          - Workspace context (recent ops, selection)

        Returns a typed payload dict {intent, operation, confidence, reason}.
        Falls back to conversation intent on LLM failure.
        """
        from prompts.interpreter import build_interpreter_prompt
        from providers.domain.contracts import AIRequest

        query = getattr(context, 'normalized_query', '') or context.message
        prompt = build_interpreter_prompt(query=query, semantic_context=semantic_ctx)

        # Log what we're sending (no data, just metadata)
        dataset_loaded = semantic_ctx.get("dataset_loaded", False)
        col_count = len(semantic_ctx.get("columns", []))
        ref_cols = semantic_ctx.get("referenced_columns", [])
        logger.info(
            f"[Router/LLM] interpret: dataset_loaded={dataset_loaded} "
            f"columns={col_count} referenced={ref_cols}"
        )

        try:
            response = provider_engine.generate(
                AIRequest(
                    task='classification',
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=(
                        "You are a semantic intent classifier. "
                        "Return ONLY a valid JSON object. No prose, no markdown."
                    ),
                    temperature=0.05,  # Near-zero for deterministic classification
                    max_tokens=256,    # Small output — just structured JSON
                )
            )

            if not response.success:
                logger.warning(
                    f"[Router/LLM] provider failed: {response.error}. "
                    f"Falling back to {'analysis' if dataset_loaded else 'conversation'}."
                )
                # Smart fallback: if dataset loaded and query has any analytical signal,
                # prefer analysis over conversation.
                fallback_intent = "conversation"
                if dataset_loaded and ref_cols:
                    fallback_intent = "analysis"
                return {
                    "intent": fallback_intent,
                    "operation": None,
                    "confidence": 0.5,
                    "reason": f"LLM unavailable ({response.error}); using schema-based fallback",
                }

            payload = self._parse_llm_json(response.text or "")
            logger.info(
                f"[Router/LLM] result: intent={payload.get('intent')} "
                f"confidence={payload.get('confidence')} "
                f"operation={payload.get('operation')} "
                f"reason={payload.get('reason', '')[:80]}"
            )
            return payload

        except Exception as e:
            logger.error(f"[Router/LLM] interpretation exception: {e}", exc_info=True)
            # Hard fallback — don't crash the request
            fallback = "analysis" if (dataset_loaded and ref_cols) else "conversation"
            return {
                "intent": fallback,
                "operation": None,
                "confidence": 0.4,
                "reason": f"Exception during LLM interpret: {str(e)[:60]}",
            }

    def _parse_llm_json(self, text: str) -> dict:
        """Parse and normalise the LLM's JSON response."""
        text = text.strip()
        # Strip markdown code fences if present
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'```\s*$', '', text, flags=re.MULTILINE)
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try extracting outermost JSON object
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except Exception:
                    pass

        logger.warning(f"[Router/LLM] Could not parse JSON from: {text[:200]}")
        return {"intent": "conversation", "operation": None, "confidence": 0.3, "reason": "parse_error"}

    # ── Schema validation + enrichment ────────────────────────────────────────

    def _validate_and_enrich(
        self, payload: dict, context: ExecutionContext, semantic_ctx: dict
    ) -> dict:
        """
        Validate the LLM's structured operation against the actual schema.

        On validation failure:
          - intent is set to 'conversation'
          - A typed error reason is attached
          - The operation is cleared

        On minor corrections (e.g. default order):
          - The corrected operation is used

        Does NOT re-run the LLM or guess missing values.
        """
        intent = payload.get("intent", "CONVERSATION")
        if intent != "DATA_OPERATION":
            return payload  # Nothing to validate for non-data intents

        columns = semantic_ctx.get("columns", [])
        operation = payload.get("operation")

        result = schema_validator.validate(
            interpretation={"intent": intent, "operation": operation},
            columns=columns,
        )

        if result.valid:
            # Apply minor corrections if any
            if result.corrected_operation:
                payload = {**payload, "operation": result.corrected_operation}
            logger.debug(f"[Router/Validator] operation valid: {operation}")
            return payload

        # Validation failed
        logger.info(
            f"[Router/Validator] validation failed: "
            f"code={result.error_code} msg={result.error_message}"
        )
        # Attach error to context for engine to surface
        context.interpretation_error = {
            "code": result.error_code,
            "message": result.error_message,
        }
        # Route to conversation with the error reason
        return {
            **payload,
            "intent": "conversation",
            "operation": None,
            "confidence": 0.9,
            "reason": f"Validation failed: {result.error_message}",
            "validation_error": result.error_message,
        }

    # ── Intent mapping ────────────────────────────────────────────────────────

    def _map_intent(self, llm_intent: str) -> str:
        """
        Map LLM intent schema names to engine intent names.

        LLM returns:  DATA_OPERATION | CONVERSATION | EXPLANATION | TITLE
        Engine uses:  analysis | conversation | help_system | title_generation
        """
        mapping = {
            "DATA_OPERATION": "analysis",
            "CONVERSATION":   "conversation",
            "EXPLANATION":    "conversation",   # ConversationEngine handles this
            "TITLE":          "title_generation",
            # Legacy intents (from old classifier) — keep compatibility
            "analysis":       "analysis",
            "conversation":   "conversation",
            "help_system":    "conversation",   # help_system → conversation
            "title_generation": "title_generation",
            "web_search":     "web_search",
        }
        return mapping.get(llm_intent, "conversation")


master_router = MasterRouter()
