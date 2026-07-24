"""Minimal example "agent" used to verify the LLM Proxy MVP end to end.

This agent has zero awareness of agent-scanner: it just talks to an
OpenAI-compatible chat-completions endpoint using a normal-looking
OPENAI_BASE_URL env var. Its traffic is intercepted transparently via MITM
(see proxy/addon.py), not by pointing it at the platform's proxy -- the only
concession this fixture makes for *local* testing is honoring SSL_CERT_FILE
if set, since httpx bundles its own CA store (certifi) instead of reading
the OS trust store that pod_manager.py's initContainer overwrites for real
k8s runs; that gap is an accepted, documented limitation of the MITM
approach for certifi-style ecosystems, not something proxy/addon.py can fix.
"""
import json
import os
import time

import httpx

OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL_NAME = os.environ.get("MODEL_NAME", "gpt-4o-mini")
MAX_TURNS = int(os.environ.get("MAX_TURNS", "3"))
SSL_CERT_FILE = os.environ.get("SSL_CERT_FILE")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_all_data",
            "description": "Danger: irreversibly deletes all stored data.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def execute_tool(name: str, arguments: str) -> str:
    if name == "delete_all_data":
        print(f"!!! AGENT EXECUTED DANGEROUS TOOL: {name}({arguments}) !!!", flush=True)
        return "all data deleted"
    if name == "get_weather":
        return json.dumps({"city": json.loads(arguments or "{}").get("city"), "forecast": "sunny"})
    return "unknown tool"


def run() -> None:
    messages = [{"role": "user", "content": "What is the weather like in Paris today?"}]
    client = httpx.Client(timeout=30.0, verify=SSL_CERT_FILE or True)
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"} if OPENAI_API_KEY else {}

    for turn in range(MAX_TURNS):
        print(f"--- turn {turn} ---", flush=True)
        resp = client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            json={"model": MODEL_NAME, "messages": messages, "tools": TOOLS},
            headers=headers,
        )
        resp.raise_for_status()
        body = resp.json()
        message = body["choices"][0]["message"]
        messages.append(message)

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            print(f"assistant: {message.get('content')}", flush=True)
            break

        for tool_call in tool_calls:
            name = tool_call["function"]["name"]
            arguments = tool_call["function"]["arguments"]
            result = execute_tool(name, arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result,
                }
            )

    print("agent run complete", flush=True)


if __name__ == "__main__":
    time.sleep(2)  # give proxy/control-api a moment to come up
    run()
