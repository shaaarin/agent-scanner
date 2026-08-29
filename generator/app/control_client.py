import os

import httpx

CONTROL_API_URL = os.environ.get("CONTROL_API_URL", "http://control-api:8000")

_client = httpx.AsyncClient(base_url=CONTROL_API_URL, timeout=10.0)


async def get_llm_model(llm_model_id: int) -> dict:
    resp = await _client.get(f"/llm-models/{llm_model_id}")
    resp.raise_for_status()
    return resp.json()


async def get_template(template_id: int) -> dict:
    resp = await _client.get(f"/templates/{template_id}")
    resp.raise_for_status()
    return resp.json()


async def create_template(payload: dict) -> dict:
    resp = await _client.post("/templates", json=payload)
    resp.raise_for_status()
    return resp.json()


async def list_events(
    campaign_id: int, success_detected: bool = False, limit: int = 20
) -> list[dict]:
    resp = await _client.get(
        "/events",
        params={
            "campaign_id": campaign_id,
            "success_detected": success_detected,
            "limit": limit,
        },
    )
    resp.raise_for_status()
    return resp.json()


async def list_campaign_events(campaign_id: int, limit: int = 20) -> list[dict]:
    """Every event for one campaign regardless of success_detected -- unlike
    list_events above (which /adapt uses specifically for *unsuccessful*
    events), the fuzz engine needs both outcomes to compute its own reward.
    """
    resp = await _client.get(
        "/events", params={"campaign_id": campaign_id, "limit": limit}
    )
    resp.raise_for_status()
    return resp.json()


async def get_campaign(campaign_id: int) -> dict:
    resp = await _client.get(f"/campaigns/{campaign_id}")
    resp.raise_for_status()
    return resp.json()


async def list_templates() -> list[dict]:
    resp = await _client.get("/templates")
    resp.raise_for_status()
    return resp.json()


async def get_attack_prompt(attack_prompt_id: int) -> dict:
    resp = await _client.get(f"/attack-prompts/{attack_prompt_id}")
    resp.raise_for_status()
    return resp.json()


async def list_attack_prompts() -> list[dict]:
    resp = await _client.get("/attack-prompts")
    resp.raise_for_status()
    return resp.json()


async def get_fuzz_run(fuzz_run_id: int) -> dict:
    resp = await _client.get(f"/fuzz-runs/{fuzz_run_id}")
    resp.raise_for_status()
    return resp.json()


async def update_fuzz_run(fuzz_run_id: int, payload: dict) -> dict:
    resp = await _client.patch(f"/fuzz-runs/{fuzz_run_id}", json=payload)
    resp.raise_for_status()
    return resp.json()


async def create_attempt(fuzz_run_id: int, payload: dict) -> dict:
    resp = await _client.post(f"/fuzz-runs/{fuzz_run_id}/attempts", json=payload)
    resp.raise_for_status()
    return resp.json()


async def list_attempts(fuzz_run_id: int) -> list[dict]:
    # limit=1000 (the API's max) matters for resume correctness: the fuzz
    # engine derives its iteration counter from len() of this list, so the
    # default limit of 100 would duplicate iterations on a >100-attempt run.
    resp = await _client.get(
        f"/fuzz-runs/{fuzz_run_id}/attempts", params={"limit": 1000}
    )
    resp.raise_for_status()
    return resp.json()


async def get_tree_run(tree_run_id: int) -> dict:
    resp = await _client.get(f"/tree-runs/{tree_run_id}")
    resp.raise_for_status()
    return resp.json()


async def update_tree_run(tree_run_id: int, payload: dict) -> dict:
    resp = await _client.patch(f"/tree-runs/{tree_run_id}", json=payload)
    resp.raise_for_status()
    return resp.json()


async def create_node(tree_run_id: int, payload: dict) -> dict:
    resp = await _client.post(f"/tree-runs/{tree_run_id}/nodes", json=payload)
    resp.raise_for_status()
    return resp.json()


async def list_nodes(tree_run_id: int) -> list[dict]:
    resp = await _client.get(f"/tree-runs/{tree_run_id}/nodes")
    resp.raise_for_status()
    return resp.json()


async def create_probe(tree_run_id: int, payload: dict) -> dict:
    resp = await _client.post(f"/tree-runs/{tree_run_id}/probes", json=payload)
    resp.raise_for_status()
    return resp.json()


async def list_probes(tree_run_id: int) -> list[dict]:
    resp = await _client.get(f"/tree-runs/{tree_run_id}/probes", params={"limit": 1000})
    resp.raise_for_status()
    return resp.json()
