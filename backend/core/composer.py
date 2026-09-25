"""
Response Composer — Post-Processing Pipeline

The ResponseComposer handles results from engines that return raw analytical
facts and need an LLM to compose the final response.

WHEN IT RUNS:
Only when an EngineResult has should_compose=True. 
The Conversation Engine now handles its own generation (should_compose=False),
so the composer is primarily used by the Analysis Engine and other data engines.

WHAT IT DOES:
- Takes raw analytical facts from EngineResult.facts
- Builds a context-aware system prompt using the Conversation Engine architecture
- Generates a natural, intelligent, Plexis-flavored response to the facts

WHAT IT DOES NOT DO:
- Does not override the Conversation Engine's output
- Does not handle routing
- Does not handle planning
"""
import logging
from core.context import ExecutionContext
from engines.base import EngineResult
from providers import provider_engine
from conversation import build_system_prompt, build_context_block

logger = logging.getLogger(__name__)


class ResponseComposer:
    """
    Composes natural language responses for engines that return raw facts.
    """

    def compose(self, context: ExecutionContext, result: EngineResult) -> EngineResult:
        # Conversation Engine handles its own generation — skip if not needed
        if not getattr(result, 'should_compose', True):
            return result

        intent = getattr(context, 'intent', 'unknown')
        message = getattr(context, 'normalized_query', getattr(context, 'message', ''))
        conversation_history = getattr(context, 'conversation_history', [])
        dataset_filename = getattr(context, 'dataset_filename', None)
        facts = getattr(result, 'facts', None)
        evidence = getattr(result, 'evidence', None)
        workspace_summary = getattr(context, 'workspace_summary', '')
        narrative_hint = ''

        # Capability result may include a narrative_hint
        # (short prose produced by the capability — not the evidence object itself)
        if hasattr(result, '_capability_narrative_hint'):
            narrative_hint = result._capability_narrative_hint

        has_analytical_facts = bool(facts and set(facts.keys()) != {'type'} and set(facts.keys()) != {'error'})

        # Build system prompt — always include analyst voice since composer
        # is primarily used for analytical results
        system_prompt = build_system_prompt(
            intent=intent,
            has_dataset=bool(dataset_filename),
            has_analytical_facts=has_analytical_facts,
        )

        # Build context block with the full facts payload.
        # workspace_summary provides LLM with natural language workspace context.
        # evidence description (if present) is injected as an additional hint so the
        # LLM can reference what the system found deterministically.
        evidence_description = None
        if evidence and hasattr(evidence, 'description'):
            evidence_description = evidence.description
        elif evidence and hasattr(evidence, 'summary'):
            evidence_description = evidence.summary

        context_block = build_context_block(
            message=message,
            intent=intent,
            conversation_history=conversation_history,
            dataset_filename=dataset_filename,
            facts=facts,
            workspace_summary=workspace_summary or None,
            evidence_description=evidence_description,
        )

        # Generate the composed response.
        # Use near-zero temperature when analytical facts are present —
        # the LLM must read numbers from the FACTS block, not hallucinate them.
        # 0.7 is only appropriate for open-ended conversation, not data answers.
        from providers.domain.contracts import AIRequest
        compose_temperature = 0.1 if has_analytical_facts else 0.7
        response = provider_engine.generate(
            AIRequest(
                task='chat',
                messages=[{"role": "user", "content": context_block}],
                system_prompt=system_prompt,
                temperature=compose_temperature,
            )
        )

        if response.success:
            result.answer = response.text
            result.provider = response.provider
        else:
            logger.warning("ResponseComposer generation failed: %s", response.error)

            # ── Deterministic fallback when analysis succeeded but LLM failed ──
            # If the analytical result is verified, build a short factual answer
            # from the structured data rather than showing a blank/error response.
            # The verified result is NEVER discarded due to a composer failure.
            deterministic_answer = self._build_deterministic_answer(context)
            if deterministic_answer:
                result.answer = deterministic_answer
                result.composer_failed = True   # surfaced in response metadata
                logger.info("ResponseComposer: using deterministic fallback answer.")
            else:
                result.answer = "I computed the result but couldn't generate the full explanation right now."
                result.composer_failed = True

            result.error = response.error

        return result

    def _build_deterministic_answer(self, context: ExecutionContext) -> str:
        """
        Build a short factual answer from a verified AnalyticalResult without LLM.

        Used as a fallback when the response composer LLM fails.
        The analytical value is NEVER invented — it comes from the verified result only.
        """
        analytical_result = getattr(context, 'analytical_result', None)
        if not analytical_result:
            return ''

        verified = getattr(analytical_result, 'verified', False)
        value = getattr(analytical_result, 'value', None)
        operation = getattr(analytical_result, 'operation', None)
        column = getattr(analytical_result, 'column', None)

        if not verified or value is None:
            return ''

        op_labels = {
            'max': 'highest', 'min': 'lowest', 'mean': 'average',
            'median': 'median', 'sum': 'total', 'count': 'count',
            'std': 'standard deviation', 'mode': 'most frequent',
        }
        op_word = op_labels.get((operation or '').lower(), str(operation or 'result').lower())
        col_phrase = f" of {column}" if column else ""

        if isinstance(value, float) and value == int(value):
            value_str = str(int(value))
        else:
            value_str = str(value)

        return f"The {op_word}{col_phrase} is **{value_str}**."


response_composer = ResponseComposer()
