import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import control_client, fuzz_engine, llm_client, tree_engine
from app.prompts import MUTATION_PROMPT, RESPONSE_SHAPE

app = FastAPI(title="agent-scanner attack generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_running_fuzz_tasks: dict[int, asyncio.Task] = {}
_running_tree_tasks: dict[int, asyncio.Task] = {}


@app.get("/health")
def health():
    return {"status": "ok"}


class GenerateRequest(BaseModel):
    attack_prompt_id: int
    llm_model_id: int
    target_context: str = ""


@app.post("/generate")
async def generate(req: GenerateRequest):
    attack_prompt = await control_client.get_attack_prompt(req.attack_prompt_id)
    system_prompt = f"{attack_prompt['system_prompt']}\n\n{RESPONSE_SHAPE}"

    llm_model = await control_client.get_llm_model(req.llm_model_id)
    user_prompt = "Generate one injection template now."
    if req.target_context:
        user_prompt += f"\n\nTarget context (tool names/schemas discovered on the tested agent):\n{req.target_context}"

    raw = await llm_client.call_chat_completion(llm_model, system_prompt, user_prompt)
    parsed = llm_client.parse_template_json(raw)
    parsed.setdefault("tags", [])
    parsed["tags"] = [*parsed["tags"], f"attack_prompt:{req.attack_prompt_id}", "generator:llm"]
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


def _validate_base_campaign(base_campaign: dict, judge_llm_model_id: int | None) -> None:
    """Shared preflight for /fuzz/start and /tree/start: both engines now
    share the same one-honest-baseline-then-direct-LLM-calls delivery (see
    backbone.py/direct_llm.py), so both need the same things from the base
    campaign up front rather than failing async mid-run. Credential
    resolvability can't be preflighted here anymore -- the credential now
    comes from what the honest baseline exchange itself captures (see
    direct_llm.py), which doesn't exist yet at this point; a genuinely
    missing capture surfaces as a normal run failure (status -> stopped)
    inside run_fuzz_iterations/run_tree instead.
    """
    if base_campaign.get("status") != "active":
        raise HTTPException(
            status_code=400,
            detail="base campaign must be status=active -- the one honest baseline exchange is "
            "driven for real, and proxy only logs traffic against whichever campaign is "
            "currently active for a session_id",
        )
    if not base_campaign.get("agent_config_id"):
        raise HTTPException(status_code=400, detail="base campaign has no agent_config_id set")
    if not base_campaign.get("interactor_llm_model_id"):
        raise HTTPException(status_code=400, detail="base campaign has no interactor_llm_model_id set")
    if not base_campaign.get("generator_llm_model_id") and not judge_llm_model_id:
        raise HTTPException(
            status_code=400,
            detail="need a generator_llm_model_id on the base campaign or a judge_llm_model_id on the run",
        )


@app.post("/fuzz/{fuzz_run_id}/start")
async def start_fuzz(fuzz_run_id: int):
    fuzz_run = await control_client.get_fuzz_run(fuzz_run_id)
    if fuzz_run["status"] not in ("pending", "paused"):
        raise HTTPException(status_code=400, detail=f"fuzz run has status={fuzz_run['status']}, cannot start")

    base_campaign = await control_client.get_campaign(fuzz_run["base_campaign_id"])
    _validate_base_campaign(base_campaign, fuzz_run.get("judge_llm_model_id"))

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
    _validate_base_campaign(base_campaign, tree_run.get("judge_llm_model_id"))

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
