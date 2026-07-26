# Architecture

## Phase 1 — LLM Proxy MVP [transport revised — see "MITM pivot" below; capture-only revised — see "Direct-to-LLM fuzzing delivery" below]

Two services:

- **`proxy`** (mitmproxy addon, see "MITM pivot" below for how traffic
  actually reaches it): **capture-only** — it never injects or detects
  anything itself. On each intercepted `.../chat/completions` flow:
  1. Reads `SESSION_ID` from its own environment (one sidecar per Pod, set
     by `launcher`).
  2. Polls `control-api` (`GET /campaigns/active?session_id=...`, 2s TTL
     in-memory cache) purely to resolve which `campaign_id` this session's
     traffic should be attributed to for logging — the response carries no
     template/injection fields at all (`{campaign_id, session_id, status}`).
  3. Forwards the request unmodified to whatever real upstream the tested
     agent's own connection was headed to — mitmproxy discovers this
     per-connection, `proxy` never needs to resolve it itself.
  4. For streamed responses (`"stream": true`): passes SSE chunks through to
     the client unmodified while reassembling them in memory so the complete
     body still gets logged.
  5. Every request and response is logged to `control-api` via
     `POST /events`, fire-and-forget — a `control-api` outage never breaks
     the proxied call.

- **`control-api`** (FastAPI + SQLModel/SQLite): the control plane and single
  source of truth for `InjectionTemplate`, `Campaign`, and `TrafficEvent`.
  Also the backend for the web UI and attack generator.

**Why capture-only**: injection and detection used to happen live, in
`proxy`, against the tested agent's real intercepted traffic (this section
described that design until the "Direct-to-LLM fuzzing delivery" pivot
below). That mechanism required creating a fresh ephemeral `Campaign` row
per fuzzing attempt so `proxy` would inject/detect exactly once per attempt
— which the current design replaced entirely: `proxy`'s only remaining job
is capturing the *one* honest baseline exchange per `Campaign` (so the fuzz
engines know what the agent's LLM actually sees), and every fuzzing attempt
after that is a direct chat-completion call `generator` makes itself,
outside `proxy` and outside the live agent. See that section for the full
mechanism and the reasoning behind it.

The former body-transformation/detection modules (`openai_provider.py`'s
injection helpers, `injector.py`, `detector.py`, `vuln_signatures.py`) were
transport-agnostic — pure functions over plain `dict` bodies, never touching
an HTTP request/response object directly. That's what made them portable:
they were **moved from `proxy/app/` into `generator/app/`**
(`injection_apply.py`, `success_detector.py`, `vuln_signatures.py`,
`response_helpers.py`) rather than rewritten, since fuzzing attempts now
construct/mutate a body and call an LLM directly instead of a live
`HTTPFlow` being intercepted. `proxy/app/openai_provider.py` kept only its
streaming-reconstruction helpers (`StreamAccumulator`, `parse_sse_lines`,
`is_streaming_request`), still needed for capture.

### Data model

- **`InjectionTemplate`**: `target` (`user_message` | `tool_result` |
  `assistant_response` | `system_prompt`), `mode` (`append` | `prepend` |
  `replace`), `payload`, `success_indicator` (regex), `success_indicator_field`
  (`tool_name` | `tool_arguments` | `response_text`), `tags`. Still exists
  exactly as before as an internal artifact — every generated fuzzing
  attempt creates one to record what was tried — it's just never "activated"
  via a live `Campaign`/`proxy` anymore; see "Direct-to-LLM fuzzing
  delivery" below. Never user-facing (no `Templates` CRUD page).
- **`Campaign`**: the single scan-configuration point — `session_id`,
  `agent_config_id`, the platform's own `interactor_llm_model_id`/
  `generator_llm_model_id`, `interactor_persona`/`user_instruction`. Carries
  no template/injection fields at all (removed: `template_id`,
  `injection_rate`, `inject_at_occurrence` — dead once nothing ever
  "activates" a template on a live campaign). `status` is a small lifecycle:
  `new` (just created) → `active` (launched; `proxy` attributes captured
  traffic to it, and the one honest baseline exchange for its `FuzzRun`/
  `TreeRun` gets driven for real) → `paused` (halted, resumable back to
  `active`) or `cancelled` (halted, terminal).
- **`TrafficEvent`**: one row per intercepted request/response. `injected`/
  `injection_target`/`success_detected` are always `false`/`null` now (dead
  fields kept for schema continuity, since `proxy` never injects or detects
  — see above). `raw_excerpt` is stored **in full, untruncated** (previously
  capped at 4096 bytes) — it's load-bearing now: the fuzz/tree engines
  replay the exact captured `messages` array to the tested LLM directly, so
  a truncated body would corrupt every downstream fuzzing attempt.

### Provider support

Only OpenAI's `/v1/chat/completions` format is implemented. The former
injection/detection functional interface (`inject_request`/`inject_response`/
`iter_tool_calls`/`get_response_text`) now lives in `generator/app/`
(see above) rather than `proxy/app/`; an Anthropic `/v1/messages` provider
module would extend that interface there instead.

## MITM pivot — how traffic actually reaches `proxy`

**Revises the original Phase 1 attach mechanism.** The first version of this
platform pointed a tested agent's `OPENAI_BASE_URL` explicitly at `proxy` —
simple, but it meant the agent needed a one-line config change, which isn't
"near zero changes" for an agent that already has its own real provider
config. The platform now intercepts a tested agent's LLM traffic
**transparently**, at the network level, inside its own Pod. The agent's own
LLM credentials/base_url are whatever's in `AgentConfig.env_vars` — a real
`OPENAI_API_KEY` pointed at a real-looking `OPENAI_BASE_URL`, exactly what a
real deployment would already have. `proxy` never needs to know the target
upstream in advance; it discovers it per-connection from the intercepted
TLS SNI/original destination.

Mechanism, per Pod (`launcher/app/pod_manager.py`):

1. **`ca-trust-setup` initContainer**: writes a combined CA bundle (the init
   image's own OS default CAs + the platform's MITM root CA, see
   `launcher/app/ca_manager.py`) into a shared `emptyDir`, mounted over the
   agent container's system trust-store file
   (`/etc/ssl/certs/ca-certificates.crt`, covers Debian/Ubuntu/Alpine — the
   base images every current example agent uses) via a `subPath` mount so
   only that one file is replaced. `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE`/
   `NODE_EXTRA_CA_CERTS` are also set on the agent container pointing at the
   same path, as a supplementary best-effort measure.

   > **Known, accepted limitation**: this only covers OS-level trust stores.
   > Language ecosystems that bundle their own CA store independent of the
   > OS — notably Python's `certifi`, which `httpx`/the OpenAI SDK use by
   > default — won't pick up the overwritten system file at all. The `SSL_CERT_FILE`
   > env var is a partial mitigation: it works for libraries that explicitly
   > honor it (verified against `httpx.Client(verify=os.environ.get("SSL_CERT_FILE"))`,
   > see `examples/stub-agent/agent.py`), but a library that ignores it and
   > trusts only `certifi` will fail closed (connection refused due to cert
   > verification failure) rather than silently bypass interception — not
   > solved in this pass, flagged here rather than fixed.

2. **`net-setup` initContainer** (`NET_ADMIN` capability): installs
   `iptables` and adds `iptables -t nat -A OUTPUT -p tcp --dport 443
   -m owner ! --uid-owner <mitm-uid> -j REDIRECT --to-port 8443` — redirects
   all outbound HTTPS (port **443** specifically; a target on a nonstandard
   port won't be intercepted) to the `mitm-proxy` sidecar's listening port,
   excluding the sidecar's own uid so its own upstream connections don't
   get redirected back into itself.

   > **Known limitation**: initContainers necessarily run to completion
   > *before* any regular container starts, so the iptables rule is live
   > before `mitm-proxy` is actually listening. An agent connection attempted
   > in that narrow startup window fails outright (connection refused) —
   > acceptable for an MVP since real agents rarely dial out in the first
   > instant of process start, and most HTTP clients/frameworks retry.

3. **`mitm-proxy` sidecar**: the `proxy` image itself, running mitmproxy in
   `--mode transparent` (real Linux `SO_ORIGINAL_DST`-based interception),
   sharing the Pod's network namespace with the agent container so the
   REDIRECT above lands on it. Runs as a fixed non-root uid (`MITM_UID=1000`
   in `pod_manager.py`) matching the `net-setup` exclusion rule. Loads the
   platform's own CA (mounted from the same Secret as step 1) as *its own*
   signing CA via `proxy/docker-entrypoint.sh` (concatenates `ca.crt`+`ca.key`
   into mitmproxy's `confdir/mitmproxy-ca.pem`), so the leaf certs it
   generates on the fly chain back to exactly the CA the agent's trust store
   was overwritten with — not mitmproxy's own randomly-generated default CA.

CA keypair lifecycle (`launcher/app/ca_manager.py`): generated once
(self-signed, RSA 2048, ~10y validity) and stored as a Kubernetes Secret
(`agent-scanner-mitm-ca`) in a dedicated `agent-scanner-system` namespace;
copied into each scan's namespace on first launch (`ensure_ca_secret_in_namespace`),
since Kubernetes Secrets aren't readable across namespaces and every Pod
volume mount needs a Secret in its own namespace.

**Local dev/test mode**: the exact same `proxy` image/addon also runs in
mitmproxy's `--mode regular` (explicit proxy, `HTTPS_PROXY` env var) for
fast iteration in `docker compose`, without the iptables/initContainer
machinery — see `docs/running-locally.md`'s two separate verification
paths. Toggled via the `MITM_MODE` env var
(`transparent` default / `regular` for compose), read by
`proxy/docker-entrypoint.sh`.

**Reachability gotcha hit during verification**: the `mitm-proxy` sidecar
calls `control-api` directly from inside the Kubernetes cluster — if that's
a Docker Compose container name, the cluster's own CoreDNS can't resolve it
(same class of problem `build.py` already had for `git-server`, now
factored into a shared `launcher/app/host_alias.py` helper: `launcher`
resolves the host itself, where it *is* resolvable via Docker's embedded
DNS, and pins it as a Pod `hostAlias`). A second, non-obvious wrinkle: a
hostAlias only helps if the resolved IP is actually **routable** from the
cluster, which means the target container needs to be on the `kind` Docker
network too — but attaching `control-api` itself to `kind` (tried first)
turned out to reintroduce a different, already-known problem: on this
Docker Desktop/WSL2 setup, a dual-homed (default + `kind`) service's
*host-published* port becomes flaky (the same quirk already documented
below for `launcher`/`interactor`). That's tolerable for `launcher`'s
occasional API calls but not for `control-api`, which the web UI's browser
hits on `localhost:8000` constantly. Fix: a dedicated
`control-api-mitm-bridge` forwarder (`alpine/socat`, `docker-compose.yml`)
absorbs the dual-homing instead — `control-api` itself stays
default-network-only (reliable host port), and `launcher` points the
sidecar's `CONTROL_API_URL` at the bridge (`MITM_CONTROL_API_URL` env var
on `launcher`, resolved via the same `host_alias.py` helper) instead of at
`control-api` directly.

## Phase 2 — Attack generator (LLM-based)

A `generator` service (FastAPI + httpx). It never touches `proxy`'s runtime path — it only
creates `InjectionTemplate` rows via `control-api`, and (for fuzzing) calls the tested LLM
directly itself — see "Direct-to-LLM fuzzing delivery" below.

- **`control-api`'s `AttackPrompt`** (`control-api/app/models.py`, `/attack-prompts` CRUD router): instructions for the generator LLM on how to construct one class of attack (a jailbreak/injection technique) — `name`, `description`, `system_prompt`, `tags`. Deliberately carries **no delivery target**: an attack's semantics (what it's trying to get the agent to do) are independent of *where* it's delivered, so the same checklist entry seeds both a `FuzzRun` (direct/`user_message`) and a `TreeRun` (indirect/`tool_result`) — whichever engine consumes it enforces its own target (`fuzz_engine.py` forces `user_message`, `tree_engine.py` forces `tool_result`), same as each already does for its own mutation loop. This **replaced** an earlier hardcoded `generator/app/prompts.py:ATTACK_CLASS_PROMPTS` dict (7 built-in classes: `tool_call_hijack`, `sandbox_escape`, `xss_via_tool_arg`, `ssrf_via_tool_arg`, `rce_via_tool_arg`, `idor_via_tool_arg`, `sqli_via_tool_arg`) once it became clear users need to author/edit their own, not just the built-in ones. `control-api/app/seed.py` seeds those same 7 as `AttackPrompt` rows on startup, so nothing built-in was lost.
- **`generator/app/prompts.py`** now holds only the shared, non-attack-specific scaffolding: `RESPONSE_SHAPE` (the strict-JSON response-shape instruction matching `InjectionTemplate`'s fields, appended to whichever `AttackPrompt.system_prompt` is in play) and `MUTATION_PROMPT`/`ADAPT_PROMPT` (`__MARKER__`-style `str.replace()` substitution rather than `str.format()`, since the embedded JSON example in `RESPONSE_SHAPE` contains literal braces that broke `.format()` — hit and fixed during verification).
- **`generator/app/llm_client.py`**: calls the configured LLM via **LiteLLM**'s unified `acompletion()` interface (not a hand-rolled OpenAI-format httpx call) — works against any provider LiteLLM supports, picked via the `LLMModel`'s `provider_type`/`model`, with `base_url` passed through as a custom `api_base`. Never through `proxy`, since the generator's own LLM calls are not the system under test. Parses/validates the assistant's JSON response. `generator/app/direct_llm.py` is the sibling used for fuzzing attempts specifically — see below.
- **`generator/app/main.py`** routes:
  - `POST /generate {attack_prompt_id, llm_model_id, target_context}` → fetches the `AttackPrompt` from `control-api`, calls the LLM with its `system_prompt` + `RESPONSE_SHAPE`, creates the resulting `InjectionTemplate` (tagged `attack_prompt:<id>`, `generator:llm`).
  - `POST /mutate {template_id, llm_model_id, strategy_hint, count}` → fetches the existing template, asks the LLM for `count` variants, creates each (tagged `mutated_from:<id>`).
  - `POST /adapt` was **removed**: it used to fetch "the campaign's current template" and its recent unsuccessful `TrafficEvent`s, but a `Campaign` never carries a "current template" anymore (see "Direct-to-LLM fuzzing delivery" below) — its reasoning (adapt from recent failures) is now fully absorbed into `fuzz_engine.py`/`tree_engine.py`'s own `mode=adaptive` (they already draw on this run's own `FuzzAttempt`/`InjectionProbe` history, a strictly better feedback loop than one standalone campaign-triggered call).
- Verified against a real provider (see `docs/running-locally.md` — register an `LLMModel` from `.env`'s `LLM_PROVIDER_*` creds); there is no mock LLM stand-in for this service.

### Direct-to-LLM fuzzing delivery (shared by both engines below)

Both the fuzz engine (direct) and the injection tree (indirect) used to deliver every single
fuzzing attempt by creating a **fresh ephemeral `Campaign` row**, activating it, and driving the
**real tested agent** through `interactor`, relying on `proxy`'s transparent MITM interception to
apply the injection and detect success on the agent's own live traffic. This was rejected as
unnecessary churn — a 20-iteration `FuzzRun` meant 20 throwaway `Campaign` rows — and replaced
with a fundamentally simpler mechanism:

1. **One honest baseline exchange per `Campaign`, shared by both engines.**
   `generator/app/backbone.py::ensure_backbone(base_campaign)` checks whether `base_campaign_id`
   already has captured request-direction `TrafficEvent`s; if not, it drives exactly one exchange
   for real via `interactor_client.session_turn(base_campaign_id, message=None)` (persona-authored
   message) — the *only* point where the live agent, `interactor`, and `proxy`'s MITM interception
   are involved at all. Whichever of `run_fuzz_iterations`/`run_tree` starts first does this; the
   other reuses the same captured events (an in-process `asyncio.Lock` keyed by `base_campaign_id`
   serializes the race — a known single-generator-process MVP limitation, not distributed-safe).
2. **Every fuzzing attempt is a direct chat-completion call, not an agent call.** Each captured
   request event's `raw_excerpt` is the *exact* `messages` array (+ `tools`/`model`/etc.) the real
   agent's LLM client sent at that point. An attempt takes a `copy.deepcopy` of the relevant
   captured body, mutates one message in place
   (`generator/app/injection_apply.py::apply_injection` — ported from the old `proxy/app/
  openai_provider.py`/`injector.py`, same `append`/`prepend`/`replace` semantics, just operating on
   a locally-held dict instead of a live `HTTPFlow` body), and sends the mutated body directly to
   the tested agent's own LLM (`generator/app/direct_llm.py::call_raw_completion` — via LiteLLM,
   forcing `stream=False`, using the *captured* `model` field rather than a second configured
   value). The raw completion is scored with `success_detector.evaluate` (ported from
   `proxy/app/detector.py`, byte-for-byte identical logic) and `judge.judge_compliance` as before.
   No `Campaign` row, no `interactor` call, no `proxy` involvement for any of this — the whole
   thing after step 1 is `generator` talking directly to an LLM endpoint.
3. **Credentials come from what `proxy` actually observed, not from any configured value.**
   During the one honest baseline exchange, `proxy/addon.py` captures the real upstream connection
   target and the real `Authorization` header the agent's own LLM client sent
   (`TrafficEvent.upstream_base_url`/`request_authorization`) — not just the request/response
   *body*, as it did before. `direct_llm.resolve_target_credential` reads these straight off the
   captured backbone request, so there is nothing to configure at all: the platform never needs to
   know or guess the agent's own env var naming for its LLM client, the same "zero changes to the
   tested agent, transparent interception" principle as the MITM pivot below, just applied to
   credential discovery too instead of only to traffic interception. (An earlier version of this
   design asked the user to configure `AgentConfig.target_llm_base_url_env`/`target_llm_api_key_env`
   — env var *names* to look up in `AgentConfig.env_vars` — removed once it became clear `proxy`
   already has the real values directly and doesn't need to ask.)

Consequences: `proxy` shrank to pure capture (see Phase 1 above) — nothing left ever sets
`Campaign.template_id`/`injection_rate`/`inject_at_occurrence`, so those fields were removed
entirely rather than left nullable-and-unused. `InjectionTemplate` is unaffected — every attempt
still creates one to record what was tried, just never "activated" via a live campaign.

### Fuzz engine (one-shot jailbreak/injection fuzzing, direct only)

An autonomous, budget-driven search loop over `InjectionTemplate` variants — a `FuzzRun`
(`control-api/app/models.py`) — instead of manually triggering `/generate`/`/mutate` one at a
time. Built after a literature review of GPTFuzzer, PAIR/TAP, AgentVigil, and InjecAgent/AgentDojo,
which converge on: a persisted log of attempts, a seed pool + mutation operators, a bandit-style
seed-selection strategy, and a judge/oracle scoring each attempt.

**Direct only** (`injection_target=user_message`) — `control-api/app/api/fuzz_runs.py:
create_fuzz_run` rejects any other target with 400. Indirect (`tool_result`) fuzzing is the
"Injection tree" mechanism below, sharing the same delivery primitive (previous section) but with
per-checkpoint discovery instead of a single implicit checkpoint.

- **`control-api`**: `FuzzRun` (binds to a `base_campaign_id` for session/agent/LLM config, `mode`
  is `adaptive`/`non_adaptive`, `seed_template_ids`/`attack_prompt_ids`/`max_iterations`/
  `stop_on_success`/`status`) and `FuzzAttempt` (one row per iteration: seed template "arm", the
  mutated template actually tried, detector + judge verdicts, combined `reward` — no `campaign_id`
  column anymore, nothing to point at). New `/fuzz-runs` router. `attack_prompt_ids` is the
  checklist: a scan can pick specific `AttackPrompt`s to seed the search from, generated via one
  `POST /generate`-equivalent LLM call each at bootstrap (`generator/app/attack_prompt_seeds.py`,
  which enforces `target="user_message"` on the caller's behalf) — unioned with any explicit
  `seed_template_ids`; if both are empty, falls back to the built-in `seed_corpus.py` corpus.
- **`generator`**: `bandit.py` (pure UCB1 `select_seed`, same exploration/exploitation strategy
  GPTFuzzer/AgentVigil use), `seed_corpus.py` (a small hand-authored jailbreak seed library,
  bootstrapped into `control-api` on first use per `injection_target`), `judge.py` (LLM-as-judge
  oracle: classifies whether the agent's reply actually complied with the injected goal — needed
  because `success_detector` only recognizes tool-call/pattern-shaped success, not a plain
  jailbreak that produced disallowed prose with no tool call), `mutators.py` (named non-adaptive
  operators — rephrase/expand/shorten/encode_obfuscate/persona_shift), and `fuzz_engine.py` (the
  orchestration loop — see "Direct-to-LLM fuzzing delivery" above for what each iteration actually
  does — run as a background `asyncio` task via `POST /fuzz/{id}/start`, cooperatively stoppable
  via `POST /fuzz/{id}/stop`; `/fuzz/{id}/start` preflights that `base_campaign` is `status=active`
  and that its `AgentConfig`'s target LLM credentials actually resolve, failing fast with 400
  rather than async mid-run).
- Because every iteration's full state is a durable `FuzzAttempt` row, pausing a run and
  inspecting/resuming it later requires no special snapshot mechanism — it falls out of the
  data model for free. See `docs/running-locally.md`'s "Using the fuzz engine" for the curl
  walkthrough (direct, adaptive/non-adaptive).

### Injection tree (indirect fuzzing: per-tool-call A/B branching)

Real tool-calling agents often run many internal tool calls to complete one task. A single
injected exchange in isolation (what the fuzz engine above does) doesn't reveal what an
already-*established* conversation looks like right before the point being fuzzed — so indirect
(`tool_result`) fuzzing works differently: the shared honest **backbone** exchange (previous
section) surfaces a series of points where the agent received a new tool result
(**checkpoints**). Each checkpoint is fuzzed independently — several mutated payloads, bandit +
mutation, same delivery primitive as the fuzz engine — each attempt a **single** direct
chat-completion call against that checkpoint's captured message array with its tool result
swapped, compared against what the backbone itself actually did right after that same checkpoint.

**The realization that made this tractable**: a single *external* exchange (one `interactor` <->
agent call) can contain many *internal* tool calls, each a separate request the agent makes to
its own LLM backend — and `proxy` intercepts every one of those during the honest backbone capture,
regardless of `interaction_mode` (`api` or `langgraph`) and regardless of how many external turns
it took to produce them. So checkpoint discovery doesn't need to happen at the external-turn level
at all — it's read straight back out of `control-api`'s own `TrafficEvent` log for a campaign. This
is what makes the feature **mode-agnostic**.

- **`generator/app/checkpoints.py::checkpoints_from_events`**: reads a campaign's
  `TrafficEvent`s (full, untruncated `raw_excerpt` — see Phase 1's data-model note) for
  newly-appeared `role: tool` messages across successive requests. Each checkpoint carries
  `{occurrence_index, tool_name, tool_result, request_body, flow_id}` — `request_body` is the
  full captured body as of that tool result first appearing (what gets mutated and replayed
  directly), `flow_id` links to the paired response `TrafficEvent` holding what the real backbone
  actually decided to do right after seeing it (used for the divergence comparison below).
- **`control-api`**: `TreeRun` (the search config: `base_campaign_id`, `max_checkpoints`/
  `attempts_per_checkpoint`/`mode`/`seed_template_ids`/`attack_prompt_ids`, same checklist
  mechanism as `FuzzRun`), `ConversationNode` (the backbone's one external exchange), and
  `InjectionProbe` (one fuzzing attempt at one checkpoint occurrence — `trajectory` now holds
  exactly one `{request, response}` pair, the direct call's mutated body and raw completion, not a
  multi-turn transcript — `stopped_reason` (`"success"`/`"no_success"`), detector+judge verdict,
  and `diverged_from_backbone`/`divergence_detail`). New `/tree-runs` router. No `campaign_id`
  column on `InjectionProbe` anymore, same reasoning as `FuzzAttempt` above.
- **`generator/app/tree_engine.py`**: reuses `bandit.py`/`mutators.py`/`judge.py`/`seed_corpus.py`
  unchanged, plus `checkpoints.py` above. `run_tree` calls the shared `backbone.ensure_backbone`
  once, then for each checkpoint calls `_probe_checkpoint`: mutate a deep copy of
  `checkpoint["request_body"]`'s tool-result message
  (`injection_apply.apply_injection(..., target="tool_result", ...)`), call
  `direct_llm.call_raw_completion` directly, score with `success_detector.evaluate` + judge
  fallback. **Divergence** is now a single-step comparison (previously a multi-turn trajectory
  comparison against a live re-driven agent, which no longer exists): the probe's response's
  immediate tool-call decision vs. what the backbone's own paired response event (same `flow_id`)
  shows the real agent actually decided right after that same checkpoint — a strictly more direct
  measurement of the same thing. Runs as a background `asyncio` task (`POST /tree/{id}/start`/
  `POST /tree/{id}/stop`, same preflight/pattern as the fuzz engine).
- See `docs/running-locally.md`'s "Using the injection tree" for the curl walkthrough.

## Phase 4 — Web UI + scan configuration

`web/` is a Vite + React + TypeScript app styled directly on `https://cabinet.miem.hse.ru/`'s
own source CSS (fetched and inspected, not guessed): a **left icon-rail
sidebar** (6.4rem wide, white, active item filled with the brand accent) +
slim top header, `Onest` font, **orange brand accent** (`#ff6d00`, not blue),
a black-opacity text scale (`--text-1000` through `--text-300`) instead of
named grays, generously rounded corners (1.2–2rem depending on component
size — buttons and cards read as noticeably rounded, not sharp/minimal), and
soft diffuse shadows (`rgba(26,26,26,.08)` at a 1.6rem blur). Design tokens
live in `web/src/theme/tokens.css`, named after the source site's own custom
properties. It talks directly to `control-api` from the browser
(`VITE_CONTROL_API_URL`, `control-api` has permissive CORS enabled for this).

**Campaigns page** (`web/src/pages/Campaigns.tsx`, route `/campaigns`): the
single scan-configuration point — creates a `Campaign` (session + agent +
platform LLM roles) and, via two optional checkbox-gated sections, a linked
`FuzzRun` (direct) and/or `TreeRun` (indirect) in the same submit
(`base_campaign_id` set to the campaign just created). No manual
`InjectionTemplate` picking — templates are internal fuzzing artifacts only
now (no `Templates` CRUD page).

**Scan progress view** (`web/src/pages/ScanDetail.tsx`, route `/campaigns/:id`):
a per-scan dashboard — stat cards (exchanges/successes), agent launch
controls (calls `launcher` directly via `VITE_LAUNCHER_URL`, CORS-enabled for
this same reason) with live-polled status, a "Run interactor" button (calls
`interactor` via `VITE_INTERACTOR_URL`) rendering the resulting transcript as
chat bubbles, status cards for any linked `FuzzRun`/`TreeRun` (start/stop,
link to `web/src/pages/FuzzRunDetail.tsx`/`TreeRunDetail.tsx`), and
`web/src/components/FlowTimeline.tsx` — groups `TrafficEvent`s by `flow_id`
into request/response pairs, live-polled every 3s. Since `proxy` is
capture-only now (see Phase 1), every event here is un-injected captured
traffic; fuzzing results live on the `FuzzRun`/`TreeRun` detail pages
instead, not this timeline.

Two new `control-api` entities back the scan-configuration screens:

- **`LLMModel`** (renamed from an earlier `ProviderCredential` design once it became clear each role needed its own explicit choice, not a shared reusable credential): `name`, `provider_type` (`openai`/`anthropic`), `base_url`, `api_key`, `model` (passed to LiteLLM, e.g. `"gpt-4o-mini"` or `"claude-3-5-sonnet-latest"`). Stored in **plain text** — an explicitly accepted MVP tech-debt item, not a long-term security posture. Used for the platform's own two outbound LLM roles, each with its **own explicit FK**, not a shared "credential" reused by role:
  - the interactor's model: `Campaign.interactor_llm_model_id`;
  - the generator's model: `Campaign.generator_llm_model_id`.

  The tested agent's own model is *not* an `LLMModel` row at all — see the MITM pivot above: it's just whatever real provider config is in `AgentConfig.env_vars`, intercepted transparently rather than resolved by the platform. (An earlier iteration added `AgentConfig.target_llm_model_id` for this; removed when the MITM pivot made it unnecessary — `proxy` no longer needs to know the target upstream in advance.)
- **`AgentConfig`**: `git_repo_url`, `git_ref` (default `main`), `git_access_token`
  (optional — a Personal Access Token for private HTTPS repos, embedded
  into the clone URL as `https://oauth2:<token>@host/...` by
  `launcher/app/git_auth.py` — GitLab's documented PAT-over-HTTPS convention
  (non-empty placeholder username, token as password); GitHub accepts this
  shape too since it doesn't validate the username. An earlier version put
  the token in the username slot with no password
  (`https://<token>@host/...`), which GitHub tolerated but a real self-hosted
  GitLab instance rejected as anonymous, falling back to an interactive
  credential prompt that fails hard in a non-interactive clone. No-op for
  the platform's own `git://` test servers or `ssh://` remotes. Plain text,
  same accepted MVP tech-debt posture as `LLMModel.api_key` — see the
  security note in `git_auth.py`'s docstring about clone-failure logs),
  `dockerfile_path` (default `"Dockerfile"` — path to the Dockerfile itself,
  relative to the repo root; the build context is always the repo root,
  matching normal Docker semantics), `env_example_path` (optional — a
  `.env.example`-style file in the repo that `launcher` reads to auto-fill
  any `env_vars` keys not already set, see Phase 6), `api_port` (optional —
  if the agent listens on one, `launcher` auto-exposes it via a `NodePort`
  Service, see Phase 6), `entrypoint` (optional command override; not
  exposed in the web UI's create/edit form — the user's view is that this
  belongs in the Dockerfile/image, not a platform-level override choice),
  `env_vars` (JSON dict — this is where the agent's real LLM provider config
  lives, as plain env vars, exactly like a real deployment; `proxy` captures
  the real values transparently during the honest baseline exchange rather
  than needing them configured anywhere else — see "Direct-to-LLM fuzzing
  delivery" above), `resources` (optional, also not exposed in the web UI —
  `{"cpu": ..., "memory": ...}`), `agent_purpose` (free text describing what
  the agent is for — context for `interactor`'s legit-user persona,
  Phase 7), `interaction_mode` (`none`/`api`/`langgraph`),
  `api_config`/`langgraph_config` (JSON, mode-specific — see
  Phase 7 for each shape; `api_config.url`/`langgraph_config.base_url`'s
  host/port are overwritten automatically by `launcher` once `api_port`'s
  Service exists, only the path needs to be set by hand). Source is always
  fetched from git and built in-cluster — see Phase 6.
- **`Campaign`** gained nullable FKs (`agent_config_id`, `interactor_llm_model_id`,
  `generator_llm_model_id`) and fields (`interactor_persona`,
  `user_instruction` — what the interactor's legit-user persona is
  allowed/told to do; only `benign_user` is currently honored, see Phase 7).
  `status` is a small lifecycle (`new` → `active` → `paused`/`cancelled` —
  see Phase 1's data-model note) rather than a free-form choice at creation
  time; the web form always creates `new` and launching/pausing/cancelling
  are actions on the campaign list afterward.

New routes: `/llm-models` (list responses mask `api_key`; only `GET /llm-models/{id}`
returns it in full) and `/agent-configs`, both standard CRUD.

> **No DB migrations yet** (`SQLModel.metadata.create_all()` only adds
> missing tables, it doesn't alter existing ones): after a schema change,
> a dev environment with a pre-existing `control-api-data` volume needs
> `docker volume rm agent-scanner_control-api-data` before the next
> `docker compose up`. Accepted as MVP tech debt; revisit with Alembic if
> this needs to survive real production data.

## Phase 3 — Detection hardening

Regex-only `success_indicator` matching, hardened with signature-based classic-web-vuln
detection, without any schema change (`FuzzAttempt`/`InjectionProbe`'s judge/detector fields were
always free-form; `detail`-equivalent info holds a JSON-encoded string). Originally lived in
`proxy/app/detector.py`, applied to live intercepted traffic — **moved to
`generator/app/success_detector.py`** as part of "Direct-to-LLM fuzzing delivery" (Phase 2 above),
since `proxy` no longer sees fuzzing attempts at all; logic is otherwise unchanged.

- **`generator/app/vuln_signatures.py`**: regex signature sets for five vuln classes — `ssrf` (cloud metadata endpoint, localhost/private-IP URLs, `file://`), `sqli` (UNION SELECT, tautology `OR 1=1`, comment/drop-table sequences), `rce` (shell metacharacter chains, `` `cmd` ``/`$(cmd)`), `path_traversal` (`../`, `/etc/passwd`), `xss` (`<script>`, `on*=` handlers, `javascript:`).
- **`success_detector.scan_vuln_signatures(request_body, response_body)`**: scans every tool call's `arguments` in the response against all signature sets, and separately checks for **XSS echo-back** — a `role: tool` message earlier in the request's conversation history that looked like XSS reappearing verbatim in the assistant's response text (a proxy for "rendered unescaped downstream").
- **`success_detector.evaluate(...)`** combines this with `check_success` (same regex logic): `success_detected` is true if *either* the template's own `success_indicator` matches *or* any signature fires. The JSON detail becomes `{"indicator_match": "...", "vuln_signatures": [{"class": "ssrf", "field": "tool_arguments", "tool": "...", "snippet": "..."}]}`.
- Called directly by `fuzz_engine.py`/`tree_engine.py` on each direct chat-completion call's mutated request + raw response — see "Direct-to-LLM fuzzing delivery" above.

## Phase 6 — Agent launcher (Kubernetes, git-based build)

Tested agents run in Kubernetes, not plain Docker (revised from an initial Docker-Engine-based implementation — see "Implementation status" below). A target's source comes from a **git repository** (specified on its `AgentConfig`); `launcher` builds it in-cluster and launches it as a Pod.

1. **`launcher` service** (FastAPI + the `kubernetes` Python client, no Docker socket, no Docker CLI). Talks to an **external** cluster via a kubeconfig bind-mounted from the host (`KUBECONFIG` env var) — the rest of the platform stays in Docker Compose. `POST /launch` runs the whole flow the user asked this to follow explicitly — clone, discover env defaults, build, run, expose:
   - **Namespace-per-scan**: `scan-<slug(session_id)>` (`launcher/app/naming.py`), created if missing at the start of `/launch`.
   - **Env-defaults discovery** (`launcher/app/env_discovery.py`): if `AgentConfig.env_example_path` is set, a quick **local** shallow clone (`git clone --depth 1`, directly inside `launcher`'s own container — separate from, and ahead of, the actual build below) reads that file's `KEY=value` lines and fills in any keys missing from `AgentConfig.env_vars` with the repo's own declared defaults. Explicit `env_vars` always win — this only fills gaps, e.g. auto-picking up a third-party agent's expected `MODEL_NAME` default without the user having to read its source first. Failure here (bad ref, missing file) is non-fatal: logged and skipped, since it's a convenience, not a hard requirement.
   - **Build** (`launcher/app/build.py`): a `batch/v1` `Job` with two containers sharing an `emptyDir`: an `alpine/git` init container running `git clone --branch <git_ref> --depth 1 <git_repo_url> /workspace/src`, then a Kaniko container building `--context=dir:///workspace/src --dockerfile=<dockerfile_path>` and pushing to `--destination=<AGENT_IMAGE_REGISTRY>/agents/<agent_config_id>:<git_ref>` (`--insecure --skip-tls-verify`, since the local dev registry has no TLS). Build context is always the repo root — `dockerfile_path` is just where the Dockerfile itself lives, matching normal Docker semantics (`COPY` paths inside it are relative to the context root, not the Dockerfile's own location) rather than the earlier `build_context_path`-as-subdir design. A real `git clone` step (rather than Kaniko's own `git://` context support) was chosen so private repos can be supported later just by mounting a credential into the clone container, without touching the Kaniko step. `run_build()` blocks until the Job succeeds/fails/times out (default 300s) — a known MVP simplification; a background-job model would be needed at real scale.
   - **`launcher/app/host_alias.py`**: shared helper (also used for the CA-secret-reachability wrinkle in the MITM pivot above) — local Docker Compose container names (like `examples/git-server`, reachable from `launcher` via Docker's embedded DNS on the `kind` network) aren't resolvable by the cluster's own CoreDNS. `launcher` resolves the host itself (where it *is* resolvable) and pins it as a `hostAlias` — a no-op for hosts the cluster's own DNS already resolves (e.g. a real `github.com`).
   - **Pod launch** (`launcher/app/pod_manager.py`): builds the two-initContainer + agent-plus-`mitm-proxy`-sidecar Pod spec described in the MITM pivot section above — image = the pushed tag, `command` = `AgentConfig.entrypoint` if set, `env` = the (possibly env-defaults-merged) `env_vars` as-is (plus the CA-trust env vars) with **no platform-injected base_url/proxy config**, `resources` from `AgentConfig.resources`, and a `containerPort` for `api_port` if set. Pod gets labels (`app=agent-scanner-target`, `agent-config-id=<id>`).
   - **Auto-exposure** (`pod_manager.ensure_agent_service`): if `AgentConfig.api_port` is set, `launcher` creates a `NodePort` Service selecting the Pod by those same labels (idempotent — reuses an existing one on relaunch) and reads back the allocated `nodePort`. It then patches the resolved, actually-reachable address (`http://<k8s-node-container-name>:<nodePort>`) into `AgentConfig.api_config.url` or `.langgraph_config.base_url` (host/port replaced, any existing path preserved) via `PUT /agent-configs/{id}` — this is what used to be a manual `kubectl expose` + config-edit step (still documented below as the fallback for agents launched without `api_port` set).
   - **`POST /launch {campaign_id}`** orchestrates all of the above and records `agent_namespace`/`agent_pod_name`/`build_job_name`/`built_image` on the `Campaign`. **`POST /stop/{campaign_id}`** deletes the whole namespace (cascades: Job + Pod + mitm-proxy sidecar + the auto-created Service all gone in one call — a real isolation boundary given the tested agent may end up doing something genuinely hostile) and clears those fields. **`GET /status/{campaign_id}`** reports build/Pod status.
2. Local MCP servers inside the agent's own Pod are untouched by the platform (same reasoning as before: their tool-call traffic still flows through the same LLM conversation `proxy` already intercepts).
3. **`launcher/app/repo_inspect.py`** (git introspection only — no k8s/build involved): backs the `AgentConfigs` web UI's creation wizard, called *before* any `AgentConfig` exists yet. `list_branches` (`git ls-remote --heads`, no clone needed) and `inspect_repo` (a shallow clone of one chosen branch, same approach as `env_discovery.py`, walking the tree for `Dockerfile`/`*.Dockerfile` and `.env.example`/`.env.*.example` candidates, parsing every `.env.example` candidate found immediately) back `POST /repo/branches` and `POST /repo/inspect`. Unlike `env_discovery.py` (which silently skips a missing/bad env file since that's a soft convenience during a real launch), both of these **raise** on failure — giving the user clear feedback that a URL/branch/token is wrong is this endpoint's entire purpose. The web wizard: step 1 collects `git_repo_url`/`git_access_token` and loads branches; step 2 (informed by `inspect_repo` for the chosen branch) lets the user *pick* `git_ref`/`dockerfile_path`/`env_example_path` from what's actually in the repo instead of typing them blind, prefilling `env_vars` from the chosen `.env.example`. Editing an existing `AgentConfig` skips the wizard (a flat form, same fields, no re-discovery).

`entrypoint`/`resources` (CPU/memory) are intentionally **not** exposed in the web form at all (create or edit) — the user's view is that these belong in the Dockerfile/image itself, not a platform-level override made through this UI. They remain valid `AgentConfig` fields for API/curl use; editing an existing config that already has them set (e.g. via the API) carries them through unchanged rather than clobbering them, since the UI just never renders inputs for them.

### Cluster prerequisites (documented, not automated)

A reachable k8s cluster with a registry both the build Job can push to and the kubelet can pull from. Local dev uses the standard `kind`-with-local-registry recipe (a `registry:2` container on the `kind` Docker network, `kind` created with a `containerdConfigPatches` mirror pointing at it) — see `docs/running-locally.md` for the exact commands. `launcher`/`interactor` reach the cluster via a kubeconfig using the cluster's **internal** address (`kind get kubeconfig --internal`, e.g. `https://agent-scanner-control-plane:6443`) and join the `kind` Docker network so that address resolves.

> **Security note**: `launcher` holds a kubeconfig for the target cluster, which for a local `kind` setup is typically cluster-admin. This is an inherent cost of a feature that builds/launches workloads from a web request, not an accident. Acceptable for a local research/lab deployment; a shared/production deployment would want a scoped `ServiceAccount`/`Role` instead. `interactor` holds no kubeconfig at all — it only ever talks to the tested agent's own HTTP surface (`api`/`langgraph` mode), never the Kubernetes API directly.

> **`api`/`langgraph`-mode reachability**: a Pod's ClusterIP is **not** routable from `interactor`'s Docker Compose container (confirmed during verification — the two live on different network layers: Compose's Docker bridge vs. the cluster's Pod CNI). `launcher` handles this automatically when `AgentConfig.api_port` is set — see the "Auto-exposure" bullet above, a `NodePort` Service gets created and its resolved address patched into the config. For an `AgentConfig` launched without `api_port` set, the same thing can still be done manually: `kubectl expose pod <pod> --type=NodePort --port=<port> --selector=app=agent-scanner-target`, then set `api_config.url`/`langgraph_config.base_url` to `http://<kind-node-container-name>:<nodePort>` by hand.

## Phase 7 — Interactor LLM

`interactor` service (FastAPI + httpx + the LiteLLM client). `POST /run {campaign_id, max_turns}`. **`cli` mode has been removed** (was: a persistent Kubernetes pod-exec session, `kubernetes.stream.stream(...connect_get_namespaced_pod_exec...)`, writing turns to stdin) — only `api` and `langgraph` remain, both of which talk to the agent's own HTTP surface rather than the Kubernetes API directly, so `interactor` no longer needs a kubeconfig at all:

- Resolves the campaign's `AgentConfig` (must have `interaction_mode != none`) and `interactor_llm_model_id` (an `LLMModel`, called directly via `interactor/app/llm_client.py`'s LiteLLM client — never through `proxy`, mirroring the generator's approach).
- **Persona, this iteration**: only a legitimate, ordinary user is driven (`interactor/app/main.py:_build_persona_prompt`) — built from `AgentConfig.agent_purpose` (what the agent is for) and `Campaign.user_instruction` (what this user is allowed/told to do), both entered via the web UI. `InteractorPersona.ATTACKER` still exists in the schema for a later iteration but `interactor` does not currently branch on it — the "attacker" red-teaming persona described in the original Phase 7 design is deferred, not implemented.
- Each turn: asks the persona LLM to write the next message given the transcript so far (plain text, not the OpenAI message-list format — a simpler prompt-and-transcript loop was chosen over full stateful chat history for this MVP), sends it to the target agent over the configured channel, appends the reply, and checks `control-api`'s `/events?session_id=...&success_detected=true` to stop early.
- **`api` mode** (`interactor/app/target_client.send_via_api`): fully configurable REST wire contract via `AgentConfig.api_config`: `request_body_template` (arbitrary JSON with a `"{{message}}"` placeholder, recursively substituted — `{"query": "{{message}}"}`, nested objects, etc. all work) POSTed/GETed to `url`, and `response_field` (a dot-path into the JSON response, e.g. `"reply"` or `"data.0.text"`, numeric segments index into lists) to extract the reply. Defaults to the simple `{"message": ...}` / `"reply"` shape when unset, for backward compatibility. `headers` is an optional dict for auth tokens etc. Falls back to the raw response body if extraction fails. See the reachability note under Phase 6 above.
- **`langgraph` mode** (`interactor/app/target_client.LangGraphSession`): talks the LangGraph Platform / LangGraph API SDK's REST surface directly, for agents built with the LangGraph framework. `AgentConfig.langgraph_config = {"base_url", "assistant_id", "api_key" (optional, sent as `X-Api-Key`)}`. One persistent **thread** for the whole `/run` call (`POST {base_url}/threads` on start), each turn sent as `POST /threads/{thread_id}/runs/wait` with `{"assistant_id": ..., "input": {"messages": [{"role": "user", "content": <text>}]}}`, reply extracted as the last `assistant`/`ai`-role message in the returned `messages` array. `DELETE /threads/{thread_id}` on close (best-effort). Verified against `examples/langgraph-customer-support` — a real agent served by the real `langgraph dev` local API server (not a hand-rolled stand-in), which happens to expose exactly this REST surface natively; see "Real end-to-end case study" in `docs/running-locally.md`.

## Example agents and the removal of mock LLMs

Earlier iterations used hand-rolled OpenAI-compatible stub servers
(`mock-llm`, `mock-generator-llm`, `mock-persona-llm`, `mock-langgraph-agent`)
so the platform could be exercised end to end without a real API key. These
have been **removed entirely** — every LLM call in the platform (the tested
agent's own traffic, `generator`, `interactor`, and the example agents) now
goes through a real OpenAI-compatible provider, configured once via
`LLM_PROVIDER_BASE_URL`/`LLM_PROVIDER_API_KEY`/`LLM_PROVIDER_MODEL` in
`.env` (any OpenAI-compatible endpoint works, including free/cheap/
self-hosted ones — see `docs/running-locally.md`). The consequence worth
naming explicitly: results are no longer deterministic. Whether an injected
instruction actually gets complied with now depends on the real model's own
susceptibility, which is the genuine point of a security-testing platform —
a scripted mock that always complies proves the *mechanism* works but says
nothing about real-world risk.

`examples/langgraph-customer-support` is the platform's primary case study:
a real agent built with the actual `langgraph` framework (`create_react_agent`,
served by the real `langgraph dev` local API server), with tools
(`look_up_order`, `issue_refund`, `cancel_order`) that move real (simulated)
money and a system prompt instructing it to always look up an order before
refunding it. A seeded `customer-support-refund-hijack` template tries to
make it skip that check. See "Real end-to-end case study" in
`docs/running-locally.md` for the full walkthrough: `interactor` plays an
ordinary customer, the injection rides along inside that traffic via MITM,
and `control-api` logs whether the real model complied.

## Roadmap beyond Phase 1

| Phase | Deliverable | Status |
|---|---|---|
| 2 | Attack generator (LLM-based): attack-class prompt library, LLM-driven generation/mutation, adaptive scenarios | **shipped** |
| 3 | Detection hardening: classic-web-vuln signatures (XSS/SSRF/RCE/path-traversal/SQLi) in tool arguments + XSS echo-back | **shipped** |
| 4 | Web UI + scan configuration | **shipped** |
| 5 | Anthropic `/v1/messages` support + streaming response injection | not started |
| 6 | Agent launcher & containerization | **shipped** |
| 7 | Interactor LLM | **shipped** |
| 8 | Skills support: injection templates targeting Skill invocation, indirect-injection-via-Skill-content detection | not started |
| 9 | Fuzz engine: bandit-driven seed selection, LLM-mutation operators, LLM-judge oracle, one-shot direct only | **shipped** |
| 10 | Injection tree: per-tool-call A/B branching against a real backbone conversation, indirect only, mode-agnostic (`api`/`langgraph`) | **shipped** |

Only Phase 5 (Anthropic + streaming injection) and Phase 8 (Skills) remain. Neither requires
reworking the schema/API built so far.
