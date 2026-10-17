"""
InvestigateEngine — handles INVESTIGATE intent.

Tells the frontend to open the Investigation workspace, 
and optionally provides a grounded chat summary of the findings.
"""
from __future__ import annotations
import logging
from typing import Optional
from engines.base import BaseEngine, EngineResult
from core.context import ExecutionContext
from providers.engine import provider_engine
from providers.domain.contracts import AIRequest
from autonomous_analysis.investigation_cache import investigation_cache

logger = logging.getLogger(__name__)

INVESTIGATE_SYSTEM_PROMPT = """You are Plexis, analyzing the user's CURRENT DATASET.
You are NOT answering a generic question about datasets.
Your task is to summarize the verified data findings provided below.

RULES:
1. ONLY use the verified findings provided in the context.
2. If there are no verified findings, state clearly that no anomalies were detected in the current dataset.
3. Do NOT hallucinate columns, values, salaries, examples, or general data advice.
4. Keep the summary concise (1-3 sentences).
5. State the facts confidently based on the verified evidence.
"""

class InvestigateEngine(BaseEngine):

    @property
    def engine_name(self) -> str:
        return 'investigate'

    def can_handle(self, context: ExecutionContext) -> bool:
        return getattr(context, 'intent', None) in ('investigate', 'INVESTIGATE')

    def _get_fingerprint(self, dataset_id: str) -> Optional[str]:
        try:
            from datasets.registry import dataset_registry
            entry = dataset_registry.get_by_id(dataset_id)
            if entry and getattr(entry, "dko", None):
                return entry.dko.fingerprint
            if entry and hasattr(entry, "fingerprint"):
                return entry.fingerprint
        except Exception:
            pass
        return dataset_id

    def handle(self, context: ExecutionContext) -> EngineResult:
        dataset_id = str(getattr(context, 'dataset_id', '') or '')
        if not dataset_id:
            return EngineResult(
                answer="No dataset is currently loaded. Upload a dataset to investigate.",
                source='investigate',
                provider='system',
                success=True,
                metadata={'trigger_investigation': False},
            )

        fingerprint = self._get_fingerprint(dataset_id)
        report = investigation_cache.get_report(fingerprint) if fingerprint else None

        evidence_text = "No verified findings available for this dataset."
        if report:
            findings = []
            if report.get('synthesis_text'):
                findings.append(report['synthesis_text'])
            for group in report.get('section_groups', []):
                for sec in group.get('sections', []):
                    if sec.get('interpretation'):
                        findings.append(sec['interpretation'])
            
            if findings:
                evidence_text = "\n".join(findings)

        # Build grounded response
        user_msg = f"User asked about dataset anomalies.\nVERIFIED FINDINGS:\n{evidence_text}"

        response = provider_engine.generate(
            AIRequest(
                task="chat",
                messages=[{"role": "user", "content": user_msg}],
                system_prompt=INVESTIGATE_SYSTEM_PROMPT,
                temperature=0.2
            )
        )
        
        answer = "Opening the Investigation workspace for your dataset."
        if response.success and response.text:
            answer = response.text

        return EngineResult(
            answer=answer,
            source='investigate',
            provider=response.provider if response.success else 'system',
            success=True,
            should_compose=False,
            metadata={'trigger_investigation': True, 'dataset_id': dataset_id},
        )

investigate_engine = InvestigateEngine()
