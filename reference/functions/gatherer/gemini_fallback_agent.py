from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4


def _load_schema_models():
    try:
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise ValueError("pydantic is required for the ADK Gemini fallback") from exc

    class GeminiFallbackInput(BaseModel):
        region_code: str = Field(description="Canonical NewsCloud region code such as US-PA, TT, or UK.")
        region_name: str = Field(description="Human-readable region name.")
        run_date: str = Field(description="Canonical run date in YYYY-MM-DD format.")
        allowed_topics: list[str] = Field(description="State or region issue lanes that are acceptable to return.")
        max_results: int = Field(description="Maximum number of fallback results to return.")

    class FallbackHeadline(BaseModel):
        title: str = Field(description="Exact headline text from the source article.")
        source_name: str = Field(description="Publisher or outlet name.")
        url: str = Field(description="Canonical article URL.")
        published_date: str = Field(description="Published date in YYYY-MM-DD format.")
        excerpt: str = Field(description="Short factual excerpt from the article.")
        why_relevant: str = Field(description="One sentence explaining why the item matters for the region.")

    class GeminiFallbackOutput(BaseModel):
        results: list[FallbackHeadline] = Field(description="Validated fallback headline candidates.")

    return GeminiFallbackInput, GeminiFallbackOutput


def _load_adk_agent():
    try:
        from google.adk.agents import LlmAgent
    except ImportError:
        try:
            from google.adk.agents.llm_agent import LlmAgent
        except ImportError as exc:
            raise ValueError("google-adk is required for the ADK Gemini fallback") from exc
    return LlmAgent


def _load_adk_runtime():
    try:
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types
    except ImportError as exc:
        raise ValueError("google-adk runtime dependencies are required for the ADK Gemini fallback") from exc
    return Runner, InMemorySessionService, types


async def _run_agent_once_async(agent: Any, prompt: str, *, app_name: str, output_key: str | None = None):
    Runner, InMemorySessionService, types = _load_adk_runtime()
    session_service = InMemorySessionService()
    user_id = "newscloud"
    session_id = f"{app_name}-{uuid4().hex}"
    await session_service.create_session(app_name=app_name, user_id=user_id, session_id=session_id)
    runner = Runner(agent=agent, app_name=app_name, session_service=session_service)
    user_content = types.Content(role="user", parts=[types.Part(text=prompt)])

    final_response_text = ""
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=user_content):
        if event.is_final_response() and event.content and event.content.parts:
            final_response_text = "".join(part.text or "" for part in event.content.parts).strip()

    session = await session_service.get_session(app_name=app_name, user_id=user_id, session_id=session_id)
    stored_output = None
    if session and output_key:
        stored_output = session.state.get(output_key)
    return final_response_text, stored_output


def _run_agent_once(agent: Any, prompt: str, *, app_name: str, output_key: str | None = None):
    return asyncio.run(_run_agent_once_async(agent, prompt, app_name=app_name, output_key=output_key))


def _validate_structured_output(schema_model: Any, payload: Any):
    if payload is None:
        raise ValueError("ADK Gemini fallback returned an empty payload")

    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8")

    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            raise ValueError("ADK Gemini fallback returned an empty payload")
        return schema_model.model_validate_json(stripped)

    if isinstance(payload, dict):
        return schema_model.model_validate(payload)

    model_dump = getattr(payload, "model_dump", None)
    if callable(model_dump):
        return schema_model.model_validate(model_dump(by_alias=True))

    return schema_model.model_validate(payload)


def fetch_headlines_via_adk(
    *,
    model: str,
    region_code: str,
    region_name: str,
    run_date: str,
    allowed_topics: list[str],
    max_results: int,
) -> dict[str, list[dict[str, str]]]:
    GeminiFallbackInput, GeminiFallbackOutput = _load_schema_models()
    LlmAgent = _load_adk_agent()

    contract = GeminiFallbackInput(
        region_code=region_code,
        region_name=region_name,
        run_date=run_date,
        allowed_topics=allowed_topics,
        max_results=max_results,
    )

    instruction = """You are a regional political news gatherer for NewsCloud.

Return only structured output that matches the output schema.

Rules:
- Focus on regional politics, state government, elections, courts, and public policy.
- Prefer local reporting, statehouse reporting, and credible statewide outlets.
- Exclude sports, university athletics, gambling, promotions, crime-blotter-only items, and generic national stories that only mention the region in passing.
- Prefer items published on the requested run_date. If no same-day items exist, older items are allowed only if the published_date is exact.
- Do not invent URLs, titles, publishers, dates, excerpts, or explanations.
- Keep excerpts factual and concise.
"""
    prompt = (
        "Find recent regional political news using this input contract.\n\n"
        f"{contract.model_dump_json(indent=2)}"
    )
    agent = LlmAgent(
        name="newscloud_gemini_fallback",
        description="Structured regional political news fallback for thin-coverage days.",
        model=model,
        instruction=instruction,
        output_schema=GeminiFallbackOutput,
        output_key="fallback_result",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )
    final_text, stored_output = _run_agent_once(
        agent,
        prompt,
        app_name="newscloud_gemini_fallback",
        output_key="fallback_result",
    )
    payload = stored_output or final_text
    if not payload:
        raise ValueError("ADK Gemini fallback returned an empty response")
    parsed = _validate_structured_output(GeminiFallbackOutput, payload)
    return parsed.model_dump()
