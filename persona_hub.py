#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi",
#     "uvicorn",
#     "httpx",
# ]
# ///

import uvicorn
import httpx
from dataclasses import dataclass
from fastapi import FastAPI
from pydantic import BaseModel

PORT = 8400
LLM_URL = "http://127.0.0.1:8401"

@dataclass
class Config:
    provider: str = "ollama"
    model: str | None = None

cfg = Config()
app = FastAPI()

class ThinkRequest(BaseModel):
    text: str

@app.post("/think")
def think(req: ThinkRequest):
    r = httpx.post(f"{LLM_URL}/v1/chat/completions", timeout=60.0, json={
        "provider": cfg.provider,
        "model": cfg.model,
        "messages": [{"role": "user", "content": req.text}],
    })
    r.raise_for_status()
    return {"text": r.json()["choices"][0]["message"]["content"]}

services = ['speech_input', 'llm', 'speech_output']

def check_services():
    pass

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
