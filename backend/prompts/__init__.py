"""
Prompts Package

Exposes all dynamic prompt builders for the Plexis architecture.
Each module handles exactly one responsibility.

Note: build_conversation_prompt is intentionally NOT imported here at module level
to avoid a circular import with the conversation package. Import it directly from
prompts.conversation when needed.
"""

from .formatter import get_formatting_rules
from .router import build_router_prompt
from .query_normalizer import build_normalizer_prompt
from .planner import build_planner_prompt
from .analysis import build_analysis_prompt
from .report import build_report_prompt
from .title_generator import build_title_prompt
from .web_search import build_web_search_prompt
from .dataset_profiler import build_dataset_profiler_prompt
# 80/20 semantic interpreter prompt
from .interpreter import build_interpreter_prompt

__all__ = [
    'get_formatting_rules',
    'build_router_prompt',
    'build_normalizer_prompt',
    'build_planner_prompt',
    'build_analysis_prompt',
    'build_report_prompt',
    'build_title_prompt',
    'build_web_search_prompt',
    'build_dataset_profiler_prompt',
    'build_interpreter_prompt',
]
