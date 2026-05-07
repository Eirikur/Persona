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

PORT = 8401
MODEL = "gpt-4o-mini"
SYSTEM_PROMPT = "You are Persona, a helpful voice assistant."

app = FastAPI()
client = OpenAI()  # OPENAI_API_KEY from environment

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
