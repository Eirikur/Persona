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

from persona_tools import TOOLS

load_dotenv()


# ─── Configuration ────────────────────────────────────────────────────────────

PORT     = 8401
HUB_URL  = "http://127.0.0.1:8400"

MAX_TOOL_ROUNDS = 3   # safety valve against a model that never stops calling tools

# Real providers: (base_url, env var holding the API key, default model).
# "echo" is handled separately below -- it never reaches this table.
PROVIDERS = {
    "ollama":     ("http://localhost:11434/v1",  None,               "gemma3:12b"),
    "openai":     (None,                         "OPENAI_API_KEY",   "gpt-4o-mini"),
    "cerebras":   ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", "qwen-3.8-27b"),
    "perplexity": ("https://api.perplexity.ai",  "PPLX_API_KEY",     "sonar"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "google/gemini-2.0-flash-001"),
}


# ─── API ───────────────────────────────────────────────────────────────────────

app = FastAPI()


class ChatRequest(BaseModel):
    provider: str = "ollama"
    model: str | None = None
    system_prompt: str = "You are Persona, a helpful voice assistant."
    messages: list[dict]
    tools: list[str] = []   # names into persona_tools.TOOLS this persona may call


def run_tool_call(call) -> dict:
    """Run one model-requested tool call and return its result as a tool message."""
    try:
        httpx.post(f"{HUB_URL}/tool_call/{call.function.name}", timeout=1.0)
    except Exception:
        pass  # the hub being briefly unavailable shouldn't block the tool call

    tool = TOOLS.get(call.function.name)
    if tool:
        result = tool["run"](json.loads(call.function.arguments))
    else:
        result = f"Unknown tool: {call.function.name}"
    return {"role": "tool", "tool_call_id": call.id, "content": result}


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

    for _ in range(MAX_TOOL_ROUNDS):
        kwargs = {"model": model, "messages": messages}
        if tool_schemas:
            kwargs["tools"] = tool_schemas
        response = await client.chat.completions.create(**kwargs)

        message = response.choices[0].message
        if not message.tool_calls:
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
        messages.extend(run_tool_call(call) for call in message.tool_calls)

    return response.model_dump()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
