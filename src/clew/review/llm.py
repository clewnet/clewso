import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from .context import ReviewContext

logger = logging.getLogger("clew.review.llm")


@dataclass
class ReviewResult:
    risk_level: str  # HIGH, MEDIUM, LOW, SAFE, UNKNOWN
    explanation: str
    affected_files: list[str]
    recommendation: str
    confidence: float = 0.0


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4-turbo-preview")

        if not self.api_key:
            logger.warning("OPENAI_API_KEY not found. LLM features will fail.")
        elif not self.api_key.startswith("sk-"):
            logger.error("Invalid OpenAI API key format. Should start with 'sk-'.")

    async def chat_completion(self, messages: list[dict[str, str]], json_mode: bool = True) -> dict[str, Any]:
        """Send chat completion request with retries."""
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
        }

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(3):
                try:
                    response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                    response.raise_for_status()
                    return response.json()
                except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as e:
                    logger.warning(f"LLM request failed (attempt {attempt + 1}/3): {e}")
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1 * (attempt + 1))
        return {}


def _build_system_prompt() -> str:
    return """You are a code review assistant specializing in architectural impact analysis.

Your task: Analyze whether a code change introduces breaking changes to downstream files.

RULES:
1. HIGH Risk: Definite breaking change (ImportError, missing symbol, deleted file used by others)
2. MEDIUM Risk: Likely breaking change (signature mismatch, type change, semantic shift)
3. LOW Risk: Possible issue (style change, deprecation warning, minor refactor)
4. SAFE: No breaking changes detected (new methods, internal changes, comments)

Only flag HIGH/MEDIUM if you have specific evidence from the context.
If unsure, use LOW or SAFE with explanation.

Output format (JSON):
{
  "risk_level": "HIGH" | "MEDIUM" | "LOW" | "SAFE",
  "explanation": "Specific reasoning based on code",
  "affected_files": ["path/to/file.py"],
  "recommendation": "Specific action to take",
  "confidence": 0.0 to 1.0
}
"""


def _build_user_prompt(diff: str, context: ReviewContext, changed_file: str) -> str:
    prompt = f"""# Changed File
File: {changed_file}

# Diff
{diff}

# Downstream Files Affected
The following files import or depend on this file:
"""

    if context.truncated:
        prompt += (
            f"Focus on the {len(context.files)} affected files "
            f"(of {context.files[0].score if context.files else 'many'}).\n"
        )

    for f in context.files:
        prompt += f"\n## File: {f.path}\n{f.content}\n"

    prompt += """
# Task
Analyze if the change in the file breaks any of the downstream files.
Focus on:
- Import statements (will they fail?)
- Function/class usage (will calls fail?)
- Type mismatches

Respond in JSON format as specified.
"""
    return prompt


async def analyze_impact(diff: str, context: ReviewContext, changed_file: str) -> ReviewResult:
    """
    Analyzes the impact of changes using LLM.
    """
    logger.info(f"Analyzing impact for {changed_file} with {len(context.files)} context files")

    # Edge Case: Zero Dependencies
    if not context.files and not context.truncated:
        return ReviewResult(
            risk_level="SAFE",
            explanation=(
                "No downstream dependencies detected. This file is not imported by other modules (in the graph)."
            ),
            affected_files=[],
            recommendation="No action needed.",
            confidence=0.99,
        )

    client = LLMClient()

    if not client.api_key:
        return ReviewResult(
            risk_level="UNKNOWN",
            explanation="OpenAI API Key missing. Cannot perform semantic analysis.",
            affected_files=[f.path for f in context.files],
            recommendation="Configure OPENAI_API_KEY to enable smart review.",
            confidence=0.0,
        )

    messages = [
        {"role": "system", "content": _build_system_prompt()},
        {"role": "user", "content": _build_user_prompt(diff, context, changed_file)},
    ]

    try:
        response = await client.chat_completion(messages)
        content = response["choices"][0]["message"]["content"]
        data = json.loads(content)

        return ReviewResult(
            risk_level=data.get("risk_level", "UNKNOWN"),
            explanation=data.get("explanation", "No explanation provided."),
            affected_files=data.get("affected_files", []),
            recommendation=data.get("recommendation", ""),
            confidence=data.get("confidence", 0.5),
        )
    except Exception as e:
        logger.error(f"LLM analysis failed: {e}")
        # Fallback to deterministic summary
        return ReviewResult(
            risk_level="MEDIUM",  # Conservative default
            explanation=(f"Automated analysis unavailable. Graph shows {len(context.files)} affected files."),
            affected_files=[f.path for f in context.files],
            recommendation="Manual review recommended.",
            confidence=0.0,
        )
