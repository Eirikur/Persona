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
import openai
from urllib.parse import urlsplit
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


# ─── Provider Check ───────────────────────────────────────────────────────────

MODEL_LIST_TIMEOUT = 10.0   # seconds per provider; a working one answers in well under that


def url_looks_wrong(url: str | None) -> str:
    """
    Why a provider URL is plainly broken (spaces in it, no http/https, no
    host name), or "" if it looks fine. This catches typos before any call:
    a mistyped host and a service that's switched off fail the same way.
    """
    if url is None:
        return ""   # the OpenAI client's own built-in URL

    if " " in url:
        return "the URL has a space in it: " + repr(url)

    parts = urlsplit(url)

    if parts.scheme not in ("http", "https"):
        return "the URL doesn't start with http:// or https://: " + repr(url)

    if not parts.hostname:
        return "the URL has no host name: " + repr(url)

    return ""


async def fetch_models(provider: str) -> dict:
    """
    Ask one provider for its model list, the same way chat() reaches it.
    The answer says how it went:

      ok            -- models holds every model id
      bad_url       -- the URL itself is broken, nothing was sent
      no_key        -- the URL works but no API key is set for it
      key_rejected  -- the URL works but the provider refused the key
      unreachable   -- no answer (wrong host, or the service is off)
      error         -- anything else; reason says what
    """
    base_url, key_env, default_model = PROVIDERS[provider]
    has_key = bool(key_env and os.environ.get(key_env))
    api_key = os.environ.get(key_env, "local") if key_env else "local"

    answer = {"provider": provider, "status": "ok", "reason": "", "models": []}

    problem = url_looks_wrong(base_url)
    if problem:
        answer["status"] = "bad_url"
        answer["reason"] = problem
        return answer

    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=MODEL_LIST_TIMEOUT, max_retries=0)

    try:
        page = await client.models.list()
        answer["models"] = [model.id for model in page.data]

    except (openai.AuthenticationError, openai.PermissionDeniedError) as refused:
        if has_key:
            answer["status"] = "key_rejected"
        else:
            answer["status"] = "no_key"
        answer["reason"] = str(refused)

    except openai.APIConnectionError as no_answer:
        answer["status"] = "unreachable"
        answer["reason"] = str(no_answer) + " (" + str(base_url) + ")"

    except Exception as other:
        answer["status"] = "error"
        answer["reason"] = type(other).__name__ + ": " + str(other)

    return answer


@app.get("/provider_models")
async def provider_models():
    """Every real provider's model list, or why it couldn't be fetched.
    The hub calls this at startup to prove each provider's URL works."""
    answers = []

    for provider in PROVIDERS:
        answers.append(await fetch_models(provider))

    return answers


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
