"""Persona Tools — function-calling registry for personas.

A tool is a name, an OpenAI-style function schema, and a plain Python
function that runs it. A Persona's `tools` list just names entries here;
persona_llm.py looks them up by name and knows nothing else about them.

To add a tool: write a function that takes the call's arguments (a dict)
and returns a string result, write its schema, and add both to TOOLS.

A tool whose source gives structured data (research, below) may instead
return a dict: {"text": what the persona reads, "data": the full structure}.
The persona only ever sees "text"; "data" goes to the data window.
"""

import json
import os
import re
import shutil
import subprocess
import httpx

from persona_schemas import (
    NEWS_SOURCES, NEWS_MAX_ITEMS,
    RESEARCH_PRESETS, RESEARCH_ALLOWED_DEPTHS, RESEARCH_TIMEOUT,
)


# ─── Web Search (Brave) ────────────────────────────────────────────────────────

def web_search(args: dict) -> str:
    """Run a Brave Search query and return the top results as plain text."""
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        return "Web search is not configured -- no BRAVE_API_KEY set in .env."

    query = args.get("query", "")
    response = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params  = {"q": query},
        headers = {"Accept": "application/json", "X-Subscription-Token": api_key},
        timeout = 10.0,
    )
    response.raise_for_status()
    results = response.json().get("web", {}).get("results", [])[:5]

    if not results:
        return f"No results found for {query!r}."

    return "\n\n".join(
        f"{r['title']} -- {r['url']}\n{r.get('description', '')}" for r in results
    )


WEB_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information via Brave Search.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for."},
            },
            "required": ["query"],
        },
    },
}


# ─── News (command-line readers) ───────────────────────────────────────────────

def find_news_program(source: dict) -> str | None:
    """Return the full path of a news program, or None if it is not installed.
    The environment variable named in the source wins over a PATH lookup."""
    from_env = os.environ.get(source["env_var"])
    if from_env and os.path.exists(from_env):
        return from_env
    return shutil.which(source["program"])


def news_read(args: dict) -> str:
    """Read current headlines from a news command-line tool and return them as
    plain sentences for speaking aloud. Optionally keep only the headlines that
    mention a keyword."""
    source_name = args.get("source", "bbc")
    section     = args.get("section", "world")
    keyword     = args.get("keyword", "").strip().lower()
    count       = min(int(args.get("count", 5)), NEWS_MAX_ITEMS)

    source = NEWS_SOURCES.get(source_name)
    if not source:
        return "Unknown news source " + repr(source_name) + ". Known: " + ", ".join(NEWS_SOURCES)
    if section not in source["sections"]:
        return "Unknown section " + repr(section) + ". Known: " + ", ".join(source["sections"])

    program = find_news_program(source)
    if not program:
        return source_name + " is not installed. Set " + source["env_var"] + " in .env."

    try:
        finished = subprocess.run(
            [program, section], capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return source_name + " news timed out."
    if finished.returncode != 0:
        return source_name + " news failed: " + finished.stderr.strip()[:200]

    items = []
    for line in finished.stdout.splitlines():
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue   # progress lines such as 'fetching section ...'

    if keyword:
        items = [i for i in items
                 if keyword in (i.get("title", "") + " " + i.get("description", "")).lower()]
    if not items:
        return "No " + source_name + " headlines found" + (" mentioning " + repr(keyword) if keyword else "") + "."

    sentences = []
    for item in items[:count]:
        sentences.append(item["title"] + ". " + item.get("description", "")
                         + " (" + item.get("published", "time unknown") + ")")
    return "\n\n".join(sentences)


NEWS_READ_SCHEMA = {
    "type": "function",
    "function": {
        "name": "news_read",
        "description": ("Get current news headlines (one line each, no detail) from a "
                        "news service. Use for \"what's in the news\". For explaining "
                        "a story, use research instead. Optionally filter by a "
                        "keyword such as a country or city."),
        "parameters": {
            "type": "object",
            "properties": {
                "source":  {"type": "string",
                            "enum": list(NEWS_SOURCES),
                            "description": "News service, not a section. Default bbc."},
                "section": {"type": "string",
                            "enum": list(NEWS_SOURCES["bbc"]["sections"]),
                            "description": "Part of the news to read. Default world."},
                "keyword": {"type": "string", "description": "Only headlines mentioning this word, e.g. Ukraine."},
                "count":   {"type": "integer", "description": "How many headlines, at most " + str(NEWS_MAX_ITEMS) + ". Default 5."},
            },
            "required": [],
        },
    },
}


# ─── Research (Perplexity Agent API) ──────────────────────────────────────────

def research_sources(response: dict) -> list[dict]:
    """Every source Perplexity's searches found, from all its search_results items, in id order."""
    sources = []
    for item in response.get("output", []):
        if item.get("type") == "search_results":
            sources.extend(item.get("results", []))

    sources.sort(key=lambda source: source.get("id", 0))
    return sources


def research_answer(response: dict) -> str:
    """Perplexity's written answer: the text parts of its message items, joined."""
    parts = []
    for item in response.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    parts.append(content.get("text", ""))

    return "\n\n".join(parts)


def research(args: dict) -> dict | str:
    """
    Ask Perplexity to research a question and return its answer with a
    numbered source list. Depth picks the preset (see RESEARCH_PRESETS);
    a depth not in RESEARCH_ALLOWED_DEPTHS is lowered to "normal".
    """
    api_key = os.environ.get("PPLX_API_KEY")
    if not api_key:
        return "Research is not configured -- no PPLX_API_KEY set in .env."

    query = args.get("query", "")
    depth = args.get("depth", "quick")
    if depth not in RESEARCH_ALLOWED_DEPTHS:
        depth = "normal"

    try:
        reply = httpx.post(
            "https://api.perplexity.ai/v1/agent",
            headers = {"Authorization": "Bearer " + api_key},
            json    = {"preset": RESEARCH_PRESETS[depth], "input": query},
            timeout = RESEARCH_TIMEOUT,
        )
    except httpx.TimeoutException:
        return "Research timed out after " + str(RESEARCH_TIMEOUT) + " seconds."

    if reply.status_code != 200:
        return "Research failed: " + str(reply.status_code) + " " + reply.text[:200]

    response = reply.json()
    answer   = research_answer(response)
    sources  = research_sources(response)

    # Perplexity marks claims with source ids, "[web:3]" or "[3]". The
    # persona would read those out loud, so they come out of the answer;
    # the numbered list below keeps which sources were used.
    marker = r"\[(web:)?\d+\]"
    answer = re.sub(marker, "", answer)

    lines = [answer, "", "Sources:"]
    for source in sources:
        lines.append(str(source.get("id")) + ". " + (source.get("title") or "")
                     + " (" + (source.get("date") or "no date") + ") " + (source.get("url") or ""))

    return {"text": "\n".join(lines), "data": response}


RESEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "research",
        "description": ("Research a question on the web with Perplexity, which searches, "
                        "reads and answers with sources. Use it first, and on its own, "
                        "when the owner says \"look up\" or \"research\", or asks a "
                        "question that needs current facts or an explanation."),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The question, as a full sentence."},
                "depth": {"type": "string",
                          "description": ("quick: one search, for single facts. "
                                          "normal: several searches, for explanations "
                                          "and current events. Default quick.")},
            },
            "required": ["query"],
        },
    },
}


# ─── Registry ──────────────────────────────────────────────────────────────────

TOOLS = {
    "web_search": {"schema": WEB_SEARCH_SCHEMA, "run": web_search},
    "news_read":  {"schema": NEWS_READ_SCHEMA, "run": news_read},
    "research":   {"schema": RESEARCH_SCHEMA,  "run": research},
}
