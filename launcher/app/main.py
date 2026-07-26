from urllib.parse import urlparse, urlunparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import build, ca_manager, control_client, env_discovery, namespace_manager, pod_manager, repo_inspect
from app.naming import namespace_for_session

app = FastAPI(title="agent-scanner launcher")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


class LaunchRequest(BaseModel):
    campaign_id: int


class RepoBranchesRequest(BaseModel):
    git_repo_url: str
    git_access_token: str | None = None


class RepoInspectRequest(BaseModel):
    git_repo_url: str
    git_ref: str
    git_access_token: str | None = None


@app.post("/repo/branches")
def repo_branches(req: RepoBranchesRequest):
    """Lists remote branches for the AgentConfigs creation wizard's step 1
    -- before any AgentConfig exists, so this takes the raw url/token
    directly rather than an agent_config_id.
    """
    try:
        return {"branches": repo_inspect.list_branches(req.git_repo_url, req.git_access_token)}
    except repo_inspect.RepoInspectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/repo/inspect")
def repo_inspect_route(req: RepoInspectRequest):
    """Discovers Dockerfile/.env.example candidates on a chosen branch for
    the wizard's step 2 -- every found .env.example is parsed immediately.
    """
    try:
        return repo_inspect.inspect_repo(req.git_repo_url, req.git_ref, req.git_access_token)
    except repo_inspect.RepoInspectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _patch_reachable_url(agent_config: dict, address: str) -> None:
    """After the agent's Pod+Service exist, points AgentConfig.api_config.url
    or .langgraph_config.base_url at the real, interactor-reachable address
    (replacing scheme/host/port only -- api_config.url's own path, if any,
    is preserved). No-op for cli/none modes, which don't need a network
    address at all.
    """
    mode = agent_config.get("interaction_mode")
    if mode == "langgraph":
        langgraph_config = dict(agent_config.get("langgraph_config") or {})
        langgraph_config["base_url"] = address
        control_client.update_agent_config(agent_config["id"], {"langgraph_config": langgraph_config})
    elif mode == "api":
        api_config = dict(agent_config.get("api_config") or {})
        existing = urlparse(api_config.get("url") or "")
        new_host = urlparse(address)
        api_config["url"] = urlunparse(new_host._replace(path=existing.path, query=existing.query))
        control_client.update_agent_config(agent_config["id"], {"api_config": api_config})


@app.post("/launch")
def launch(req: LaunchRequest):
    """Clone -> read env_example_path (if set) to auto-fill missing
    env_vars with the repo's own declared defaults -> build dockerfile_path
    via Kaniko -> run the resulting image with env_vars, exposing api_port
    (if set) via an auto-created NodePort Service and patching the
    resulting reachable address into the AgentConfig's interaction config.
    Blocks for the duration of the build -- see app/build.py's docstring.
    """
    campaign = control_client.get_campaign(req.campaign_id)
    if not campaign.get("agent_config_id"):
        raise HTTPException(status_code=400, detail="campaign has no agent_config_id set")
    agent_config = control_client.get_agent_config(campaign["agent_config_id"])

    namespace = namespace_for_session(campaign["session_id"])
    namespace_manager.ensure_namespace(namespace)
    ca_manager.ensure_ca_secret_in_namespace(namespace)

    if agent_config.get("env_example_path"):
        discovered = env_discovery.discover_env_defaults(
            agent_config["git_repo_url"],
            agent_config["git_ref"],
            agent_config["env_example_path"],
            agent_config.get("git_access_token"),
        )
        merged_env = env_discovery.merge_env_defaults(agent_config.get("env_vars", {}), discovered)
        if merged_env != agent_config.get("env_vars", {}):
            agent_config = control_client.update_agent_config(agent_config["id"], {"env_vars": merged_env})

    try:
        job_name, image = build.run_build(namespace, agent_config)
    except build.BuildError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    pod_name = pod_manager.launch_pod(namespace, agent_config, campaign["session_id"], image)
    node_port = pod_manager.ensure_agent_service(namespace, agent_config)

    if node_port:
        node = pod_manager.node_address()
        if node:
            _patch_reachable_url(agent_config, f"http://{node}:{node_port}")

    control_client.update_campaign(
        req.campaign_id,
        {
            "agent_namespace": namespace,
            "agent_pod_name": pod_name,
            "build_job_name": job_name,
            "built_image": image,
        },
    )
    return {
        "namespace": namespace,
        "pod_name": pod_name,
        "build_job_name": job_name,
        "built_image": image,
        "node_port": node_port,
        "status": pod_manager.pod_status(namespace, pod_name),
    }


@app.post("/stop/{campaign_id}")
def stop(campaign_id: int):
    campaign = control_client.get_campaign(campaign_id)
    if not campaign.get("agent_namespace"):
        raise HTTPException(status_code=400, detail="no launched agent for this campaign")

    namespace_manager.delete_namespace(campaign["agent_namespace"])
    control_client.update_campaign(
        campaign_id,
        {"agent_namespace": None, "agent_pod_name": None, "build_job_name": None, "built_image": None},
    )
    return {"stopped": True}


@app.get("/status/{campaign_id}")
def status(campaign_id: int):
    campaign = control_client.get_campaign(campaign_id)
    if not campaign.get("agent_pod_name"):
        return {"status": "not_launched"}
    return {
        "status": pod_manager.pod_status(campaign["agent_namespace"], campaign["agent_pod_name"]),
        "namespace": campaign["agent_namespace"],
        "pod_name": campaign["agent_pod_name"],
        "built_image": campaign.get("built_image"),
    }
