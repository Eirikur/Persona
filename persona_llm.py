#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi",
#     "uvicorn",
#     "openai",
# ]
# ///

import os
import uvicorn
from fastapi import FastAPI, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel

PORT = 8401

_PROVIDERS = {
    "ollama":     ("http://localhost:11434/v1",  None,               "gemma2"),
    "openai":     (None,                         "OPENAI_API_KEY",   "gpt-4o-mini"),
    "cerebras":   ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", "gemma-4-31b"),
    "perplexity": ("https://api.perplexity.ai",  "PPLX_API_KEY",     "sonar"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "google/gemini-2.0-flash-001"),
    "z800":       ("http://z800.local:11434/v1", None,               "gemma3:latest"),
    "llamacpp":   ("http://z800.local:8080/v1",  None,               None),
    "vllm":       ("http://z800.local:8000/v1",  None,               None),
}

app = FastAPI()

class ChatRequest(BaseModel):
    provider: str = "ollama"
    model: str | None = None
    system_prompt: str = "You are Persona, a helpful voice assistant."
    messages: list[dict]

@app.post("/v1/chat/completions")
async def chat(req: ChatRequest):
    if req.provider not in _PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {req.provider!r}")
    base_url, key_env, default_model = _PROVIDERS[req.provider]
    api_key = os.environ.get(key_env, "local") if key_env else "local"
    model = req.model or default_model
    if not model:
        raise HTTPException(status_code=400, detail=f"No default model for {req.provider!r}")
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    messages = [{"role": "system", "content": req.system_prompt}] + req.messages
    response = await client.chat.completions.create(model=model, messages=messages)
    return response.model_dump()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
