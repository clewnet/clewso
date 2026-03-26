import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from .context import ReviewContext

logger = logging.getLogger("clew.review.llm")

_RISK_LEVELS = frozenset({"HIGH", "MEDIUM", "LOW", "SAFE", "UNKNOWN"})


@dataclass(slots=True)
class ReviewResult:
    risk_level: str
    explanation: str
    affected_files: list[str]
    recommendation: str
    confidence: float = 0.0

    @classmethod
    def safe_no_deps(cls) -> "ReviewResult":
        """No downstream dependencies detected."""
        return cls(
            risk_level="SAFE",
            explanation=(
                "No downstream dependencies detected. This file is not imported by other modules (in the graph)."
            ),
            affected_files=[],
            recommendation="No action needed.",
            confidence=0.99,
        )

    @classmethod
    def missing_key(cls, context: ReviewContext) -> "ReviewResult":
        """API key is missing; cannot perform analysis."""
        return cls(
            risk_level="UNKNOWN",
            explanation="OpenAI API Key missing. Cannot perform semantic analysis.",
            affected_files=[f.path for f in context.files],
            recommendation="Configure OPENAI_API_KEY to enable smart review.",
            confidence=0.0,
        )

    @classmethod
    def fallback(cls, context: ReviewContext) -> "ReviewResult":
        """LLM call failed; conservative fallback."""
        return cls(
            risk_level="MEDIUM",
            explanation=(f"Automated analysis unavailable. Graph shows {len(context.files)} affected files."),
            affected_files=[f.path for f in context.files],
            recommendation="Manual review recommended.",
            confidence=0.0,
        )

    @classmethod
    def from_llm_response(cls, data: dict[str, Any]) -> "ReviewResult":
        """Parse a validated LLM JSON response into a result."""
        return cls(
            risk_level=data.get("risk_level", "UNKNOWN"),
            explanation=data.get("explanation", "No explanation provided."),
            affected_files=data.get("affected_files", []),
            recommendation=data.get("recommendation", ""),
            confidence=data.get("confidence", 0.5),
        )


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
        _validate_api_key(self.api_key)

    async def chat_completion(self, messages: list[dict[str, str]], json_mode: bool = True) -> dict[str, Any]:
        """Send chat completion request with retries."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = _build_payload(self.model, messages, json_mode)

        async with httpx.AsyncClient(timeout=60.0) as client:
            return await _retry_post(client, self.base_url, payload, headers)


def _validate_api_key(api_key: str | None) -> None:
    """Log warnings for missing or malformed API keys."""
    if not api_key:
        logger.warning("OPENAI_API_KEY not found. LLM features will fail.")
    elif not api_key.startswith("sk-"):
        logger.error("Invalid OpenAI API key format. Should start with 'sk-'.")


def _build_payload(model: str, messages: list[dict[str, str]], json_mode: bool) -> dict[str, Any]:
    """Assemble the chat-completion request body."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


async def _retry_post(
    client: httpx.AsyncClient,
    base_url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    max_attempts: int = 3,
) -> dict[str, Any]:
    """POST with exponential back-off retries."""
    url = f"{base_url}/chat/completions"
    for attempt in range(max_attempts):
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning("LLM request failed (attempt %d/%d): %s", attempt + 1, max_attempts, exc)
            if attempt == max_attempts - 1:
                raise
            await asyncio.sleep(1 * (attempt + 1))
    return {}


def _build_system_prompt() -> str:
    return (
        "You are a code review assistant specializing in architectural impact analysis.\n"
        "\n"
        "Your task: Analyze whether a code change introduces breaking changes to downstream files.\n"
        "\n"
        "RISK LEVELS:\n"
        "1. HIGH: Definite breaking change (ImportError, missing symbol, deleted file with live consumers)\n"
        "2. MEDIUM: Likely breaking change (signature mismatch, type change, semantic shift)\n"
        "3. LOW: Possible issue (style change, deprecation warning, minor refactor)\n"
        "4. SAFE: No breaking changes detected\n"
        "\n"
        "SAME-DIFF RULES (critical — apply these before assigning risk):\n"
        "- If a downstream consumer is marked **(also changed in this diff)**, check\n"
        "  whether the consumer's changes accommodate the breakage. If they do, the\n"
        "  risk is SAFE, not HIGH.\n"
        "- DELETION COHERENCE: If a file is deleted AND all of its downstream\n"
        "  consumers are also deleted in this diff, the removal is coordinated.\n"
        "  Flag SAFE, not HIGH.\n"
        "- RE-EXPORT CHECK: If a consumer only re-exports a symbol and that symbol\n"
        "  still exists (possibly with a changed shape) in the changed file, check\n"
        "  the co-changed consumer content to see if the re-export is still valid.\n"
        "- Do NOT flag risk based on hypothetical 'unlisted consumers.' Only assess\n"
        "  risk for the consumers actually listed in the downstream section.\n"
        "\n"
        "Only flag HIGH/MEDIUM if you have specific evidence from the provided code.\n"
        "\n"
        "Output format (JSON):\n"
        "{\n"
        '  "risk_level": "HIGH" | "MEDIUM" | "LOW" | "SAFE",\n'
        '  "explanation": "Specific reasoning based on code",\n'
        '  "affected_files": ["path/to/file.py"],\n'
        '  "recommendation": "Specific action to take",\n'
        '  "confidence": 0.0 to 1.0\n'
        "}"
    )


def _build_user_prompt(
    diff: str,
    context: ReviewContext,
    changed_file: str,
    impacts: list | None = None,
    notes: list[str] | None = None,
) -> str:
    ext = changed_file.rsplit(".", 1)[-1] if "." in changed_file else "unknown"
    sections = [f"# Changed File\nFile: {changed_file} (type: .{ext})\n\n# Diff\n{diff}\n"]

    # Summarize all known consumers (even if their source couldn't be loaded)
    if impacts:
        sections.append(f"# Downstream Consumers ({len(impacts)} files depend on this file)\n")
        for imp in impacts:
            if getattr(imp, "co_deleted", False):
                tag = " **(DELETED in this diff)**"
            elif getattr(imp, "co_changed", False):
                tag = " **(also changed in this diff)**"
            else:
                tag = ""
            sections.append(f"- `{imp.path}` via {imp.relationship}{tag}\n")
        sections.append("\n")

    if notes:
        sections.append("# Analysis Notes (verified facts — use these to inform your assessment)\n")
        for note in notes:
            sections.append(f"- {note}\n")
        sections.append("\n")

    if context.files:
        sections.append("# Downstream File Contents\n")
        for f in context.files:
            sections.append(f"\n## File: {f.path}\n{f.content}\n")

    sections.append(
        "\n# Task\n"
        "Analyze if the change in the file breaks any of the downstream files.\n"
        "Focus on:\n"
        "- Import statements (will they fail?)\n"
        "- Function/class usage (will calls fail?)\n"
        "- Type mismatches\n"
        "- If a downstream consumer is **also changed in this diff**, check whether\n"
        "  the co-change addresses the breakage. If it does, reduce the risk level.\n\n"
        "Respond in JSON format as specified.\n"
    )
    return "".join(sections)


async def analyze_impact(
    diff: str,
    context: ReviewContext,
    changed_file: str,
    impacts: list | None = None,
    notes: list[str] | None = None,
) -> ReviewResult:
    """Analyze the impact of changes using LLM."""
    logger.info(
        "Analyzing impact for %s with %d context files, %d graph impacts, %d notes",
        changed_file,
        len(context.files),
        len(impacts) if impacts else 0,
        len(notes) if notes else 0,
    )

    if not context.files and not impacts:
        return ReviewResult.safe_no_deps()

    client = LLMClient()
    if not client.api_key:
        return ReviewResult.missing_key(context)

    messages = [
        {"role": "system", "content": _build_system_prompt()},
        {"role": "user", "content": _build_user_prompt(diff, context, changed_file, impacts, notes)},
    ]

    try:
        response = await client.chat_completion(messages)
        content = response["choices"][0]["message"]["content"]
        return ReviewResult.from_llm_response(json.loads(content))
    except Exception as exc:
        logger.error("LLM analysis failed: %s", exc)
        return ReviewResult.fallback(context)
