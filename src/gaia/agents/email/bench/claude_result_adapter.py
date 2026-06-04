# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Result adapter for the Claude CLI email classification benchmark.

Parses raw Claude CLI JSON responses and adapts them into GAIA
EmailResult / BatchResult / RunResult dataclass shapes.
"""

from __future__ import annotations

import json
import re
from typing import Any

from gaia.agents.email.bench.data_shapes import EmailResult


def _extract_json_block(text: str) -> str:
    """Extract the JSON object from Claude CLI output.

    Strips markdown code fences (```json ... ```) if present and returns
    the raw JSON string. Handles trailing text after the JSON block.
    """
    text = text.strip()
    # Try to find a ```json ... ``` block first.
    match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: try to find the outermost JSON object.
    brace_count = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if brace_count == 0:
                start = i
            brace_count += 1
        elif ch == "}":
            brace_count -= 1
            if brace_count == 0 and start >= 0:
                return text[start : i + 1]
    # Last resort: return the whole thing and let json.loads fail.
    return text


def parse_claude_response(
    result_text: str,
    usage: dict[str, Any],
    cost: float,
    duration_ms: int,
    email_id: str,
    subject: str,
    sender: str,
) -> EmailResult:
    """Parse a Claude CLI classification response into an EmailResult.

    Args:
        result_text: Raw stdout from the Claude CLI invocation.
        usage: Usage dict from Claude CLI JSON output (may contain
               cache_creation_input_tokens, cache_read_input_tokens,
               input_tokens, output_tokens).
        cost: Estimated cost in USD for this invocation.
        duration_ms: Wall-clock duration in milliseconds.
        email_id: The email identifier.
        subject: The email subject line.
        sender: The email sender address.

    Returns:
        An EmailResult populated from the parsed response.
    """
    # Extract JSON from the response.
    json_text = _extract_json_block(result_text)

    # Defaults for error case.
    category = ""
    is_spam = False
    is_phishing = False
    confident = False
    reason = ""
    status = "ok"
    error = ""

    try:
        parsed = json.loads(json_text)
        category = parsed.get("category", "")
        is_spam = bool(parsed.get("is_spam", False))
        is_phishing = bool(parsed.get("is_phishing", False))
        confidence = parsed.get("confidence", "low")
        confident = confidence == "high"
        reason = parsed.get("reason", "")
    except (json.JSONDecodeError, ValueError) as exc:
        status = "parse_error"
        error = f"Failed to parse JSON response: {exc}"

    # Map usage to GAIA token counts.
    # Claude API usage may have:
    #   input_tokens — base input tokens
    #   cache_creation_input_tokens — tokens written to cache (first pass)
    #   cache_read_input_tokens — tokens read from cache (subsequent passes)
    #   output_tokens — generated tokens
    input_tokens = (
        usage.get("cache_creation_input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("input_tokens", 0)
    )
    output_tokens = usage.get("output_tokens", 0)
    total_tokens = input_tokens + output_tokens

    tps = (output_tokens / max(duration_ms, 1)) * 1000 if output_tokens > 0 else 0.0

    return EmailResult(
        email_id=email_id,
        subject=subject,
        sender=sender,
        category=category,
        is_spam=is_spam,
        is_phishing=is_phishing,
        confident=confident,
        reason=reason,
        duration_ms=duration_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=0,
        total_tokens=total_tokens,
        time_to_first_token_ms=0.0,
        tokens_per_second=round(tps, 1),
        status=status,
        error=error,
    )
