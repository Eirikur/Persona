"""Persona Tools — function-calling registry for personas.

A tool is a name, an OpenAI-style function schema, and a plain Python
function that runs it. A Persona's `tools` list just names entries here;
persona_llm.py looks them up by name and knows nothing else about them.

To add a tool: write a function that takes the call's arguments (a dict)
and returns a string result, write its schema, and add both to TOOLS.
"""

import os
import httpx


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


# ─── Registry ──────────────────────────────────────────────────────────────────

TOOLS = {
    "web_search": {"schema": WEB_SEARCH_SCHEMA, "run": web_search},
}
