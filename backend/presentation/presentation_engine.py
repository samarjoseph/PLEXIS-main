"""
Presentation Layer — Presentation Engine (v2.1)

Primary LLM call: executive facts only (~700 tokens, not 2500+).

The LLM receives ONLY the top-25 ExecutiveFacts from the ranker.
It never sees raw DKO JSON, column profiles, or full statistics.

v2.1 changes:
  - Full PRESENTATION_* structured telemetry (Phase 2 audit fix)
  - presentation_source header injected as first SSE chunk
    (value: "__SOURCE:llm__" or "__SOURCE:deterministic_fallback__")
  - Fallback is now always observable — never silently treated as LLM success
  - Model/provider identity logged on every call
"""

from __future__ import annotations

import logging
import time
from typing import Generator, List

from .domain.contracts import ExecutiveFact, ExecutiveSummary, KnowledgeModule

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Versioning — increment when prompt changes meaningfully
# ---------------------------------------------------------------------------
PRESENTATION_VERSION = "2.1"
PROMPT_MAX_TOKENS = 700      # Hard budget for facts section of the prompt
RESPONSE_MAX_TOKENS = 1024   # Max LLM output tokens

# ---------------------------------------------------------------------------
# Source sentinel — injected as the very first chunk so the upstream
# SSE handler can strip it out and record presentation_source.
# ---------------------------------------------------------------------------
SOURCE_LLM         = "__SOURCE:llm__"
SOURCE_FALLBACK    = "__SOURCE:deterministic_fallback__"

# ---------------------------------------------------------------------------
# System Prompt (§13 LLM boundary enforced here)
# ---------------------------------------------------------------------------

EXECUTIVE_SYSTEM_PROMPT = """You are Plexis — an AI data analyst who has already explored this dataset before meeting the user.

Your task: write a warm, analytical dataset introduction using ONLY the prioritized facts provided.

CRITICAL RULES:
1. NEVER narrate raw numbers in prose (mean: 41.4 belongs in a table, not your text)
2. NEVER list column names exhaustively — reference patterns and groups instead
3. NEVER use template headings like "Data Quality Summary" or "Key Findings"
4. NEVER repeat what the structured cards already show — interpret what they cannot
5. ALWAYS end with ONE specific, intriguing observation that invites further exploration

WHAT YOU SHOULD DO:
- Connect facts into a coherent storyline with narrative arc
- Interpret patterns (e.g., "the revenue concentration suggests a power-law customer distribution")
- Adapt tone to the detected domain (retail=customers/products, HR=people/teams, finance=margins/risk)
- Use the "I've already been through this" perspective — the expert who has pre-explored the data
- Use markdown sparingly: **bold** for emphasis, natural paragraph flow, end with one specific hook

LENGTH: 150–300 words. Dense insight, not length.

FORMAT: Pure markdown prose. No bullet lists. No tables. No headings. Just analytical narrative."""

# ---------------------------------------------------------------------------
# PresentationEngine
# ---------------------------------------------------------------------------

class PresentationEngine:
    """
    Stage 11 (v2.1) — Executive-first streaming LLM narrative with full telemetry.

    Receives ExecutiveFacts (top-25) from the ranker.
    Sends ~700 tokens to the LLM (vs 2500+ in v1.0).
    Streams Markdown chunks directly to the SSE endpoint.

    First yielded chunk is always a SOURCE sentinel so callers can distinguish
    LLM responses from deterministic fallback without inspecting content.
    """

    def stream(self, summary: ExecutiveSummary) -> Generator[str, None, None]:
        """
        Stream the executive narrative.

        Args:
            summary: ExecutiveSummary from SemanticImportanceRanker.

        Yields:
            First chunk: SOURCE sentinel (__SOURCE:llm__ or __SOURCE:deterministic_fallback__)
            Remaining: Plain string Markdown chunks from LLM or fallback.
        """
        identity = summary.executive_module.data.get("dataset_identity", {})
        dataset_name = identity.get("name", "unknown")
        t0 = time.monotonic()

        logger.info(
            "[PRESENTATION_REQUEST_STARTED] dataset=%s facts=%d version=%s",
            dataset_name, len(summary.facts), PRESENTATION_VERSION,
        )

        try:
            prompt = self._build_prompt(summary.facts, summary.executive_module)
            logger.info(
                "[PRESENTATION_PROMPT_BUILT] dataset=%s estimated_tokens=%d facts_in_prompt=%d",
                dataset_name, len(prompt) // 4, len(summary.facts),
            )
            yield from self._call_llm(prompt, summary, dataset_name, t0)
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.error(
                "[PRESENTATION_ERROR] dataset=%s elapsed=%.2fs error=%s",
                dataset_name, elapsed, e, exc_info=True,
            )
            yield from self._fallback_stream(summary, dataset_name, t0)

    def _build_prompt(
        self, facts: List[ExecutiveFact], executive_module: KnowledgeModule
    ) -> str:
        """
        Build the executive prompt from scored facts.
        Hard token budget enforced: if estimated tokens > PROMPT_MAX_TOKENS,
        trim facts until budget satisfied (min 10 facts always kept).
        """
        identity = executive_module.data.get("dataset_identity", {})

        header = (
            f"Dataset: {identity.get('name', 'Unknown')}\n"
            f"Domain: {identity.get('domain', 'General')} "
            f"(confidence: {identity.get('domain_confidence', 0):.0%})\n"
            f"Scale: {identity.get('rows', 0):,} rows × {identity.get('columns', 0)} columns\n"
            f"Readiness: {identity.get('readiness', 'unknown')} ({identity.get('readiness_score', 0):.0f}/100)\n\n"
            f"PRIORITIZED INTELLIGENCE (top facts, pre-ranked by importance):\n"
        )

        # Build fact lines, enforce budget
        fact_lines = []
        for i, fact in enumerate(facts):
            anomaly_marker = " ⚠️" if fact.is_anomalous else ""
            line = (
                f"{i+1}. [{fact.category.upper()}] {fact.title}: "
                f"{fact.value}{' ' + fact.unit if fact.unit else ''}{anomaly_marker}\n"
                f"   → {fact.context}"
            )
            fact_lines.append(line)

        # Estimate token count (chars / 4 approximation)
        while len(fact_lines) > 10:
            full_facts_text = "\n".join(fact_lines)
            estimated_tokens = len(header + full_facts_text) // 4
            if estimated_tokens <= PROMPT_MAX_TOKENS:
                break
            fact_lines.pop()  # Remove lowest-scored fact (last in list)

        facts_text = "\n".join(fact_lines)
        instruction = (
            "\n\nWrite the dataset introduction now. "
            "Do not reference this list directly — synthesize it into your narrative. "
            "Do not include any preamble or meta-commentary."
        )

        return header + facts_text + instruction

    def _call_llm(
        self, prompt: str, summary: ExecutiveSummary,
        dataset_name: str, t0: float,
    ) -> Generator[str, None, None]:
        """Call the provider engine and stream chunks with full telemetry."""
        from providers import provider_engine
        from providers.domain.contracts import AIRequest
        from providers.selector import model_selector

        # Log which model will be selected BEFORE calling
        try:
            selected = model_selector.select_fallback(
                task="presentation", require_json=False, failed_providers=[]
            )
            if selected:
                logger.info(
                    "[PRESENTATION_MODEL_SELECTED] dataset=%s provider=%s model=%s",
                    dataset_name, selected.provider, selected.model_name,
                )
            else:
                logger.warning(
                    "[PRESENTATION_MODEL_SELECTED] dataset=%s NO_MODEL_FOUND "
                    "task=presentation — will fall back",
                    dataset_name,
                )
                yield from self._fallback_stream(summary, dataset_name, t0)
                return
        except Exception as sel_err:
            logger.warning(
                "[PRESENTATION_MODEL_SELECTED] dataset=%s selector_error=%s",
                dataset_name, sel_err,
            )
            # Continue anyway — provider_engine has its own fallback

        logger.info(
            "[PRESENTATION_STREAM_STARTED] dataset=%s prompt_tokens=~%d",
            dataset_name, len(prompt) // 4,
        )

        # SOURCE sentinel emitted AFTER first successful chunk — not before.
        # Selection != successful generation. The sentinel is proof of actual output.
        yielded_chunks = 0
        source_sentinel_emitted = False
        t_first_chunk = None
        try:
            for chunk in provider_engine.generate_stream(
                AIRequest(
                    task="presentation",
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=EXECUTIVE_SYSTEM_PROMPT,
                    temperature=0.65,
                    max_tokens=RESPONSE_MAX_TOKENS,
                )
            ):
                if chunk:
                    if t_first_chunk is None:
                        t_first_chunk = time.monotonic()
                        logger.info(
                            "[PRESENTATION_FIRST_CHUNK] dataset=%s ttfb=%.2fs",
                            dataset_name, t_first_chunk - t0,
                        )
                        # NOW we can confirm the source — generation is real
                        yield SOURCE_LLM
                        source_sentinel_emitted = True
                        logger.info(
                            "[PRESENTATION_SOURCE] dataset=%s source=llm",
                            dataset_name,
                        )
                    yielded_chunks += 1
                    yield chunk
        except Exception as stream_err:
            elapsed = time.monotonic() - t0
            logger.error(
                "[PRESENTATION_ERROR] dataset=%s stream_error=%s elapsed=%.2fs chunks_before_error=%d",
                dataset_name, stream_err, elapsed, yielded_chunks,
            )
            if yielded_chunks == 0:
                # Zero chunks received — fall back entirely (no SOURCE_LLM emitted yet)
                yield from self._fallback_stream(summary, dataset_name, t0)
            return

        elapsed = time.monotonic() - t0

        if yielded_chunks == 0:
            logger.warning(
                "[PRESENTATION_STREAM_EMPTY] dataset=%s elapsed=%.2fs — LLM yielded nothing",
                dataset_name, elapsed,
            )
            # No chunks at all — fall back (no SOURCE_LLM sentinel was emitted)
            yield from self._fallback_stream(summary, dataset_name, t0)
        else:
            logger.info(
                "[PRESENTATION_STREAM_COMPLETED] dataset=%s chunks=%d elapsed=%.2fs",
                dataset_name, yielded_chunks, elapsed,
            )

    def _fallback_stream(
        self, summary: ExecutiveSummary, dataset_name: str = "unknown", t0: float = 0.0
    ) -> Generator[str, None, None]:
        """Deterministic fallback when LLM is unavailable. Always observable via SOURCE sentinel."""
        elapsed = time.monotonic() - t0
        logger.warning(
            "[PRESENTATION_FALLBACK_USED] dataset=%s elapsed=%.2fs reason=llm_unavailable",
            dataset_name, elapsed,
        )
        yield SOURCE_FALLBACK
        yield from self._fallback_content(summary, dataset_name, t0, already_emitted_source=True)

    def _fallback_content(
        self, summary: ExecutiveSummary, dataset_name: str, t0: float,
        already_emitted_source: bool = False,
    ) -> Generator[str, None, None]:
        """Shared deterministic content for fallback cases."""
        identity = summary.executive_module.data.get("dataset_identity", {})
        top_facts = summary.facts[:5]

        lines = [
            f"**{identity.get('name', 'Dataset')}** — {identity.get('domain', 'General Purpose')} dataset",
            f"",
            f"{identity.get('rows', 0):,} rows · {identity.get('columns', 0)} columns · "
            f"Quality: {identity.get('readiness_score', 0):.0f}/100 ({identity.get('readiness', 'unknown')})",
            f"",
            "**Key findings:**",
        ]
        for fact in top_facts:
            marker = "⚠️ " if fact.is_anomalous else "• "
            lines.append(f"{marker}{fact.context}")

        yield "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
presentation_engine = PresentationEngine()
