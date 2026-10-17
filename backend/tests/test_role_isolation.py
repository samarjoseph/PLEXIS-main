"""
Role Isolation and Task Assignment Tests (Part 10.A).

Verifies:
- Router requests use Mistral first, then direct NVIDIA NIM fallback.
- Analysis requests use OpenRouter Gemma first, Nemotron model fallback, then Gemini.
- Transformation requests use Gemini only (NO cross-role fallback to Mistral/Nvidia).
- Conversation requests use OpenRouter Gemma, Nemotron, then Gemini.
- Router-only models cannot be selected for analysis or transformation.
- Every task resolves an explicit model and provider.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from providers.model_registry import model_registry, ModelMetadata
from providers.selector import model_selector
from config import Config


class TestRoleIsolation:
    """Verifies that model selection strictly adheres to the 4 authoritative roles."""

    def test_router_role_progression(self):
        """Router requests must select Mistral Small first, then NVIDIA NIM."""
        # 1. Primary selection
        primary = model_selector.select_by_model_fallback(
            task="classification",
            require_json=True,
            failed_model_ids=[],
        )
        assert primary is not None
        assert primary.provider == "mistral"
        assert primary.model_name == Config.ROUTER_MISTRAL_MODEL

        # 2. When Mistral fails, direct NVIDIA NIM is selected
        fallback = model_selector.select_by_model_fallback(
            task="classification",
            require_json=True,
            failed_model_ids=[primary.model_id],
        )
        assert fallback is not None
        assert fallback.provider == "nvidia"
        assert fallback.model_name == Config.ROUTER_NVIDIA_MODEL

        # 3. When both fail, no other models (e.g. Gemini, OpenRouter) are hijacked
        none_left = model_selector.select_by_model_fallback(
            task="classification",
            require_json=True,
            failed_model_ids=[primary.model_id, fallback.model_id],
        )
        assert none_left is None

    def test_analysis_role_progression(self):
        """Analysis requests: OpenRouter Gemma -> OpenRouter Nemotron -> Gemini."""
        # 1. Primary: OpenRouter Gemma
        primary = model_selector.select_by_model_fallback(
            task="planner",
            require_json=True,
            failed_model_ids=[],
        )
        assert primary is not None
        assert primary.provider == "openrouter"
        assert primary.model_name == Config.ANALYSIS_OPENROUTER_MODEL

        # 2. Model fallback: OpenRouter Nemotron
        model_fallback = model_selector.select_by_model_fallback(
            task="planner",
            require_json=True,
            failed_model_ids=[primary.model_id],
        )
        assert model_fallback is not None
        assert model_fallback.provider == "openrouter"
        assert model_fallback.model_name == Config.ANALYSIS_OPENROUTER_FALLBACK_MODEL

        # 3. Secondary provider: Google Gemini
        provider_fallback = model_selector.select_by_model_fallback(
            task="planner",
            require_json=True,
            failed_model_ids=[primary.model_id, model_fallback.model_id],
        )
        assert provider_fallback is not None
        assert provider_fallback.provider == "gemini"
        assert provider_fallback.model_name == Config.TRANSFORMATION_GEMINI_MODEL

        # 4. Router models (Mistral / Nvidia) are NOT used for analysis
        final = model_selector.select_by_model_fallback(
            task="planner",
            require_json=True,
            failed_model_ids=[primary.model_id, model_fallback.model_id, provider_fallback.model_id],
        )
        assert final is None

    def test_transformation_role_isolation(self):
        """Transformation planning: Dedicated to Gemini, NO cross-role fallback."""
        primary = model_selector.select_by_model_fallback(
            task="transformation_planning",
            require_json=True,
            failed_model_ids=[],
        )
        assert primary is not None
        assert primary.provider == "gemini"
        assert primary.model_name == Config.TRANSFORMATION_GEMINI_MODEL

        # When Gemini fails, Mistral, NVIDIA, and OpenRouter are NOT borrowed
        fallback = model_selector.select_by_model_fallback(
            task="transformation_planning",
            require_json=True,
            failed_model_ids=[primary.model_id],
        )
        assert fallback is None, "Transformation must not fall back to unrelated models!"

    def test_conversation_role_progression(self):
        """Conversation: OpenRouter Gemma -> OpenRouter Nemotron -> Gemini."""
        primary = model_selector.select_by_model_fallback(
            task="conversation",
            require_json=False,
            failed_model_ids=[],
        )
        assert primary is not None
        assert primary.provider == "openrouter"

        fallback1 = model_selector.select_by_model_fallback(
            task="conversation",
            require_json=False,
            failed_model_ids=[primary.model_id],
        )
        assert fallback1 is not None
        assert fallback1.provider == "openrouter"
        assert fallback1.model_name == Config.ANALYSIS_OPENROUTER_FALLBACK_MODEL

        fallback2 = model_selector.select_by_model_fallback(
            task="conversation",
            require_json=False,
            failed_model_ids=[primary.model_id, fallback1.model_id],
        )
        assert fallback2 is not None
        assert fallback2.provider == "gemini"

    def test_title_task_has_eligible_model(self):
        """Title generation must NOT fail or be unassigned."""
        title_model = model_selector.select_by_model_fallback(
            task="title",
            require_json=False,
            failed_model_ids=[],
        )
        assert title_model is not None
        assert title_model.provider in ("openrouter", "gemini")

    def test_all_registered_tasks_resolve(self):
        """Verify that every task used in the Plexis codebase has an eligible model."""
        known_tasks = [
            "classification",
            "router",
            "planner",
            "transformation_planning",
            "transformation",
            "interpreter",
            "insight_synthesizer",
            "explanation",
            "spreadsheet_interpret",
            "chat",
            "conversation",
            "presentation",
            "title",
        ]
        for task in known_tasks:
            model = model_selector.select_by_model_fallback(task=task, require_json=False, failed_model_ids=[])
            assert model is not None, f"Task '{task}' has no eligible models configured!"
