"""Orchestrates a TreeRun: walks one real, clean conversation (the backbone)
forward via interactor's resumable /session/turn primitive, then fuzzes each
tool-result checkpoint the backbone actually produced (bandit-selected seed +
mutation, same machinery as the one-shot engine's fuzz_engine.py) -- see
docs/architecture.md's "Injection tree" section. Runs as a background asyncio
task (see main.py's POST /tree/{id}/start).

Delivery reuses the existing production path unchanged: each checkpoint
attempt creates a fresh ephemeral Campaign with `inject_at_occurrence` set
(proxy's new occurrence counter, see proxy/addon.py) and drives it via
interactor -- no per-turn campaign swapping needed, proxy injects exactly
once, automatically, however many external turns it takes to reach that
occurrence.
"""

import asyncio
import json
import uuid

from app import bandit, checkpoints, control_client, interactor_client, judge, llm_client, mutators, seed_corpus
from app.prompts import ADAPT_PROMPT, MUTATION_PROMPT

RUNNING_STATUSES = {"running"}
EVENTS_LIMIT = 1000

# proxy/app/control_client.py caches GET /campaigns/active for
# ACTIVE_CAMPAIGN_CACHE_TTL seconds (default 2) per session_id. Since this
# engine activates a fresh ephemeral Campaign per attempt -- much faster than
# that TTL when driven by a fast LLM -- a probe's first turn can otherwise
# race a stale read of the *previous* attempt's (already-injected) campaign,
# corrupting occurrence counting. Settling briefly after activation, longer
# than the default TTL, avoids this; harmless in real usage where an actual
# LLM call already takes longer than this anyway.
CAMPAIGN_ACTIVATION_SETTLE_SECONDS = 2.5


async def _is_running(tree_run_id: int) -> bool:
    tree_run = await control_client.get_tree_run(tree_run_id)
    return tree_run["status"] in RUNNING_STATUSES


async def _drive_turns(campaign_id: int, scripted_messages: list[str], max_turns: int, tree_run_id: int, on_turn=None):
    """Drives up to max_turns turns on campaign_id, starting a fresh session.
    For turn i, replays scripted_messages[i] verbatim if available, otherwise
    lets interactor's own persona LLM decide (message=None) -- covers both
    Phase A (no script at all) and Phase B (replay the backbone's script,
    then let persona continue if the poisoned run needs more turns, i.e. a
    human-in-the-loop follow-up, than the backbone did).

    Stops when `on_turn` (if given) reports success, when a turn adds no new
    tool-result events (the simplest available "the agent believes it's
    done" signal), when the TreeRun is stopped externally, or at max_turns.
    """
    session_token: str | None = None
    transcript: list[dict] = []
    turns: list[dict] = []
    prev_checkpoint_count = 0

    for i in range(max_turns):
        if not await _is_running(tree_run_id):
            return turns, "stopped"

        message = scripted_messages[i] if i < len(scripted_messages) else None
        result = await interactor_client.session_turn(campaign_id, session_token, message, transcript)
        session_token = result["session_token"]
        transcript.append({"speaker": "interactor", "text": result["message_sent"]})
        transcript.append({"speaker": "agent", "text": result["reply"]})
        turns.append({"turn_index": i, "message_sent": result["message_sent"], "reply": result["reply"]})

        events = await control_client.list_campaign_events(campaign_id, limit=EVENTS_LIMIT)
        checkpoint_count = len(checkpoints.checkpoints_from_events(events))

        if on_turn is not None and await on_turn(result["reply"], events):
            return turns, "success"

        # Only apply the "no new tool activity -> probably done" heuristic
        # once we're off-script (persona deciding freely): while replaying a
        # known script (message is not None), trust it -- a quiet turn there
        # just means that particular turn had no tool call yet, not that the
        # conversation is over.
        if message is None:
            if checkpoint_count == prev_checkpoint_count:
                return turns, "natural_end"
        prev_checkpoint_count = checkpoint_count

    return turns, "budget"


async def _mutate(tree_run: dict, seed_template: dict, generator_llm_model: dict, past_probes: list[dict], attempt_index: int) -> tuple[dict, str]:
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
        user_prompt = ADAPT_PROMPT.replace("__EXISTING_TEMPLATE_JSON__", json.dumps(seed_template)).replace(
            "__RECENT_EVENTS_JSON__", json.dumps(recent_failures)
        )
        strategy = "adapt"
    else:
        strategy = mutators.pick_operator(attempt_index)
        hint = mutators.MUTATION_OPERATORS[strategy]
        user_prompt = MUTATION_PROMPT.replace("__EXISTING_TEMPLATE_JSON__", json.dumps(seed_template)).replace(
            "__STRATEGY_HINT__", hint
        )

    raw = await llm_client.call_chat_completion(generator_llm_model, "", user_prompt)
    parsed = llm_client.parse_template_json(raw)
    parsed.setdefault("tags", [])
    parsed["tags"] = [*parsed["tags"], f"tree_run:{tree_run['id']}", f"mutated_from:{seed_template['id']}", "generator:tree"]
    parsed["name"] = f"{parsed['name']}-tree{tree_run['id']}-{attempt_index}-{uuid.uuid4().hex[:6]}"
    parsed["target"] = "tool_result"  # this engine only ever targets tool_result, regardless of what the mutation LLM proposes
    return parsed, strategy


async def _walk_backbone(tree_run: dict) -> list[dict]:
    """Resumable in the coarse sense only: if this TreeRun already has any
    backbone nodes (e.g. a prior run was interrupted mid-walk), Phase A is
    skipped entirely rather than continuing a partial walk -- a documented
    simplification, not a perfect resume.
    """
    tree_run_id = tree_run["id"]
    existing_nodes = await control_client.list_nodes(tree_run_id)
    if existing_nodes:
        return existing_nodes

    turns, _ = await _drive_turns(tree_run["base_campaign_id"], [], tree_run["max_backbone_turns"], tree_run_id)
    nodes = []
    for turn in turns:
        node = await control_client.create_node(
            tree_run_id,
            {"turn_index": turn["turn_index"], "message_sent": turn["message_sent"], "agent_reply": turn["reply"]},
        )
        nodes.append(node)
    return nodes


async def run_tree(tree_run_id: int) -> None:
    tree_run = await control_client.get_tree_run(tree_run_id)
    base_campaign = await control_client.get_campaign(tree_run["base_campaign_id"])

    generator_llm_model_id = base_campaign.get("generator_llm_model_id")
    judge_llm_model_id = tree_run.get("judge_llm_model_id") or generator_llm_model_id
    if not generator_llm_model_id or not judge_llm_model_id:
        await control_client.update_tree_run(tree_run_id, {"status": "stopped"})
        return
    generator_llm_model = await control_client.get_llm_model(generator_llm_model_id)
    judge_llm_model = await control_client.get_llm_model(judge_llm_model_id)

    seed_ids = tree_run["seed_template_ids"] or await seed_corpus.ensure_seed_pool("tool_result")

    try:
        backbone_nodes = await _walk_backbone(tree_run)
        if not await _is_running(tree_run_id):
            return
        scripted_messages = [n["message_sent"] for n in backbone_nodes]

        backbone_events = await control_client.list_campaign_events(tree_run["base_campaign_id"], limit=EVENTS_LIMIT)
        all_checkpoints = checkpoints.checkpoints_from_events(backbone_events)
        if tree_run["max_checkpoints"]:
            all_checkpoints = all_checkpoints[: tree_run["max_checkpoints"]]

        # what the backbone itself called AFTER each checkpoint, for the divergence comparison
        backbone_tool_names_after = {
            checkpoint["occurrence_index"]: {c["tool_name"] for c in all_checkpoints[idx + 1 :]}
            for idx, checkpoint in enumerate(all_checkpoints)
        }

        for checkpoint in all_checkpoints:
            if not await _is_running(tree_run_id):
                return

            done_attempts = [
                p for p in await control_client.list_probes(tree_run_id)
                if p["checkpoint_occurrence"] == checkpoint["occurrence_index"]
            ]
            if any(p["success"] for p in done_attempts):
                continue  # already found a working variant at this checkpoint

            for attempt_index in range(len(done_attempts), tree_run["attempts_per_checkpoint"]):
                if not await _is_running(tree_run_id):
                    return

                past_probes = await control_client.list_probes(tree_run_id)
                seed_id = bandit.select_seed(past_probes, seed_ids)
                seed_template = await control_client.get_template(seed_id)

                mutated, strategy = await _mutate(tree_run, seed_template, generator_llm_model, past_probes, attempt_index)
                new_template = await control_client.create_template(mutated)

                probe_campaign = await control_client.create_campaign(
                    {
                        "name": f"{base_campaign['name']}-tree-{tree_run_id}-cp{checkpoint['occurrence_index']}-{attempt_index}",
                        "session_id": base_campaign["session_id"],
                        "template_id": new_template["id"],
                        "status": "active",
                        "injection_rate": 1.0,
                        "inject_at_occurrence": checkpoint["occurrence_index"],
                        "agent_config_id": base_campaign.get("agent_config_id"),
                        "interactor_llm_model_id": base_campaign.get("interactor_llm_model_id"),
                        "generator_llm_model_id": base_campaign.get("generator_llm_model_id"),
                        "interactor_persona": base_campaign.get("interactor_persona"),
                        "user_instruction": base_campaign.get("user_instruction"),
                    }
                )
                # let proxy's active-campaign cache settle on this campaign before
                # driving any turns against it -- see CAMPAIGN_ACTIVATION_SETTLE_SECONDS
                await asyncio.sleep(CAMPAIGN_ACTIVATION_SETTLE_SECONDS)

                attack_goal = new_template.get("description") or new_template["payload"]
                score = {"detector_success": False, "judge_score": 0.0, "judge_verdict": ""}

                async def on_turn(reply: str, events: list[dict], score=score) -> bool:
                    score["detector_success"] = any(e["success_detected"] for e in events)
                    if score["detector_success"]:
                        return True
                    result = await judge.judge_compliance(judge_llm_model, reply, attack_goal)
                    score["judge_score"] = result["score"]
                    score["judge_verdict"] = result["verdict"]
                    return result["complied"]

                turns, stopped_reason = await _drive_turns(
                    probe_campaign["id"], scripted_messages, tree_run["max_probe_turns"], tree_run_id, on_turn=on_turn
                )

                probe_events = await control_client.list_campaign_events(probe_campaign["id"], limit=EVENTS_LIMIT)
                probe_tool_names_after = {
                    c["tool_name"]
                    for c in checkpoints.checkpoints_from_events(probe_events)
                    if c["occurrence_index"] > checkpoint["occurrence_index"]
                }
                backbone_tool_names = backbone_tool_names_after.get(checkpoint["occurrence_index"], set())
                diverged = probe_tool_names_after != backbone_tool_names

                await control_client.create_probe(
                    tree_run_id,
                    {
                        "checkpoint_occurrence": checkpoint["occurrence_index"],
                        "attempt_index": attempt_index,
                        "seed_template_id": seed_id,
                        "template_id": new_template["id"],
                        "campaign_id": probe_campaign["id"],
                        "tool_name": checkpoint["tool_name"],
                        "original_tool_result": checkpoint["tool_result"],
                        "injected_tool_result": new_template["payload"],
                        "trajectory": turns,
                        "stopped_reason": stopped_reason,
                        "detector_success": score["detector_success"],
                        "judge_score": score["judge_score"],
                        "judge_verdict": score["judge_verdict"],
                        "reward": 1.0 if score["detector_success"] else score["judge_score"],
                        "success": stopped_reason == "success",
                        "diverged_from_backbone": diverged,
                        "divergence_detail": (
                            f"backbone continued with {sorted(backbone_tool_names)}, "
                            f"this attempt continued with {sorted(probe_tool_names_after)}"
                        ),
                    },
                )

                if stopped_reason == "success":
                    break

        await control_client.update_tree_run(tree_run_id, {"status": "completed"})
    except Exception:
        await control_client.update_tree_run(tree_run_id, {"status": "stopped"})
        raise
