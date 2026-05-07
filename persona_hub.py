#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "openai",
# ]
# ///

from openai import OpenAI

LLM_URL = "http://127.0.0.1:8401/v1"  # 8401=cloud, 8402=local
LLM_MODEL = "gpt-4o-mini"

client = OpenAI(base_url=LLM_URL, api_key="persona")

def ask(messages: list[dict]) -> str:
    response = client.chat.completions.create(model=LLM_MODEL, messages=messages)
    return response.choices[0].message.content

services = ['speech_input', 'speech_output', 'llm']

def start_up():
    pass

def check_services():
    pass
