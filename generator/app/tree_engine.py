"""Orchestrates a TreeRun: one real, clean external exchange (the backbone,
shared with any FuzzRun on the same Campaign -- see backbone.py) discovers a
sequence of tool-result checkpoints, then each checkpoint is fuzzed by
mutating its captured message array and sending it as a single direct
chat-completion call to the tested agent's own LLM (see direct_llm.py) --
no ephemeral Campaign, no `interactor`, no `proxy` involved per attempt.
Runs as a background asyncio task (see main.py's POST /tree/{id}/start).

This works because a *single* external exchange (one interactor <-> agent
call) can itself contain several internal tool calls -- proxy intercepts
every one of them regardless -- so checkpoint discovery
(generator/app/checkpoints.py) already reads control-api's own TrafficEvent
log for a campaign rather than depending on how many external turns it took.
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
    checkpoints,
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
EVENTS_LIMIT = 1000
MAX_CONSECUTIVE_ERRORS = 3


async def _is_running(tree_run_id: int) -> bool:
    tree_run = await control_client.get_tree_run(tree_run_id)
    return tree_run["status"] in RUNNING_STATUSES


async def _mutate(
    tree_run: dict,
    seed_template: dict,
    generator_llm_model: dict,
    past_probes: list[dict],
    attempt_index: int,
) -> tuple[dict, str]:
    if tree_run["mode"] == "adaptive":
        recent_failures = [
            {
                "template_id": p["template_id"],
                "detector_success": p["detector_success"],
                "judge_verdict": p["judge_verdict"],
            }
            for p in past_probes
            if p["seed_template_id"] == seed_template["id"] and not p["success"]
        ][-10:]
        user_prompt = ADAPT_PROMPT.replace(
            "__EXISTING_TEMPLATE_JSON__", json.dumps(seed_template)
        ).replace("__RECENT_EVENTS_JSON__", json.dumps(recent_failures))
        strategy = "adapt"
    else:
        strategy = mutators.pick_operator(attempt_index)
        hint = mutators.MUTATION_OPERATORS[strategy]
        user_prompt = MUTATION_PROMPT.replace(
            "__EXISTING_TEMPLATE_JSON__", json.dumps(seed_template)
        ).replace("__STRATEGY_HINT__", hint)

    raw = await llm_client.call_chat_completion(generator_llm_model, "", user_prompt)
    parsed = llm_client.parse_template_json(raw)
    parsed.setdefault("tags", [])
    parsed["tags"] = [
        *parsed["tags"],
        f"tree_run:{tree_run['id']}",
        f"mutated_from:{seed_template['id']}",
        "generator:tree",
    ]
    parsed["name"] = (
        f"{parsed['name']}-tree{tree_run['id']}-{attempt_index}-{uuid.uuid4().hex[:6]}"
    )
    parsed["target"] = (
        "tool_result"  # this engine only ever targets tool_result, regardless of what the mutation LLM proposes
    )
    return parsed, strategy


def _tool_names(response_body: dict) -> set[str]:
    return {
        tc.get("function", {}).get("name", "")
        for tc in response_helpers.iter_tool_calls(response_body)
    }


async def _probe_checkpoint(
    tree_run: dict,
    checkpoint: dict,
    credential: dict,
    generator_llm_model: dict,
    judge_llm_model: dict,
    seed_ids: list[int],
    attempt_index: int,
) -> dict:
    tree_run_id = tree_run["id"]
    past_probes = await control_client.list_probes(tree_run_id)
    seed_id = bandit.select_seed(past_probes, seed_ids)
    seed_template = await control_client.get_template(seed_id)

    mutated, strategy = await _mutate(
        tree_run, seed_template, generator_llm_model, past_probes, attempt_index
    )
    new_template = await control_client.create_template(mutated)

    mutated_body = copy.deepcopy(checkpoint["request_body"])
    injected = injection_apply.apply_injection(
        mutated_body,
        new_template["target"],
        new_template["mode"],
        new_template["payload"],
    )
    if not injected:
        # No tool message to mutate -- sending the body anyway would probe a
        # clean (uninjected) conversation and could score a false judge
        # success. Retry with a fresh mutation instead.
        raise RuntimeError(
            f"injection found no {new_template['target']} message in checkpoint "
            f"{checkpoint['occurrence_index']}'s request body"
        )
    response_body = await direct_llm.call_raw_completion(credential, mutated_body)

    detector_success, _detail = success_detector.evaluate(
        mutated_body,
        response_body,
        new_template["success_indicator"],
        new_template["success_indicator_field"],
    )
    judge_score, judge_verdict, complied = 0.0, "", False
    if not detector_success:
        agent_reply = response_helpers.get_response_text(response_body)
        judge_result = await judge.judge_compliance(
            judge_llm_model,
            agent_reply,
            new_template.get("description") or new_template["payload"],
        )
        judge_score, judge_verdict, complied = (
            judge_result["score"],
            judge_result["verdict"],
            judge_result["complied"],
        )

    success = detector_success or complied

    return {
        "checkpoint_occurrence": checkpoint["occurrence_index"],
        "attempt_index": attempt_index,
        "seed_template_id": seed_id,
        "template_id": new_template["id"],
        "tool_name": checkpoint["tool_name"],
        "original_tool_result": checkpoint["tool_result"],
        "injected_tool_result": new_template["payload"],
        "trajectory": [{"request": mutated_body, "response": response_body}],
        "stopped_reason": "success" if success else "no_success",
        "detector_success": detector_success,
        "judge_score": judge_score,
        "judge_verdict": judge_verdict,
        "reward": 1.0 if detector_success else judge_score,
        "success": success,
        "probe_tool_names": _tool_names(
            response_body
        ),  # consumed by run_tree, not stored as-is
    }


async def run_tree(tree_run_id: int) -> None:
    tree_run = await control_client.get_tree_run(tree_run_id)
    base_campaign = await control_client.get_campaign(tree_run["base_campaign_id"])

    generator_llm_model_id = base_campaign.get("generator_llm_model_id")
    judge_llm_model_id = tree_run.get("judge_llm_model_id") or generator_llm_model_id
    if (
        not generator_llm_model_id
        or not judge_llm_model_id
        or not base_campaign.get("agent_config_id")
    ):
        await control_client.update_tree_run(tree_run_id, {"status": "stopped"})
        return
    try:
        generator_llm_model = await control_client.get_llm_model(generator_llm_model_id)
        judge_llm_model = await control_client.get_llm_model(judge_llm_model_id)

        # Priority: explicit seed_template_ids + freshly LLM-generated seeds from
        # the attack_prompt_ids checklist (both, if given) -- falls back to the
        # built-in seed_corpus only if neither is set, preserving the
        # zero-config default (mirrors fuzz_engine.py's _bootstrap_seeds).
        seed_ids = list(tree_run["seed_template_ids"])
        if tree_run["attack_prompt_ids"]:
            seed_ids += await attack_prompt_seeds.generate_seeds_from_attack_prompts(
                tree_run["attack_prompt_ids"],
                generator_llm_model,
                f"tree_run:{tree_run_id}",
                "tool_result",
            )
        if not seed_ids:
            seed_ids = await seed_corpus.ensure_seed_pool("tool_result")

        backbone_requests = await backbone.ensure_backbone(base_campaign)
        if not backbone_requests:
            raise RuntimeError(
                "backbone exchange captured no request TrafficEvents -- check that the "
                "campaign was active and the agent's LLM client speaks OpenAI-wire "
                "/chat/completions before starting the run"
            )
        if not await _is_running(tree_run_id):
            return
        credential = direct_llm.resolve_target_credential(backbone_requests[0])

        # Scope to the same thread `backbone_requests` was picked from --
        # list_campaign_events would return every thread the Campaign ever
        # captured, and checkpoints_from_events assumes one coherent,
        # monotonically-growing conversation (see conversation_threads.py).
        backbone_flow_ids = {r["flow_id"] for r in backbone_requests}
        campaign_events = await control_client.list_campaign_events(
            tree_run["base_campaign_id"], limit=EVENTS_LIMIT
        )
        backbone_events = [
            e for e in campaign_events if e["flow_id"] in backbone_flow_ids
        ]
        all_checkpoints = checkpoints.checkpoints_from_events(backbone_events)
        if tree_run["max_checkpoints"]:
            all_checkpoints = all_checkpoints[: tree_run["max_checkpoints"]]

        # Ground truth for the divergence comparison: what the real (clean)
        # backbone actually decided to do -- which tool(s), if any -- right
        # after seeing each checkpoint's tool result. Each checkpoint's
        # request has a paired response TrafficEvent (same flow_id) holding
        # exactly that decision.
        responses_by_flow_id: dict[str, dict] = {}
        for event in backbone_events:
            if event["direction"] != "response":
                continue
            try:
                responses_by_flow_id[event["flow_id"]] = json.loads(
                    event["raw_excerpt"]
                )
            except (json.JSONDecodeError, TypeError):
                continue
        backbone_tool_names_by_checkpoint = {
            checkpoint["occurrence_index"]: _tool_names(
                responses_by_flow_id.get(checkpoint["flow_id"], {})
            )
            for checkpoint in all_checkpoints
        }

        consecutive_errors = 0
        for checkpoint in all_checkpoints:
            if not await _is_running(tree_run_id):
                return

            done_attempts = [
                p
                for p in await control_client.list_probes(tree_run_id)
                if p["checkpoint_occurrence"] == checkpoint["occurrence_index"]
            ]
            if any(p["success"] for p in done_attempts):
                continue  # already found a working variant at this checkpoint

            for attempt_index in range(
                len(done_attempts), tree_run["attempts_per_checkpoint"]
            ):
                if not await _is_running(tree_run_id):
                    return

                # Same error model as fuzz_engine.py: one failed probe
                # (mutator LLM hiccup, provider 429/timeout, ...) skips the
                # attempt and retries; only MAX_CONSECUTIVE_ERRORS in a row
                # stop the whole run.
                try:
                    probe_result = await _probe_checkpoint(
                        tree_run,
                        checkpoint,
                        credential,
                        generator_llm_model,
                        judge_llm_model,
                        seed_ids,
                        attempt_index,
                    )
                except Exception:
                    consecutive_errors += 1
                    traceback.print_exc()
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        print(
                            f"[tree_engine] {consecutive_errors} consecutive failed probes, "
                            f"stopping run {tree_run_id}"
                        )
                        await control_client.update_tree_run(
                            tree_run_id, {"status": "stopped"}
                        )
                        return
                    await asyncio.sleep(1.0 * consecutive_errors)
                    continue
                consecutive_errors = 0
                probe_tool_names = probe_result.pop("probe_tool_names")
                backbone_tool_names = backbone_tool_names_by_checkpoint.get(
                    checkpoint["occurrence_index"], set()
                )
                diverged = probe_tool_names != backbone_tool_names
                probe_result["diverged_from_backbone"] = diverged
                probe_result["divergence_detail"] = (
                    f"backbone called {sorted(backbone_tool_names)} next, "
                    f"this attempt called {sorted(probe_tool_names)} next"
                )

                await control_client.create_probe(tree_run_id, probe_result)

                if probe_result["success"]:
                    break

        await control_client.update_tree_run(tree_run_id, {"status": "completed"})
    except Exception:
        await control_client.update_tree_run(tree_run_id, {"status": "stopped"})
        raise
