import asyncio
import json

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app import control_client, fuzz_engine, llm_client, tree_engine
from app.prompts import ADAPT_PROMPT, ATTACK_CLASS_PROMPTS, MUTATION_PROMPT

app = FastAPI(title="agent-scanner attack generator")

_running_fuzz_tasks: dict[int, asyncio.Task] = {}
_running_tree_tasks: dict[int, asyncio.Task] = {}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/attack-classes")
def attack_classes():
    return sorted(ATTACK_CLASS_PROMPTS.keys())


class GenerateRequest(BaseModel):
    attack_class: str
    llm_model_id: int
    target_context: str = ""


@app.post("/generate")
async def generate(req: GenerateRequest):
    system_prompt = ATTACK_CLASS_PROMPTS.get(req.attack_class)
    if system_prompt is None:
        raise HTTPException(status_code=400, detail=f"unknown attack_class, choose one of {sorted(ATTACK_CLASS_PROMPTS)}")

    llm_model = await control_client.get_llm_model(req.llm_model_id)
    user_prompt = "Generate one injection template now."
    if req.target_context:
        user_prompt += f"\n\nTarget context (tool names/schemas discovered on the tested agent):\n{req.target_context}"

    raw = await llm_client.call_chat_completion(llm_model, system_prompt, user_prompt)
    parsed = llm_client.parse_template_json(raw)
    parsed.setdefault("tags", [])
    parsed["tags"] = [*parsed["tags"], f"attack_class:{req.attack_class}", "generator:llm"]
    return await control_client.create_template(parsed)


class MutateRequest(BaseModel):
    template_id: int
    llm_model_id: int
    strategy_hint: str = "wrap using an encoding/obfuscation technique"
    count: int = 1


@app.post("/mutate")
async def mutate(req: MutateRequest):
    existing = await control_client.get_template(req.template_id)
    llm_model = await control_client.get_llm_model(req.llm_model_id)

    created = []
    for _ in range(req.count):
        user_prompt = MUTATION_PROMPT.replace("__EXISTING_TEMPLATE_JSON__", json.dumps(existing)).replace(
            "__STRATEGY_HINT__", req.strategy_hint
        )
        raw = await llm_client.call_chat_completion(llm_model, "", user_prompt)
        parsed = llm_client.parse_template_json(raw)
        parsed.setdefault("tags", [])
        parsed["tags"] = [*parsed["tags"], f"mutated_from:{existing['id']}", "generator:llm"]
        created.append(await control_client.create_template(parsed))
    return created


class AdaptRequest(BaseModel):
    campaign_id: int
    llm_model_id: int | None = None  # defaults to the campaign's generator_llm_model_id if not given


@app.post("/adapt")
async def adapt(req: AdaptRequest):
    campaign = await control_client.get_campaign(req.campaign_id)
    existing = await control_client.get_template(campaign["template_id"])

    llm_model_id = req.llm_model_id or campaign.get("generator_llm_model_id")
    if not llm_model_id:
        raise HTTPException(
            status_code=400,
            detail="no llm_model_id given and campaign has no generator_llm_model_id set",
        )
    llm_model = await control_client.get_llm_model(llm_model_id)
    recent_events = await control_client.list_events(req.campaign_id, success_detected=False, limit=10)

    user_prompt = ADAPT_PROMPT.replace("__EXISTING_TEMPLATE_JSON__", json.dumps(existing)).replace(
        "__RECENT_EVENTS_JSON__", json.dumps(recent_events)
    )
    raw = await llm_client.call_chat_completion(llm_model, "", user_prompt)
    parsed = llm_client.parse_template_json(raw)
    parsed.setdefault("tags", [])
    parsed["tags"] = [*parsed["tags"], f"adapted_from:{existing['id']}", f"campaign:{req.campaign_id}", "generator:llm"]
    return await control_client.create_template(parsed)


@app.post("/fuzz/{fuzz_run_id}/start")
async def start_fuzz(fuzz_run_id: int):
    fuzz_run = await control_client.get_fuzz_run(fuzz_run_id)
    if fuzz_run["status"] not in ("pending", "paused"):
        raise HTTPException(status_code=400, detail=f"fuzz run has status={fuzz_run['status']}, cannot start")

    base_campaign = await control_client.get_campaign(fuzz_run["base_campaign_id"])
    if not base_campaign.get("agent_config_id"):
        raise HTTPException(status_code=400, detail="base campaign has no agent_config_id set")
    if not base_campaign.get("interactor_llm_model_id"):
        raise HTTPException(status_code=400, detail="base campaign has no interactor_llm_model_id set")
    if not base_campaign.get("generator_llm_model_id") and not fuzz_run.get("judge_llm_model_id"):
        raise HTTPException(
            status_code=400,
            detail="need a generator_llm_model_id on the base campaign or a judge_llm_model_id on the fuzz run",
        )

    existing_task = _running_fuzz_tasks.get(fuzz_run_id)
    if existing_task and not existing_task.done():
        raise HTTPException(status_code=409, detail="fuzz run already has an active task")

    await control_client.update_fuzz_run(fuzz_run_id, {"status": "running"})
    task = asyncio.create_task(fuzz_engine.run_fuzz_iterations(fuzz_run_id))
    _running_fuzz_tasks[fuzz_run_id] = task
    return {"status": "running"}


@app.post("/fuzz/{fuzz_run_id}/stop")
async def stop_fuzz(fuzz_run_id: int):
    fuzz_run = await control_client.get_fuzz_run(fuzz_run_id)
    if fuzz_run["status"] == "running":
        await control_client.update_fuzz_run(fuzz_run_id, {"status": "stopped"})
    return {"status": "stopped"}


@app.post("/tree/{tree_run_id}/start")
async def start_tree(tree_run_id: int):
    tree_run = await control_client.get_tree_run(tree_run_id)
    if tree_run["status"] not in ("pending", "paused"):
        raise HTTPException(status_code=400, detail=f"tree run has status={tree_run['status']}, cannot start")

    base_campaign = await control_client.get_campaign(tree_run["base_campaign_id"])
    if base_campaign.get("status") != "active":
        raise HTTPException(
            status_code=400,
            detail="base campaign must be status=active -- unlike the one-shot engine, the tree "
            "engine walks it for real (proxy only ever logs/considers whichever campaign is "
            "currently active for a session_id)",
        )
    if not base_campaign.get("agent_config_id"):
        raise HTTPException(status_code=400, detail="base campaign has no agent_config_id set")
    if not base_campaign.get("interactor_llm_model_id"):
        raise HTTPException(status_code=400, detail="base campaign has no interactor_llm_model_id set")
    if not base_campaign.get("generator_llm_model_id") and not tree_run.get("judge_llm_model_id"):
        raise HTTPException(
            status_code=400,
            detail="need a generator_llm_model_id on the base campaign or a judge_llm_model_id on the tree run",
        )
    if base_campaign.get("injection_rate", 0.0) != 0.0 or base_campaign.get("inject_at_occurrence") is not None:
        raise HTTPException(
            status_code=400,
            detail="base campaign must have injection_rate=0.0 and inject_at_occurrence=None -- "
            "the backbone walk must be genuinely clean",
        )

    existing_task = _running_tree_tasks.get(tree_run_id)
    if existing_task and not existing_task.done():
        raise HTTPException(status_code=409, detail="tree run already has an active task")

    await control_client.update_tree_run(tree_run_id, {"status": "running"})
    task = asyncio.create_task(tree_engine.run_tree(tree_run_id))
    _running_tree_tasks[tree_run_id] = task
    return {"status": "running"}


@app.post("/tree/{tree_run_id}/stop")
async def stop_tree(tree_run_id: int):
    tree_run = await control_client.get_tree_run(tree_run_id)
    if tree_run["status"] == "running":
        await control_client.update_tree_run(tree_run_id, {"status": "stopped"})
    return {"status": "stopped"}
