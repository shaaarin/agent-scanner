"""UCB1 seed selection for the fuzz engine -- picks which seed InjectionTemplate
("arm") to mutate next, given this FuzzRun's past attempts. Same exploration/
exploitation strategy GPTFuzzer and AgentVigil both use for jailbreak fuzzing.
"""

import math


def select_seed(attempts: list[dict], seed_ids: list[int]) -> int:
    """attempts: past FuzzAttempt dicts for this run (each has seed_template_id,
    reward). seed_ids: the full candidate pool. Unpulled arms are tried before
    any UCB1 comparison, matching standard UCB1 initialization.
    """
    if not seed_ids:
        raise ValueError("seed_ids must not be empty")

    pulls: dict[int, int] = {seed_id: 0 for seed_id in seed_ids}
    reward_sums: dict[int, float] = {seed_id: 0.0 for seed_id in seed_ids}
    for attempt in attempts:
        seed_id = attempt["seed_template_id"]
        if seed_id not in pulls:
            continue
        pulls[seed_id] += 1
        reward_sums[seed_id] += attempt["reward"]

    unpulled = [seed_id for seed_id in seed_ids if pulls[seed_id] == 0]
    if unpulled:
        return unpulled[0]

    total_pulls = sum(pulls.values())

    def ucb1(seed_id: int) -> float:
        mean_reward = reward_sums[seed_id] / pulls[seed_id]
        exploration = math.sqrt(2 * math.log(total_pulls) / pulls[seed_id])
        return mean_reward + exploration

    return max(seed_ids, key=ucb1)
