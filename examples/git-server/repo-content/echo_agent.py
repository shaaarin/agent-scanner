"""Trivial target agent for verifying interaction_mode=api: implements the
interactor's MVP wire contract (POST {"message": text} -> {"reply": text}).
Same content as examples/echo-agent -- served here from a self-hosted git
repo to prove the launcher's git-clone-based build pipeline end to end
without depending on GitHub reachability.
"""
from fastapi import FastAPI, Request

app = FastAPI(title="echo-agent")


@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    message = body.get("message", "")
    return {"reply": f"echo: {message}"}
