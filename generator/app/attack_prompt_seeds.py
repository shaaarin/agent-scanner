"""Turns a scan's attack-prompt checklist (`FuzzRun`/`TreeRun.attack_prompt_ids`) into
concrete seed `InjectionTemplate`s -- one LLM call per selected `AttackPrompt`, same
mechanism `POST /generate` uses. See docs/architecture.md.

`AttackPrompt` itself carries no delivery target -- its semantics (what it's
trying to get the agent to do) are independent of where it's delivered, so
the same checklist entry can seed both a `FuzzRun` and a `TreeRun`. The
caller (fuzz_engine.py/tree_engine.py) says which target it needs and this
enforces it, rather than trusting the LLM's own choice -- same reasoning as
tree_engine.py's `_mutate` forcing `target="tool_result"`.
"""

from app import control_client, llm_client
from app.prompts import RESPONSE_SHAPE


async def generate_seeds_from_attack_prompts(
    attack_prompt_ids: list[int], generator_llm_model: dict, run_tag: str, target: str
) -> list[int]:
    seed_ids: list[int] = []
    for attack_prompt_id in attack_prompt_ids:
        attack_prompt = await control_client.get_attack_prompt(attack_prompt_id)
        system_prompt = f"{attack_prompt['system_prompt']}\n\n{RESPONSE_SHAPE}"

        raw = await llm_client.call_chat_completion(generator_llm_model, system_prompt, "Generate one injection template now.")
        parsed = llm_client.parse_template_json(raw)
        parsed["target"] = target
        parsed.setdefault("tags", [])
        parsed["tags"] = [*parsed["tags"], f"attack_prompt:{attack_prompt_id}", run_tag, "generator:llm"]

        created = await control_client.create_template(parsed)
        seed_ids.append(created["id"])
    return seed_ids
