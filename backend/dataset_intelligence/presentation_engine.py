"""
Dataset Intelligence Engine — Stage 11: Dataset Presentation Engine

This is the ONLY stage that calls the LLM.

The LLM never sees raw dataset rows.
It receives a compact, structured JSON summary of everything Python has already
determined deterministically through Stages 1–10.

PHILOSOPHY:
  The LLM acts as a Senior Data Analyst who has already spent time exploring
  the dataset before meeting the user for the first time.

  Its job is NOT to summarize everything it knows.
  Its job is to INTRODUCE the most valuable discoveries.

  The output should feel like:
    "I've already been through this — here's what immediately stood out."
  not:
    "Dataset ingested. 10,000 rows, 6 columns."

  Structure, headings, tone, length, and emphasis are decided by the LLM
  based on what is actually interesting in each specific dataset.
  No two uploads should feel identical.

OUTPUT:
  Free-form Markdown streamed directly to the upload SSE endpoint.
  Also cached as a complete string inside the DatasetPresentation object.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Generator

from .models import DatasetPresentation
from .models_v2 import DatasetKnowledgeObject
from .context_engine import presentation_context_builder

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Presentation Version — increment this when the prompt changes meaningfully.
# This allows cache invalidation when the prompt architecture evolves.
# ---------------------------------------------------------------------------
PRESENTATION_VERSION = "2.0"

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

PRESENTATION_SYSTEM_PROMPT = """You are Plexis — an exceptionally intelligent, warm, and approachable AI Information Designer and Senior Data Analyst.

You have already spent time deterministically profiling and exploring this dataset before meeting the user.
Your job is NOT to write a traditional long-form essay or report.
Your job is to **DESIGN INFORMATION** so a human understands the dataset within a few seconds.

THE DUAL-LAYER PHILOSOPHY:
You must combine two different communication styles seamlessly.
Layer 1 — Story: Explain what was discovered using warm, conversational observations. (e.g., "The first thing that caught my attention...", "An interesting pattern appears...")
Layer 2 — Evidence: Support observations with highly scannable, structured information (tables, bullet lists, metrics).

DYNAMIC INFORMATION DESIGN:
You dynamically decide the layout based on the specific dataset.
- Do NOT use a universal template.
- Avoid walls of text. Optimize for scannability (10–15 seconds to read).
- Use **tables** when they improve communication (e.g., comparing metrics, summarizing data quality, categorizing dimensions).
- Use **bullet lists** for key findings or capabilities.
- Use **paragraphs** only for storytelling and context.
- Never force a table if a bulleted list or prose works better.

PRESERVE COMPLETE INTELLIGENCE:
The Python intelligence engine has discovered valuable facts (mean, missing values, duplicates, KPIs, relationships, semantics).
- You must intelligently surface the most relevant facts.
- Do not compress profiler outputs into generic prose — surface the numbers, metrics, and identifiers.

WHAT TO AVOID:
- Do NOT begin with generic statements like "The dataset contains X rows..."
- Do NOT use fixed, rigid headings like "Dataset Summary", "Key Findings", or "Insights".
- Do NOT output a single block of prose.
- Do NOT end with generic closings like "What would you like to analyze?"

LANGUAGE ADAPTATION:
Adapt your language and structure to the detected domain:
- Retail/Sales → customers, products, revenue, sales patterns
- HR → employees, departments, attrition
- Finance → profit, cost, margins, cash flow
- Healthcare → patients, diagnoses, outcomes
- Education → students, grades, attendance
- Sports → teams, players, performance metrics

ENDING:
End naturally by pointing toward a specific, intriguing opportunity or an unusual observation the data raises that naturally invites the next conversation.

Write entirely in Markdown. The response should feel handcrafted, analytical, highly scannable, and warm.
"""

# ---------------------------------------------------------------------------
# DatasetPresentationEngine
# ---------------------------------------------------------------------------

class DatasetPresentationEngine:
    """
    Stage 11 — Dataset Presentation Engine

    Transforms the DatasetKnowledgeObject (produced by Stages 1-10) into
    a natural-language Markdown introduction that streams directly to the user.

    Two interfaces:
      present(dko)         -> Returns a complete DatasetPresentation (blocking).
                             Used when a cached DKO needs to regenerate its text.

      present_stream(dko)  -> Yields Markdown text chunks as they arrive from the
                             LLM. Used by the upload SSE endpoint.
    """

    def present(self, dko: DatasetKnowledgeObject) -> DatasetPresentation:
        """
        Generate the full presentation synchronously.
        Accumulates all streamed chunks into a single DatasetPresentation object.
        Used for caching and non-streaming contexts.
        """
        try:
            chunks = list(self.present_stream(dko))
            full_text = "".join(chunks)
            model_used = self._detect_model_used()
            return DatasetPresentation(
                presentation=full_text,
                version=PRESENTATION_VERSION,
                model_used=model_used,
                generated_at=datetime.now(timezone.utc).isoformat(),
                generated_by="llm" if full_text else "fallback",
            )
        except Exception as e:
            logger.error(f"DatasetPresentationEngine.present() failed: {e}")
            return self._build_fallback_presentation(dko)

    def present_stream(self, dko: DatasetKnowledgeObject) -> Generator[str, None, None]:
        """
        Stream the dataset presentation as Markdown text chunks.

        Yields plain string chunks from the LLM as they arrive.
        The SSE endpoint wraps each chunk in the typed event envelope.

        On any failure, falls back to yielding a deterministic Markdown
        presentation built from the DKO fields — no blank screen, no crash.
        """
        try:
            summary_json = presentation_context_builder.build_context(dko)
            prompt = (
                f"Generate a dataset introduction for the following structured intelligence:\n\n"
                f"{summary_json}\n\n"
                f"Write the introduction now. Do not include any preamble."
            )

            from providers import provider_engine
            
            logger.info("=" * 60)
            logger.info("PRESENTATION ENGINE INPUT")
            logger.info("=" * 60)
            logger.info(prompt)
            logger.info("=" * 60)
            
            yielded_anything = False
            from providers.domain.contracts import AIRequest
            for chunk in provider_engine.generate_stream(
                AIRequest(
                    task="presentation",
                    messages=[{"role": "user", "content": prompt}],
                    system_prompt=PRESENTATION_SYSTEM_PROMPT,
                    temperature=0.65,
                    max_tokens=1024,
                )
            ):
                if chunk:
                    yielded_anything = True
                    yield chunk

            if not yielded_anything:
                logger.warning("DatasetPresentationEngine: LLM yielded nothing, using fallback")
                yield from self._fallback_stream(dko)

        except Exception as e:
            logger.error(f"DatasetPresentationEngine.present_stream() failed: {e}")
            yield from self._fallback_stream(dko)

    # -------------------------------------------------------------------------
    # Fallback — deterministic Markdown when the LLM is unavailable
    # -------------------------------------------------------------------------

    def _fallback_stream(self, dko: DatasetKnowledgeObject) -> Generator[str, None, None]:
        """Yield a deterministic fallback Markdown presentation without LLM."""
        yield self._build_fallback_presentation(dko).presentation

    def _build_fallback_presentation(self, dko: DatasetKnowledgeObject) -> DatasetPresentation:
        """Build a minimal but meaningful presentation from DKO fields alone."""
        identity = dko.get_dataset_identity()
        domain = identity.probable_purpose
        quality_score = round(dko.quality_report.overall_score) if dko.quality_report else 0
        readiness = identity.overall_readiness
        metrics = [m.name for m in dko.get_primary_metrics()[:4]]
        dimensions = [d.name for d in dko.get_grouping_dimensions()[:4]]

        quality_line = (
            f"Data quality is **{quality_score}/100** ({readiness}) — "
            f"this dataset is well-prepared for analysis."
            if quality_score >= 75
            else f"Data quality score is **{quality_score}/100** — "
                 f"there are some issues worth reviewing before analysis."
        )

        metrics_line = (
            f"I can see **{len(metrics)} measurable column(s)**: "
            f"{', '.join(f'`{m}`' for m in metrics)}."
            if metrics else ""
        )
        dimensions_line = (
            f"The dataset can be broken down by **{len(dimensions)} dimension(s)**: "
            f"{', '.join(f'`{d}`' for d in dimensions)}."
            if dimensions else ""
        )

        opportunities = [o.name for o in dko.get_analysis_opportunities()[:5]]
        cap_line = (
            f"Plexis can perform **{len(dko.get_analysis_opportunities())}** types of "
            f"analysis on this dataset, including {', '.join(opportunities)}."
            if opportunities else ""
        )

        lines = [
            f"This looks like a **{domain}** dataset. Here's my first impression:",
            "",
            quality_line,
        ]
        if metrics_line:
            lines.append(metrics_line)
        if dimensions_line:
            lines.append(dimensions_line)
        if cap_line:
            lines.append("")
            lines.append(cap_line)

        text = "\n".join(lines)
        return DatasetPresentation(
            presentation=text,
            version=PRESENTATION_VERSION,
            model_used="fallback",
            generated_at=datetime.now(timezone.utc).isoformat(),
            generated_by="fallback",
        )

    def _detect_model_used(self) -> str:
        """Best-effort detection of which model generated the presentation."""
        try:
            from providers.selector import model_selector
            meta = model_selector.select_fallback("presentation", require_json=False, failed_providers=[])
            return meta.model_name if meta else "unknown"
        except Exception:
            return "unknown"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
presentation_engine = DatasetPresentationEngine()
