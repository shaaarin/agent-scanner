"""Orchestrates a FuzzRun: a budget-driven search over InjectionTemplate
variants against the direct/user_message target. Every attempt is a direct
chat-completion call against the tested agent's own LLM (see
generator/app/direct_llm.py) with a mutated copy of the one honest baseline
exchange's first captured message array (see generator/app/backbone.py) --
no ephemeral Campaign, no `interactor`, no `proxy` involved per attempt.
Runs as a background asyncio task (see main.py's POST /fuzz/{id}/start), not
inline with the HTTP request, since a fuzz run can take many iterations and
must be pausable.

Error model: a single failed attempt (mutator LLM returned invalid JSON,
provider 429/timeout, ...) skips that iteration and retries with a fresh
mutation; only MAX_CONSECUTIVE_ERRORS failures in a row stop the run. A run
stopped this way (or by the user) can be restarted later -- the engine
resumes from this run's already-recorded attempts.
"""

import asyncio
import copy
import json
import traceback
import uuid

from app import (
    attack_prompt_seeds,
    backbone,
    bandit,
    control_client,
    direct_llm,
    injection_apply,
    judge,
    llm_client,
    mutators,
    response_helpers,
    seed_corpus,
    success_detector,
)
from app.prompts import ADAPT_PROMPT, MUTATION_PROMPT

RUNNING_STATUSES = {"running"}
MAX_CONSECUTIVE_ERRORS = 3


async def _bootstrap_seeds(fuzz_run: dict, generator_llm_model: dict) -> list[int]:
    """Priority: explicit seed_template_ids + freshly LLM-generated seeds from
    the attack_prompt_ids checklist (both, if given) -- falls back to the
    built-in seed_corpus only if neither is set, preserving the zero-config
    default.
    """
    seed_ids = list(fuzz_run["seed_template_ids"])
    if fuzz_run["attack_prompt_ids"]:
        seed_ids += await attack_prompt_seeds.generate_seeds_from_attack_prompts(
            fuzz_run["attack_prompt_ids"],
            generator_llm_model,
            f"fuzz_run:{fuzz_run['id']}",
            fuzz_run["injection_target"],
        )
    if seed_ids:
        return seed_ids
    return await seed_corpus.ensure_seed_pool(fuzz_run["injection_target"])


async def _mutate(
    fuzz_run: dict,
    seed_template: dict,
    generator_llm_model: dict,
    local_attempts: list[dict],
    iteration: int,
) -> tuple[dict, str]:
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
        user_prompt = ADAPT_PROMPT.replace(
            "__EXISTING_TEMPLATE_JSON__", json.dumps(seed_template)
        ).replace("__RECENT_EVENTS_JSON__", json.dumps(recent_failures))
        strategy = "adapt"
    else:
        strategy = mutators.pick_operator(iteration)
        hint = mutators.MUTATION_OPERATORS[strategy]
        user_prompt = MUTATION_PROMPT.replace(
            "__EXISTING_TEMPLATE_JSON__", json.dumps(seed_template)
        ).replace("__STRATEGY_HINT__", hint)

    raw = await llm_client.call_chat_completion(generator_llm_model, "", user_prompt)
    parsed = llm_client.parse_template_json(raw)
    # This engine only ever delivers into this run's injection_target
    # (user_message), regardless of what the mutation LLM proposes -- same
    # reasoning as tree_engine.py's tool_result forcing, and what
    # docs/architecture.md already documents.
    parsed["target"] = fuzz_run["injection_target"]
    parsed.setdefault("tags", [])
    parsed["tags"] = [
        *parsed["tags"],
        f"fuzz_run:{fuzz_run['id']}",
        f"mutated_from:{seed_template['id']}",
        "generator:fuzz",
    ]
    # template names are unique in control-api; the LLM doesn't know about
    # other iterations, so disambiguate deterministically.
    parsed["name"] = (
        f"{parsed['name']}-fz{fuzz_run['id']}-{iteration}-{uuid.uuid4().hex[:6]}"
    )
    return parsed, strategy


async def run_fuzz_iterations(fuzz_run_id: int) -> None:
    fuzz_run = await control_client.get_fuzz_run(fuzz_run_id)
    base_campaign = await control_client.get_campaign(fuzz_run["base_campaign_id"])

    generator_llm_model_id = base_campaign.get("generator_llm_model_id")
    judge_llm_model_id = fuzz_run.get("judge_llm_model_id") or generator_llm_model_id
    if (
        not generator_llm_model_id
        or not judge_llm_model_id
        or not base_campaign.get("agent_config_id")
    ):
        await control_client.update_fuzz_run(fuzz_run_id, {"status": "stopped"})
        return
    try:
        generator_llm_model = await control_client.get_llm_model(generator_llm_model_id)
        judge_llm_model = await control_client.get_llm_model(judge_llm_model_id)

        backbone_requests = await backbone.ensure_backbone(base_campaign)
        if not backbone_requests:
            raise RuntimeError(
                "backbone exchange captured no request TrafficEvents -- check that the "
                "campaign was active and the agent's LLM client speaks OpenAI-wire "
                "/chat/completions before starting the run"
            )
        direct_checkpoint_body = json.loads(backbone_requests[0]["raw_excerpt"])
        credential = direct_llm.resolve_target_credential(backbone_requests[0])

        seed_ids = await _bootstrap_seeds(fuzz_run, generator_llm_model)
        local_attempts = await control_client.list_attempts(fuzz_run_id)
        iteration = len(local_attempts)
        consecutive_errors = 0

        while iteration < fuzz_run["max_iterations"]:
            fuzz_run = await control_client.get_fuzz_run(fuzz_run_id)
            if fuzz_run["status"] not in RUNNING_STATUSES:
                return

            try:
                seed_id = bandit.select_seed(local_attempts, seed_ids)
                seed_template = await control_client.get_template(seed_id)

                mutated, strategy = await _mutate(
                    fuzz_run,
                    seed_template,
                    generator_llm_model,
                    local_attempts,
                    iteration,
                )
                new_template = await control_client.create_template(mutated)

                mutated_body = copy.deepcopy(direct_checkpoint_body)
                injected = injection_apply.apply_injection(
                    mutated_body,
                    new_template["target"],
                    new_template["mode"],
                    new_template["payload"],
                )
                if not injected:
                    # No matching message to mutate -- sending the body anyway
                    # would waste the iteration on an uninjected (clean) call
                    # and could even score a false judge success. Retry with a
                    # fresh mutation instead.
                    raise RuntimeError(
                        f"injection found no {new_template['target']} message in the backbone request body"
                    )
                response_body = await direct_llm.call_raw_completion(
                    credential, mutated_body
                )

                detector_success, _detail = success_detector.evaluate(
                    mutated_body,
                    response_body,
                    new_template["success_indicator"],
                    new_template["success_indicator_field"],
                )

                judge_score, judge_verdict, complied = 0.0, "", False
                if not detector_success:
                    # detector-confirmed successes need no judge (mirrors
                    # tree_engine.py). And a dead/flaky judge must not discard
                    # an otherwise-complete attempt: degrade to a detector-only
                    # verdict rather than failing the iteration.
                    agent_reply = response_helpers.get_response_text(response_body)
                    attack_goal = (
                        new_template.get("description") or new_template["payload"]
                    )
                    try:
                        judge_result = await judge.judge_compliance(
                            judge_llm_model, agent_reply, attack_goal
                        )
                        judge_score, judge_verdict, complied = (
                            judge_result["score"],
                            judge_result["verdict"],
                            judge_result["complied"],
                        )
                    except Exception as exc:
                        print(
                            f"[fuzz_engine] judge call failed (detector-only verdict): {exc}"
                        )

                reward = 1.0 if detector_success else judge_score
                success = detector_success or complied
            except Exception:
                consecutive_errors += 1
                traceback.print_exc()
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(
                        f"[fuzz_engine] {consecutive_errors} consecutive failed iterations, stopping run {fuzz_run_id}"
                    )
                    await control_client.update_fuzz_run(
                        fuzz_run_id, {"status": "stopped"}
                    )
                    return
                await asyncio.sleep(1.0 * consecutive_errors)
                continue
            consecutive_errors = 0

            attempt = await control_client.create_attempt(
                fuzz_run_id,
                {
                    "iteration": iteration,
                    "seed_template_id": seed_id,
                    "template_id": new_template["id"],
                    "mutation_strategy": strategy,
                    "detector_success": detector_success,
                    "judge_score": judge_score,
                    "judge_verdict": judge_verdict,
                    "reward": reward,
                    "success": success,
                },
            )
            local_attempts.append(attempt)
            iteration += 1

            if success and fuzz_run["stop_on_success"]:
                await control_client.update_fuzz_run(
                    fuzz_run_id,
                    {"status": "completed", "success_attempt_id": attempt["id"]},
                )
                return

        await control_client.update_fuzz_run(fuzz_run_id, {"status": "completed"})
    except Exception:
        await control_client.update_fuzz_run(fuzz_run_id, {"status": "stopped"})
        raise
