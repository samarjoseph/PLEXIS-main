"""
Regression Test Suite: Plexis Assistant Identity Across All Providers

Validates:
1. Shared identity instruction across system prompts.
2. Proper system prompt serialization across all provider adapters (Nvidia, OpenRouter, Mistral, Groq, Gemini).
3. Provider failover preserves identity and provides active runtime model context.
4. Direct identity queries ('What is your name?', 'Aren't you Plexis?', 'Who developed you?', 'Which AI model powers this response?').
5. Dataset analysis queries preserve strict grounding and analytical facts.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from conversation.identity import PLEXIS_IDENTITY, PLEXIS_CORE_DIRECTIVE
from conversation.prompt_builder import build_system_prompt
from providers.domain.contracts import AIRequest
from providers.base import ProviderResponse
from providers.nvidia import NvidiaProvider
from providers.openrouter import OpenRouterProvider
from providers.mistral import MistralProvider
from providers.groq import GroqProvider
from providers.gemini import GeminiProvider
from providers.fallback import FallbackEngine


# ==============================================================================
# 1. System Prompt & Identity Contract Tests
# ==============================================================================

def test_shared_identity_directive_content():
    """Verify the exact required identity directive is embedded in PLEXIS_IDENTITY."""
    expected_fragment = (
        "You are Plexis, the AI data-analysis assistant inside the Plexis application. "
        "Respond as Plexis. The underlying model and provider are implementation details, "
        "not your product identity. If asked who you are, identify yourself as Plexis, "
        "an AI assistant that helps users analyze and work with datasets. If asked which "
        "underlying model or provider powers a response, answer accurately when that "
        "information is available; otherwise state that you do not have reliable information. "
        "Never invent model details."
    )
    assert expected_fragment in PLEXIS_CORE_DIRECTIVE
    assert expected_fragment in PLEXIS_IDENTITY


def test_build_system_prompt_includes_identity():
    """Verify build_system_prompt always includes the shared identity instruction."""
    for intent in ["conversation", "analysis", "transform", "help_system"]:
        prompt = build_system_prompt(intent=intent, has_dataset=False)
        assert "You are Plexis, the AI data-analysis assistant inside the Plexis application" in prompt
        assert "Never invent model details" in prompt
        assert "Never adopt or claim the identity, name, or persona of any underlying AI provider" in prompt


# ==============================================================================
# 2. Provider Request Serialization Tests
# ==============================================================================

def test_nvidia_provider_preserves_system_prompt_with_messages():
    """Ensure NvidiaProvider prepends system_prompt when messages is populated."""
    provider = NvidiaProvider(api_key="test-key")
    request = AIRequest(
        task="chat",
        messages=[{"role": "user", "content": "Hello what is your name?"}],
        system_prompt="You are Plexis, the AI data-analysis assistant.",
    )

    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "I am Plexis!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_post.return_value = mock_resp

        resp = provider.generate(request)
        assert resp.success
        assert mock_post.called

        called_json = mock_post.call_args[1]["json"]
        sent_messages = called_json["messages"]
        assert len(sent_messages) == 2
        assert sent_messages[0]["role"] == "system"
        assert sent_messages[0]["content"] == "You are Plexis, the AI data-analysis assistant."
        assert sent_messages[1]["role"] == "user"
        assert sent_messages[1]["content"] == "Hello what is your name?"


def test_openrouter_provider_preserves_system_prompt_with_messages():
    """Ensure OpenRouterProvider prepends system_prompt when messages is populated."""
    provider = OpenRouterProvider(api_key="test-key")
    request = AIRequest(
        task="chat",
        messages=[{"role": "user", "content": "aren't you plexis?"}],
        system_prompt="You are Plexis, the AI data-analysis assistant.",
    )

    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Yes, I am Plexis!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_post.return_value = mock_resp

        resp = provider.generate(request)
        assert resp.success
        assert mock_post.called

        called_json = mock_post.call_args[1]["json"]
        sent_messages = called_json["messages"]
        assert len(sent_messages) == 2
        assert sent_messages[0]["role"] == "system"
        assert sent_messages[0]["content"] == "You are Plexis, the AI data-analysis assistant."
        assert sent_messages[1]["role"] == "user"


def test_mistral_provider_preserves_system_prompt_with_messages():
    """Ensure MistralProvider prepends system_prompt when messages is populated."""
    provider = MistralProvider(api_key="test-key")
    request = AIRequest(
        task="chat",
        messages=[{"role": "user", "content": "Who developed you?"}],
        system_prompt="You are Plexis, the AI data-analysis assistant.",
    )

    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "I am Plexis!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_post.return_value = mock_resp

        resp = provider.generate(request)
        assert resp.success
        assert mock_post.called

        called_json = mock_post.call_args[1]["json"]
        sent_messages = called_json["messages"]
        assert len(sent_messages) == 2
        assert sent_messages[0]["role"] == "system"
        assert sent_messages[0]["content"] == "You are Plexis, the AI data-analysis assistant."
        assert sent_messages[1]["role"] == "user"


def test_groq_provider_preserves_system_prompt_with_messages():
    """Ensure GroqProvider prepends system_prompt when messages is populated."""
    provider = GroqProvider(api_key="test-key")
    request = AIRequest(
        task="chat",
        messages=[{"role": "user", "content": "Which AI model powers this response?"}],
        system_prompt="You are Plexis, the AI data-analysis assistant.",
    )

    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "I am Plexis."}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_post.return_value = mock_resp

        resp = provider.generate(request)
        assert resp.success
        assert mock_post.called

        called_json = mock_post.call_args[1]["json"]
        sent_messages = called_json["messages"]
        assert len(sent_messages) == 2
        assert sent_messages[0]["role"] == "system"
        assert sent_messages[0]["content"] == "You are Plexis, the AI data-analysis assistant."


def test_gemini_provider_uses_system_instruction():
    """Ensure GeminiProvider passes system_prompt via GenerateContentConfig system_instruction."""
    provider = GeminiProvider(api_key="test-key")
    request = AIRequest(
        task="chat",
        messages=[{"role": "user", "content": "What is your name?"}],
        system_prompt="You are Plexis, the AI data-analysis assistant.",
    )

    with patch.object(provider, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = "I am Plexis!"
        mock_response.usage_metadata = None
        mock_client.models.generate_content.return_value = mock_response

        resp = provider.generate(request)
        assert resp.success
        assert resp.text == "I am Plexis!"

        # Check call arguments to generate_content
        call_kwargs = mock_client.models.generate_content.call_args[1]
        config = call_kwargs["config"]
        assert config.system_instruction == "You are Plexis, the AI data-analysis assistant."
        # Verify system prompt was NOT duplicated in contents
        assert "system:" not in call_kwargs["contents"]
        assert "user: What is your name?" in call_kwargs["contents"]


# ==============================================================================
# 3. Provider Failover Identity & Runtime Model Context Tests
# ==============================================================================

def test_fallback_engine_failover_preserves_active_model_context():
    """
    Test that when the primary provider fails, FallbackEngine switches to the
    next model/provider and updates the active runtime model context.
    """
    fallback = FallbackEngine()
    request = AIRequest(
        task="chat",
        messages=[{"role": "user", "content": "Which AI model powers this response?"}],
        system_prompt=build_system_prompt("conversation"),
    )

    # Provider 1: Fails with 429 Rate Limit
    mock_p1 = MagicMock()
    mock_p1.generate.return_value = ProviderResponse(
        text="",
        model="primary-model",
        provider="openrouter",
        success=False,
        error="HTTP 429: Too Many Requests",
        status_code=429,
    )

    # Provider 2: Succeeds
    mock_p2 = MagicMock()
    captured_requests = []

    def mock_p2_generate(req, **kwargs):
        captured_requests.append(req)
        return ProviderResponse(
            text="I am Plexis. This response is powered by gemini-2.0-flash via Gemini.",
            model="gemini-2.0-flash",
            provider="gemini",
            success=True,
            status_code=200,
        )

    mock_p2.generate.side_effect = mock_p2_generate

    with patch("providers.selector.model_selector.select_by_model_fallback") as mock_select, \
         patch("providers.registry.provider_registry.get") as mock_get_provider, \
         patch("providers.quarantine.quarantine_manager.is_eligible", return_value=True), \
         patch("providers.quarantine.quarantine_manager.acquire_probe_slot", return_value=True), \
         patch("providers.scheduler.credential_scheduler.select_and_reserve", return_value=None):

        meta1 = MagicMock(provider="openrouter", model_id="primary-model")
        meta2 = MagicMock(provider="gemini", model_id="gemini-2.0-flash")

        def select_model(task, require_json, failed_model_ids):
            if "primary-model" not in failed_model_ids:
                return meta1
            return meta2

        mock_select.side_effect = select_model

        mock_get_provider.side_effect = lambda p: mock_p1 if p == "openrouter" else mock_p2

        response = fallback.execute(request)

        assert response.success
        assert response.provider == "gemini"
        assert response.model == "gemini-2.0-flash"
        assert "Plexis" in response.text

        # Verify the fallback provider received the active model context tag
        assert len(captured_requests) == 1
        p2_request = captured_requests[0]
        assert "Active Runtime Model Context:" in p2_request.system_prompt
        assert "gemini-2.0-flash" in p2_request.system_prompt
        assert "gemini" in p2_request.system_prompt


# ==============================================================================
# 4. Direct Identity Queries and Capability Grounding Tests
# ==============================================================================

def test_conversation_engine_identity_handling():
    """Verify ConversationEngine._chat constructs system_prompt with Plexis identity."""
    from engines.conversation import conversation_engine
    from core.context import ExecutionContext

    ctx = ExecutionContext(
        message="hello whats your name?",
        session_id="test-session",
    )
    ctx.intent = "conversation"

    with patch("providers.engine.provider_engine.generate") as mock_generate:
        mock_generate.return_value = ProviderResponse(
            text="Hello! I'm Plexis, your AI data-analysis assistant. How can I help you today?",
            model="nvidia/nemotron-3.5-lightning:free",
            provider="openrouter",
            success=True,
        )

        result = conversation_engine.handle(ctx)
        assert result.success
        assert "Plexis" in result.answer
        assert result.provider == "openrouter"

        # Verify outgoing AIRequest passed to provider_engine
        called_req = mock_generate.call_args[0][0]
        assert "You are Plexis, the AI data-analysis assistant" in called_req.system_prompt
        assert "Never invent model details" in called_req.system_prompt


def test_conversation_engine_direct_confirmation_identity():
    """Verify handling of 'aren't you plexis?' query."""
    from engines.conversation import conversation_engine
    from core.context import ExecutionContext

    ctx = ExecutionContext(
        message="aren't you plexis?",
        session_id="test-session",
    )
    ctx.intent = "conversation"

    with patch("providers.engine.provider_engine.generate") as mock_generate:
        mock_generate.return_value = ProviderResponse(
            text="Yes, absolutely! I am Plexis, your AI assistant for dataset analysis and spreadsheet intelligence.",
            model="nvidia/nemotron-3.5-lightning:free",
            provider="openrouter",
            success=True,
        )

        result = conversation_engine.handle(ctx)
        assert result.success
        assert "Plexis" in result.answer
        assert "Nemotron" not in result.answer


def test_dataset_analysis_preserves_facts_grounding():
    """Verify that dataset analysis requests continue to ground strictly in computed facts."""
    from core.composer import response_composer
    from core.context import ExecutionContext
    from engines.base import EngineResult

    ctx = ExecutionContext(
        message="give me top 3 delayed airlines",
        session_id="test-session",
    )
    ctx.intent = "analysis"
    ctx.dataset_filename = "flights.csv"

    facts = {
        "operation": "group_max",
        "column": "Departure_Delay",
        "computed_answer": "Top 3 delayed airlines: 1. IndiGo (120 mins), 2. Air India (95 mins), 3. SpiceJet (80 mins)",
        "ranking": [
            {"entity": "IndiGo", "value": 120},
            {"entity": "Air India", "value": 95},
            {"entity": "SpiceJet", "value": 80},
        ],
    }

    engine_res = EngineResult(
        answer="",
        source="analysis",
        facts=facts,
        should_compose=True,
    )

    with patch("providers.engine.provider_engine.generate") as mock_generate:
        mock_generate.return_value = ProviderResponse(
            text="The top 3 most delayed airlines are IndiGo with 120 minutes, Air India with 95 minutes, and SpiceJet with 80 minutes.",
            model="google/gemini-2.0-flash",
            provider="gemini",
            success=True,
        )

        composed = response_composer.compose(ctx, engine_res)
        assert composed.success
        assert "IndiGo" in composed.answer
        assert "120" in composed.answer
        assert composed.provider == "gemini"
