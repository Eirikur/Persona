#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi",
#     "uvicorn",
#     "openai",
#     "python-dotenv",
#     "httpx",
# ]
# ///

"""Persona LLM — inference backend.

One route, `/v1/chat/completions`, fronting whichever provider the caller
names. Real providers go through the OpenAI-compatible client below; the
"echo" provider is a fake one that returns the last message verbatim with
no network call at all, for testing the rest of the pipeline for free.

A request can also name tools (see persona_tools.py) that the persona is
allowed to call. If the model asks for one, this file runs it and feeds
the result back, for up to a few rounds, before returning the final reply.
"""

import json
import os
import uvicorn
import httpx
from fastapi import FastAPI, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel
from dotenv import load_dotenv

from persona_schemas import DEFAULT_MODELS
from persona_tools import TOOLS
from persona_tool_log import save_calls

load_dotenv()


# ─── Configuration ────────────────────────────────────────────────────────────

PORT     = 8401
HUB_URL  = "http://127.0.0.1:8400"

MAX_TOOL_ROUNDS = 3   # safety valve against a model that never stops calling tools

# Real providers: (base_url, env var holding the API key, default model).
# "echo" is handled separately below -- it never reaches this table.
# Default models live in persona_schemas.DEFAULT_MODELS.
PROVIDERS = {
    "ollama":     ("http://localhost:11434/v1",  None,               DEFAULT_MODELS["ollama"]),
    "openai":     (None,                         "OPENAI_API_KEY",   DEFAULT_MODELS["openai"]),
    "cerebras":   ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", DEFAULT_MODELS["cerebras"]),
    # Perplexity as a persona's own model is switched off: its old
    # /chat/completions endpoint (Sonar) was retired in favour of the Agent API
    # (/v1/agent). Wanted back later as a persona of its own, including
    # follow-up questions (the Agent API's previous_response_id looks like the
    # way). Until then Perplexity is used through the "research" tool.
    # "perplexity": ("https://api.perplexity.ai",  "PPLX_API_KEY",     DEFAULT_MODELS["perplexity"]),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", DEFAULT_MODELS["openrouter"]),
}


# ─── API ───────────────────────────────────────────────────────────────────────

app = FastAPI()


class ChatRequest(BaseModel):
    provider: str = "ollama"
    model: str | None = None
    system_prompt: str = "You are Persona, a helpful voice assistant."
    messages: list[dict]
    tools: list[str] = []   # names into persona_tools.TOOLS this persona may call
    persona: str = ""       # who is asking; only used to label tool results for the data window


def run_tool_call(call, persona: str, question: str, calls_made: list) -> dict:
    """Run one model-requested tool call and return its result as a tool
    message. The hub gets a copy of the result for the data window, and
    calls_made gets one for the tool log once the reply is finished."""
    try:
        httpx.post(f"{HUB_URL}/tool_call/{call.function.name}", timeout=1.0)
    except Exception:
        pass  # the hub being briefly unavailable shouldn't block the tool call

    tool = TOOLS.get(call.function.name)
    if tool:
        output = tool["run"](json.loads(call.function.arguments))
    else:
        output = f"Unknown tool: {call.function.name}"

    # A tool returns plain text, or {"text": ..., "data": ...} when it also
    # has a full structure behind the text (see persona_tools.py).
    if isinstance(output, dict):
        result = output["text"]
        data   = json.dumps(output["data"], indent=2, ensure_ascii=False)
    else:
        result = output
        data   = ""

    record = {
        "persona":   persona,
        "question":  question,
        "tool":      call.function.name,
        "arguments": call.function.arguments,
        "result":    result,
        "data":      data,
    }
    report_tool_result(record)
    calls_made.append(record)

    return {"role": "tool", "tool_call_id": call.id, "content": result}


def report_tool_result(record: dict) -> None:
    """
    Send the hub what a tool was asked and what it returned, exactly as the
    model sent and received them, so the owner can see it in the data window.
    The record's data is the tool's full structure as JSON text, or "".
    """
    try:
        httpx.post(f"{HUB_URL}/tool_result", json=record, timeout=1.0)
    except Exception:
        pass  # a missing copy for the data window shouldn't block the reply


@app.post("/v1/chat/completions")
async def chat(req: ChatRequest):
    """Return a completion in OpenAI's response shape, from a real provider
    or, for provider "echo", by handing the last message straight back."""

    if req.provider == "echo":
        heard = req.messages[-1]["content"] if req.messages else ""
        return {"choices": [{"message": {"role": "assistant", "content": heard}}]}

    if req.provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {req.provider!r}")
    base_url, key_env, default_model = PROVIDERS[req.provider]
    api_key = os.environ.get(key_env, "local") if key_env else "local"
    model = req.model or default_model
    if not model:
        raise HTTPException(status_code=400, detail=f"No default model for {req.provider!r}")
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    messages = [{"role": "system", "content": req.system_prompt}] + req.messages

    tool_schemas = [TOOLS[name]["schema"] for name in req.tools if name in TOOLS]

    calls_made = []   # every tool call for this reply, saved to the tool log at the end

    for _ in range(MAX_TOOL_ROUNDS):
        kwargs = {"model": model, "messages": messages}
        if tool_schemas:
            kwargs["tools"] = tool_schemas
        response = await client.chat.completions.create(**kwargs)

        message = response.choices[0].message
        if not message.tool_calls:
            save_calls(calls_made, message.content or "")
            return response.model_dump()

        # Only the standard tool-calling fields -- some providers (Cerebras)
        # reject the extra None-valued fields a full message.model_dump()
        # includes (refusal, annotations, audio, function_call).
        messages.append({
            "role":       "assistant",
            "content":    message.content,
            "tool_calls": [
                {
                    "id":       call.id,
                    "type":     "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in message.tool_calls
            ],
        })
        question = req.messages[-1]["content"] if req.messages else ""

        for call in message.tool_calls:
            messages.append(run_tool_call(call, req.persona, question, calls_made))

    # Out of tool rounds: the last answer is whatever the model said alongside
    # its final tool request, often nothing.
    save_calls(calls_made, response.choices[0].message.content or "")
    return response.model_dump()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
