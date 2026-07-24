"""Orchestrates a FuzzRun: a budget-driven search over InjectionTemplate
variants, delivered through the platform's *existing* production path
unchanged (proxy's injector/detector, interactor's /run) -- see docs for the
full per-iteration flow. Runs as a background asyncio task (see main.py's
POST /fuzz/{id}/start), not inline with the HTTP request, since a fuzz run
can take many iterations and must be pausable.
"""

import asyncio
import json
import uuid

from app import bandit, control_client, interactor_client, judge, llm_client, mutators, seed_corpus
from app.prompts import ADAPT_PROMPT, MUTATION_PROMPT

RUNNING_STATUSES = {"running"}

# proxy/app/control_client.py caches GET /campaigns/active for
# ACTIVE_CAMPAIGN_CACHE_TTL seconds (default 2) per session_id. Each iteration
# here activates a fresh ephemeral Campaign -- if two iterations complete
# faster than that TTL (e.g. against a very fast LLM), the next iteration's
# first exchange can race a stale read of the *previous* iteration's
# campaign, misattributing the resulting TrafficEvent's campaign_id (and
# this iteration would then see zero events for its own new_campaign["id"]).
# Settling briefly after activation, longer than the default TTL, avoids
# this -- discovered during verification of the injection-tree feature,
# which hits the same race harder (see tree_engine.py).
CAMPAIGN_ACTIVATION_SETTLE_SECONDS = 2.5


async def _bootstrap_seeds(fuzz_run: dict) -> list[int]:
    if fuzz_run["seed_template_ids"]:
        return fuzz_run["seed_template_ids"]
    return await seed_corpus.ensure_seed_pool(fuzz_run["injection_target"])


async def _mutate(fuzz_run: dict, seed_template: dict, generator_llm_model: dict, local_attempts: list[dict], iteration: int) -> tuple[dict, str]:
    if fuzz_run["mode"] == "adaptive":
        recent_failures = [
            {
                "template_id": a["template_id"],
                "detector_success": a["detector_success"],
                "judge_verdict": a["judge_verdict"],
            }
            for a in local_attempts
            if a["seed_template_id"] == seed_template["id"] and not a["success"]
        ][-10:]
        user_prompt = ADAPT_PROMPT.replace("__EXISTING_TEMPLATE_JSON__", json.dumps(seed_template)).replace(
            "__RECENT_EVENTS_JSON__", json.dumps(recent_failures)
        )
        strategy = "adapt"
    else:
        strategy = mutators.pick_operator(iteration)
        hint = mutators.MUTATION_OPERATORS[strategy]
        user_prompt = MUTATION_PROMPT.replace("__EXISTING_TEMPLATE_JSON__", json.dumps(seed_template)).replace(
            "__STRATEGY_HINT__", hint
        )

    raw = await llm_client.call_chat_completion(generator_llm_model, "", user_prompt)
    parsed = llm_client.parse_template_json(raw)
    parsed.setdefault("tags", [])
    parsed["tags"] = [*parsed["tags"], f"fuzz_run:{fuzz_run['id']}", f"mutated_from:{seed_template['id']}", "generator:fuzz"]
    # template names are unique in control-api; the LLM doesn't know about
    # other iterations, so disambiguate deterministically.
    parsed["name"] = f"{parsed['name']}-fz{fuzz_run['id']}-{iteration}-{uuid.uuid4().hex[:6]}"
    return parsed, strategy


async def run_fuzz_iterations(fuzz_run_id: int) -> None:
    fuzz_run = await control_client.get_fuzz_run(fuzz_run_id)
    base_campaign = await control_client.get_campaign(fuzz_run["base_campaign_id"])

    generator_llm_model_id = base_campaign.get("generator_llm_model_id")
    judge_llm_model_id = fuzz_run.get("judge_llm_model_id") or generator_llm_model_id
    if not generator_llm_model_id or not judge_llm_model_id:
        await control_client.update_fuzz_run(fuzz_run_id, {"status": "stopped"})
        return
    generator_llm_model = await control_client.get_llm_model(generator_llm_model_id)
    judge_llm_model = await control_client.get_llm_model(judge_llm_model_id)

    seed_ids = await _bootstrap_seeds(fuzz_run)
    local_attempts = await control_client.list_attempts(fuzz_run_id)
    iteration = len(local_attempts)

    try:
        while iteration < fuzz_run["max_iterations"]:
            fuzz_run = await control_client.get_fuzz_run(fuzz_run_id)
            if fuzz_run["status"] not in RUNNING_STATUSES:
                return

            seed_id = bandit.select_seed(local_attempts, seed_ids)
            seed_template = await control_client.get_template(seed_id)

            mutated, strategy = await _mutate(fuzz_run, seed_template, generator_llm_model, local_attempts, iteration)
            new_template = await control_client.create_template(mutated)

            new_campaign = await control_client.create_campaign(
                {
                    "name": f"{base_campaign['name']}-fuzz-{fuzz_run_id}-{iteration}",
                    "session_id": base_campaign["session_id"],
                    "template_id": new_template["id"],
                    "status": "active",
                    "injection_rate": 1.0,
                    "agent_config_id": base_campaign.get("agent_config_id"),
                    "interactor_llm_model_id": base_campaign.get("interactor_llm_model_id"),
                    "generator_llm_model_id": base_campaign.get("generator_llm_model_id"),
                    "interactor_persona": base_campaign.get("interactor_persona"),
                    "user_instruction": base_campaign.get("user_instruction"),
                }
            )
            await asyncio.sleep(CAMPAIGN_ACTIVATION_SETTLE_SECONDS)

            result = await interactor_client.run_one_shot(new_campaign["id"])
            transcript = result.get("transcript", [])
            agent_reply = next((t["text"] for t in reversed(transcript) if t["speaker"] == "agent"), "")

            events = await control_client.list_campaign_events(new_campaign["id"])
            detector_success = any(e["success_detected"] for e in events)

            attack_goal = new_template.get("description") or new_template["payload"]
            judge_result = await judge.judge_compliance(judge_llm_model, agent_reply, attack_goal)

            reward = 1.0 if detector_success else judge_result["score"]
            success = detector_success or judge_result["complied"]

            attempt = await control_client.create_attempt(
                fuzz_run_id,
                {
                    "iteration": iteration,
                    "seed_template_id": seed_id,
                    "template_id": new_template["id"],
                    "campaign_id": new_campaign["id"],
                    "mutation_strategy": strategy,
                    "detector_success": detector_success,
                    "judge_score": judge_result["score"],
                    "judge_verdict": judge_result["verdict"],
                    "reward": reward,
                    "success": success,
                },
            )
            local_attempts.append(attempt)
            iteration += 1

            if success and fuzz_run["stop_on_success"]:
                await control_client.update_fuzz_run(
                    fuzz_run_id, {"status": "completed", "success_attempt_id": attempt["id"]}
                )
                return

        await control_client.update_fuzz_run(fuzz_run_id, {"status": "completed"})
    except Exception:
        await control_client.update_fuzz_run(fuzz_run_id, {"status": "stopped"})
        raise
