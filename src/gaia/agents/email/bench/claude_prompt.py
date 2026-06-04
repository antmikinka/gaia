# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Prompt builder for the Claude CLI email classification benchmark.

Builds the classification prompt from email metadata and body text.
"""

from __future__ import annotations

from typing import Any

BENCHMARK_PROMPT_TEMPLATE = """\
Classify this email into exactly one category. Respond with ONLY a JSON object.

CATEGORIES:
- URGENT: Time-sensitive, requires immediate action. Real deadline. Known important sender.
- ACTIONABLE: Requires response or action, but not time-critical.
- INFORMATIONAL: FYI only. Contains useful information but requires no action.
- LOW PRIORITY: Promotional, automated, or low-value. Safe to archive.

PHISHING DETECTION (requires 2+ independent signals):
- Credential phishing: "verify account", "suspended", "click link to confirm" + unknown sender
- Financial threat: "wire transfer", "payment urgent", "account compromised" + unknown sender
- Prize/lottery: "you won", "claim prize", "lottery winner" + request for personal info
- Domain mismatch: Urgent/financial language + sender domain doesn't match claimed organization

KEY RULES:
- "URGENT" from unknown promotional sender = LOW PRIORITY (manufactured urgency)
- Phishing requires 2+ signals, never 1
- CC'd user defaults to INFORMATIONAL unless body explicitly asks them
- Never draft reply to phishing

Respond with ONLY this JSON (no markdown, no explanation):
{{
  "category": "URGENT|ACTIONABLE|INFORMATIONAL|LOW PRIORITY",
  "is_spam": true|false,
  "is_phishing": true|false,
  "confidence": "high|medium|low",
  "reason": "One sentence classification rationale",
  "suggested_action": "archive|reply|forward|delete|investigate"
}}

Email:
From: {sender}
Subject: {subject}
Date: {date}
To: {to}
CC: {cc}
Body:
{body}"""


def build_classification_prompt(email: dict[str, Any]) -> str:
    """Build the benchmark classification prompt for a single email.

    Args:
        email: Dict with keys: sender, subject, date, to, cc, body.
               Keys default to empty string if missing.

    Returns:
        The formatted prompt string ready to pass to ``claude --bare -p``.
    """
    return BENCHMARK_PROMPT_TEMPLATE.format(
        sender=email.get("sender", ""),
        subject=email.get("subject", ""),
        date=email.get("date", ""),
        to=email.get("to", ""),
        cc=email.get("cc", ""),
        body=email.get("body", email.get("snippet", "")),
    )
