#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi",
#     "uvicorn",
#     "openai",
# ]
# ///

import uvicorn
from fastapi import FastAPI
from openai import OpenAI
from pydantic import BaseModel

PORT = 8402
BACKEND_URL = "http://localhost:11434/v1"  # Ollama default
MODEL = "qwen3:8b"
SYSTEM_PROMPT = "You are Persona, a helpful voice assistant."

app = FastAPI()
client = OpenAI(base_url=BACKEND_URL, api_key="ollama")

class ChatRequest(BaseModel):
    model: str = MODEL
    messages: list[dict]

@app.post("/v1/chat/completions")
def chat(req: ChatRequest):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + req.messages
    response = client.chat.completions.create(model=req.model, messages=messages)
    return response.model_dump()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
