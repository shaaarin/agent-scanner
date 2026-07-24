"""Trivial target agent for verifying interactor_mode=api: implements the
interactor's MVP wire contract (POST {"message": text} -> {"reply": text}).
"""
from fastapi import FastAPI, Request

app = FastAPI(title="echo-agent")


@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    message = body.get("message", "")
    return {"reply": f"echo: {message}"}
