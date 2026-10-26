"""
Plexis Text Sanitizer — Strict Elimination of Chain-of-Thought and Prompt Leakage

Guarantees that NO internal reasoning, thinking process markers, system prompt leakage,
or agent execution traces ever reach user-facing outputs across any engine.
"""
from __future__ import annotations
import re
import logging

logger = logging.getLogger(__name__)

# Fenced or tagged reasoning blocks
_TAGGED_REASONING_PATTERNS = [
    re.compile(r'<think>.*?</think>', re.DOTALL | re.IGNORECASE),
    re.compile(r'<thought>.*?</thought>', re.DOTALL | re.IGNORECASE),
    re.compile(r'<reasoning>.*?</reasoning>', re.DOTALL | re.IGNORECASE),
    re.compile(r'<analysis>.*?</analysis>', re.DOTALL | re.IGNORECASE),
    re.compile(r'<scratchpad>.*?</scratchpad>', re.DOTALL | re.IGNORECASE),
    re.compile(r'\[THINKING\].*?\[/THINKING\]', re.DOTALL | re.IGNORECASE),
    re.compile(r'\[REASONING\].*?\[/REASONING\]', re.DOTALL | re.IGNORECASE),
]

# Prefixes that signal natural-language chain-of-thought
_COT_HEADER_PATTERN = re.compile(
    r"^(?:(?:Here(?:'s| is) (?:a |the |my )?(?:thinking|thought) process:?)"
    r"|(?:Thinking Process:?)"
    r"|(?:Thought Process:?)"
    r"|(?:Internal Reasoning:?)"
    r"|(?:Let's analyze the (?:user|request|input):?)"
    r"|(?:1\.\s+\*\*Analyze User Input:\*\*))",
    re.IGNORECASE | re.MULTILINE
)

# System prompt leakage markers
_SYSTEM_LEAK_LINES = re.compile(
    r"^(?:.*(?:CURRENT INTENT:|DATASET LOADED:|SYSTEM NOTE:|The system note says|According to the system instructions|The system prompt states).*)$",
    re.IGNORECASE | re.MULTILINE
)


def strip_thinking_and_internal_reasoning(text: str) -> str:
    """
    Remove any chain-of-thought, reasoning steps, or prompt leakage from model output.
    Returns clean user-facing prose.
    """
    if not text or not isinstance(text, str):
        return ""

    cleaned = text

    # 1. Strip explicit tagged blocks
    for pat in _TAGGED_REASONING_PATTERNS:
        cleaned = pat.sub('', cleaned)

    # 1b. Strip unclosed opening thinking tags if present
    cleaned = re.sub(r'<(?:think|thought|reasoning|analysis|scratchpad)>.*$', '', cleaned, flags=re.DOTALL | re.IGNORECASE)

    # 2. Check for natural language thinking process headers (e.g. "Here's a thinking process:...")
    m = _COT_HEADER_PATTERN.search(cleaned)
    if m:
        logger.warning("[Sanitizer] Detected natural-language chain-of-thought header. Stripping internal reasoning.")
        # If the text begins with a thinking process, find where the actual answer starts
        # Common transition markers in LLM thinking outputs:
        # - Direct response after thinking section
        # - Markdown horizontal rule (---)
        # - "Final Answer:" or "Response:" or "Conclusion:"
        # - An answer paragraph not discussing "user input" or "system note"
        sub_text = cleaned[m.start():]
        
        # Look for explicit response headers
        resp_match = re.search(
            r'(?:(?:\n---|---\n|\n\*\*\*\n)'
            r'|\n(?:Final Answer|Response|Direct Response|Conclusion):\s*'
            r'|\n\n(?!(?:[0-9]+\.|\*|-)\s+)(?=[A-Z]))',
            sub_text
        )
        if resp_match:
            candidate = sub_text[resp_match.end():].strip()
            # If the candidate doesn't mention internal prompt tokens, use it
            if candidate and not re.search(r'\b(?:system note|intent|user input)\b', candidate, re.IGNORECASE):
                cleaned = candidate
            else:
                # If still contaminated, filter out contaminated paragraphs
                paras = [p.strip() for p in sub_text.split('\n\n') if p.strip()]
                clean_paras = []
                for p in paras:
                    if not re.search(r'\b(?:thinking process|analyze user input|system note|intent:|dataset loaded:)\b', p, re.IGNORECASE):
                        clean_paras.append(p)
                cleaned = '\n\n'.join(clean_paras)
        else:
            # Split into paragraphs and remove chain-of-thought blocks
            paras = [p.strip() for p in cleaned.split('\n\n') if p.strip()]
            clean_paras = []
            for p in paras:
                if not re.search(r'\b(?:thinking process|analyze user input|system note|intent:|dataset loaded:)\b', p, re.IGNORECASE):
                    clean_paras.append(p)
            cleaned = '\n\n'.join(clean_paras)

    # 3. Strip individual prompt leakage lines
    cleaned = _SYSTEM_LEAK_LINES.sub('', cleaned)

    # 4. Clean up excessive whitespace/newlines
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()

    # 5. Unicode character cleanup (consistent with conversation engine)
    cleaned = (
        cleaned
        .replace('\u2011', '-')
        .replace('\u2013', '-')
        .replace('\u2014', '-')
        .replace('\u202f', ' ')
        .replace('\u00a0', ' ')
    )

    return cleaned
