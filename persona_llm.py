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

from persona_schemas import DEFAULT_MODELS, PRICE_URLS, RESEARCH_ALLOWED_DEPTHS
from persona_tools import TOOLS
from persona_tool_log import save_calls, save_turn
from persona_backstage import total_tokens
from persona_prices import read_price_list, turn_cost

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
    research_depth: str = "auto"   # the owner's research depth; "auto" = the persona chooses


def research_depth_to_use(args: dict, owner_depth: str) -> str:
    """
    The depth a research call actually runs at. The owner's choice (Settings
    tab, or a spoken phrase) wins. On "auto" the persona's own choice is used,
    but only up to RESEARCH_ALLOWED_DEPTHS: deeper ones hold up a spoken reply
    for minutes, so the persona can't pick them on its own.
    """
    if owner_depth != "auto":
        return owner_depth

    chosen = args.get("depth", "quick")
    if chosen not in RESEARCH_ALLOWED_DEPTHS:
        chosen = "normal"

    return chosen


def run_tool_call(call, persona: str, question: str, calls_made: list, research_depth: str) -> dict:
    """Run one model-requested tool call and return its result as a tool
    message. The hub gets a copy of the result for the data window, and
    calls_made gets one for the tool log once the reply is finished.
    A research call runs at research_depth_to_use()'s depth, and the copies
    show the arguments as actually run, depth included."""
    try:
        httpx.post(f"{HUB_URL}/tool_call/{call.function.name}", timeout=1.0)
    except Exception:
        pass  # the hub being briefly unavailable shouldn't block the tool call

    args = json.loads(call.function.arguments)

    if call.function.name == "research":
        args["depth"] = research_depth_to_use(args, research_depth)
        print(f"research at depth {args['depth']}: {args.get('query', '')}")

    tool = TOOLS.get(call.function.name)
    if tool:
        output = tool["run"](args)
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
        "arguments": json.dumps(args, ensure_ascii=False),
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


# ─── Backstage Record ─────────────────────────────────────────────────────────

# Where a model puts its thinking, if it sends any. Cerebras and OpenRouter
# use "reasoning"; DeepSeek-style models use "reasoning_content".
REASONING_FIELDS = ("reasoning", "reasoning_content")


def step(kind: str, title: str, text: str) -> dict:
    """
    One step of a turn, shown as one folding section in the Backstage
    window. The kind ("system", "reasoning", "tool_call", ...) decides
    whether the section starts folded; the title is its heading line.
    """
    return {"kind": kind, "title": title, "text": text}


def opening_steps(system_prompt: str, messages: list[dict]) -> list[dict]:
    """
    The steps for what the model is sent before it answers: the system
    prompt (with mem0's memories, if any), the replayed history, and the
    new input, which is the last message.
    """
    history = messages[:-1]

    history_parts = []
    for message in history:
        history_parts.append("[" + message["role"] + "]\n" + message["content"])

    history_title = "Replayed history: " + str(len(history)) + " messages"

    steps = [
        step("system",  "System prompt", system_prompt),
        step("history", history_title,   "\n\n".join(history_parts)),
    ]

    if messages:
        steps.append(step("input", "Input", messages[-1]["content"]))

    return steps


def reasoning_of(message) -> str:
    """The model's thinking for one answer, or "" if it sent none."""
    for field in REASONING_FIELDS:
        value = getattr(message, field, None)
        if value:
            return value

    return ""


def token_counts(usage) -> dict:
    """
    One answer's token counts as plain numbers: tokens in (and how many of
    those the provider had cached), tokens out (and how many of those were
    reasoning). All zero if the provider sent no counts.
    """
    counts = {"in": 0, "cached": 0, "out": 0, "reasoning": 0}
    if usage is None:
        return counts

    counts["in"]  = usage.prompt_tokens or 0
    counts["out"] = usage.completion_tokens or 0

    if usage.prompt_tokens_details and usage.prompt_tokens_details.cached_tokens:
        counts["cached"] = usage.prompt_tokens_details.cached_tokens

    if usage.completion_tokens_details and usage.completion_tokens_details.reasoning_tokens:
        counts["reasoning"] = usage.completion_tokens_details.reasoning_tokens

    return counts


def answer_steps(response, round_number: int) -> list[dict]:
    """
    The steps for one answer from the model: its reasoning, if it sent any,
    and its token counts. The token step also carries the counts as
    numbers, for adding up later.
    """
    label  = "Round " + str(round_number)
    steps  = []

    reasoning = reasoning_of(response.choices[0].message)
    if reasoning:
        steps.append(step("reasoning", label + ": reasoning", reasoning))

    counts = token_counts(response.usage)
    text = (str(counts["in"]) + " in (" + str(counts["cached"]) + " cached), "
            + str(counts["out"]) + " out (" + str(counts["reasoning"]) + " reasoning)")

    tokens_step = step("tokens", label + ": tokens", text)
    tokens_step["counts"] = counts
    steps.append(tokens_step)

    return steps


def report_turn(req: ChatRequest, model: str, steps: list[dict], cost: float | None) -> None:
    """
    Send the hub the whole turn, step by step, and what it cost, for the
    Backstage window. Like report_tool_result(), a failure here never
    blocks the reply.
    """
    turn = {
        "persona":  req.persona,
        "provider": req.provider,
        "model":    model,
        "steps":    steps,
        "cost":     cost,
    }

    try:
        httpx.post(f"{HUB_URL}/turn", json=turn, timeout=1.0)
    except Exception:
        pass  # a missing Backstage record shouldn't block the reply


def finish_turn(req: ChatRequest, model: str, steps: list[dict], response, calls_made: list) -> dict:
    """
    End a turn: add the reply to the steps, work out what the turn cost,
    save the tool calls and the turn's numbers to the tool log, send the
    turn to Backstage, and return the response in OpenAI's shape.
    """
    reply = response.choices[0].message.content or ""
    steps.append(step("reply", "Reply", reply))

    tokens = total_tokens(steps)
    cost   = turn_cost(req.provider, model, tokens)

    save_calls(calls_made, reply)
    save_turn(req.persona, req.provider, model, tokens, len(calls_made), cost)
    report_turn(req, model, steps, cost)

    return response.model_dump()


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

    # The whole turn, step by step, for the Backstage window. Kept apart from
    # messages, which go back to the provider: it rejects unknown fields.
    steps = opening_steps(req.system_prompt, req.messages)

    for round_number in range(1, MAX_TOOL_ROUNDS + 1):
        kwargs = {"model": model, "messages": messages}
        if tool_schemas:
            kwargs["tools"] = tool_schemas
        response = await client.chat.completions.create(**kwargs)

        steps.extend(answer_steps(response, round_number))

        message = response.choices[0].message
        if not message.tool_calls:
            return finish_turn(req, model, steps, response, calls_made)

        if message.content and message.content.strip():
            steps.append(step("said", "Said with the tool request", message.content))

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
            steps.append(step("tool_call", "Tool call: " + call.function.name, call.function.arguments))

            tool_message = run_tool_call(call, req.persona, question, calls_made, req.research_depth)
            messages.append(tool_message)

            result_title = ("Tool result: " + call.function.name + ", "
                            + str(len(tool_message["content"])) + " characters")
            steps.append(step("tool_result", result_title, tool_message["content"]))

    # Out of tool rounds. Every tool result is in messages by now, so ask one
    # last time with tool calls switched off (tool_choice "none"): the model
    # has to answer with what it found, even when its sources disagree.
    # Without this, the reply is whatever the model said alongside its last
    # tool request, which is usually nothing, and the persona stays silent.
    print(f"out of tool rounds after {len(calls_made)} tool calls; asking for an answer with tools off")

    kwargs = {"model": model, "messages": messages}
    if tool_schemas:
        kwargs["tools"]       = tool_schemas
        kwargs["tool_choice"] = "none"
    response = await client.chat.completions.create(**kwargs)

    steps.extend(answer_steps(response, MAX_TOOL_ROUNDS + 1))

    return finish_turn(req, model, steps, response, calls_made)


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

    answer["prices"] = await fetch_prices(provider)

    return answer


async def fetch_prices(provider: str) -> dict:
    """
    This provider's prices as {model: {"in": ..., "out": ...}}, in dollars
    per token (see persona_prices.py). Empty if it publishes none (not in
    PRICE_URLS) or the fetch failed; the hub then keeps its old prices.
    """
    if provider not in PRICE_URLS:
        return {}

    try:
        async with httpx.AsyncClient(timeout=MODEL_LIST_TIMEOUT) as client:
            listing = await client.get(PRICE_URLS[provider])
            listing.raise_for_status()
            return read_price_list(listing.json())

    except Exception as problem:
        print(f"prices for {provider}: could not fetch: {type(problem).__name__} {problem}")
        return {}


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
