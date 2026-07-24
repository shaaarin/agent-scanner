# Architecture

## Phase 1 — LLM Proxy MVP [transport revised — see "MITM pivot" below]

Two services:

- **`proxy`** (mitmproxy addon, see "MITM pivot" below for how traffic
  actually reaches it): the interception point. On each intercepted
  `.../chat/completions` flow:
  1. Reads `SESSION_ID` from its own environment (one sidecar per Pod, set
     by `launcher`).
  2. Polls `control-api` (`GET /campaigns/active?session_id=...`, 2s TTL
     in-memory cache) for the active injection campaign bound to that
     session.
  3. If the campaign's template targets `user_message`, `tool_result`, or
     `system_prompt`, mutates the matching message in the request body
     (append/prepend/replace) before forwarding upstream.
  4. Forwards the (possibly mutated) request to whatever real upstream the
     tested agent's own connection was headed to — mitmproxy discovers this
     per-connection, `proxy` never needs to resolve it itself.
  5. For non-streamed responses: if the template targets
     `assistant_response`, mutates the response (either text content, or — if
     the payload parses as `{"name": ..., "arguments": ...}` — splices in a
     fabricated tool call). Runs the detector against the (possibly mutated)
     response and logs a `TrafficEvent`.
  6. For streamed responses (`"stream": true`): passes SSE chunks through to
     the client **unmodified** (via mitmproxy's native `flow.response.stream`
     callback) while reassembling them in memory to run the same detector.
     **Response injection is not supported for streaming requests in this
     MVP** — logging/detection only.
  7. Every request and response is logged to `control-api` via
     `POST /events`, fire-and-forget — a `control-api` outage never breaks
     the proxied call.

- **`control-api`** (FastAPI + SQLModel/SQLite): the control plane and single
  source of truth for `InjectionTemplate`, `Campaign`, and `TrafficEvent`.
  Also the backend for the future web UI and attack generator.

The body-transformation/detection modules (`openai_provider.py`,
`injector.py`, `detector.py`, `vuln_signatures.py`) are transport-agnostic —
they only ever touch plain `dict` request/response bodies, never an HTTP
request/response object directly. This is what made the MITM pivot (below)
a transport-layer rewrite rather than a logic rewrite.

### Data model

- **`InjectionTemplate`**: `target` (`user_message` | `tool_result` |
  `assistant_response` | `system_prompt`), `mode` (`append` | `prepend` |
  `replace`), `payload`, `success_indicator` (regex), `success_indicator_field`
  (`tool_name` | `tool_arguments` | `response_text`), `tags`.
- **`Campaign`**: binds a template to a `session_id`, `status`
  (`active`/`paused`/`stopped`), `injection_rate` (0.0–1.0 probability per
  eligible exchange). Only one campaign may be `active` per `session_id`.
- **`TrafficEvent`**: one row per intercepted request/response, tagging
  `injected`, `injection_target`, `success_detected`, and a truncated
  `raw_excerpt` for audit.

### Provider support

Only OpenAI's `/v1/chat/completions` format is implemented
(`proxy/app/openai_provider.py`). The injection/detection logic
(`injector.py`, `detector.py`) is written against a small functional
interface (`inject_request`, `inject_response`, `iter_tool_calls`,
`get_response_text`) so an Anthropic `/v1/messages` provider module can be
added later (Phase 5) without touching the routing logic in `main.py`.

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

A new `generator` service (FastAPI + httpx). It never touches `proxy`'s runtime path — it only creates `InjectionTemplate` rows via `control-api`, which `proxy` already knows how to consume.

- **`generator/app/prompts.py`**: one system prompt per attack class (`tool_call_hijack`, `sandbox_escape`, `xss_via_tool_arg`, `ssrf_via_tool_arg`, `rce_via_tool_arg`, `idor_via_tool_arg`, `sqli_via_tool_arg`), each ending in a shared strict-JSON response-shape instruction matching `InjectionTemplate`'s fields. `MUTATION_PROMPT`/`ADAPT_PROMPT` use `__MARKER__`-style `str.replace()` substitution rather than `str.format()`, since the embedded JSON example in the shared response-shape text contains literal braces that broke `.format()` (hit and fixed during verification).
- **`generator/app/llm_client.py`**: calls the configured LLM via **LiteLLM**'s unified `acompletion()` interface (not a hand-rolled OpenAI-format httpx call) — works against any provider LiteLLM supports, picked via the `LLMModel`'s `provider_type`/`model`, with `base_url` passed through as a custom `api_base`. Never through `proxy`, since the generator's own LLM calls are not the system under test. Parses/validates the assistant's JSON response.
- **`generator/app/main.py`** routes:
  - `POST /generate {attack_class, llm_model_id, target_context}` → calls the LLM with the attack-class prompt, creates the resulting `InjectionTemplate` (tagged `attack_class:<x>`, `generator:llm`).
  - `POST /mutate {template_id, llm_model_id, strategy_hint, count}` → fetches the existing template, asks the LLM for `count` variants, creates each (tagged `mutated_from:<id>`).
  - `POST /adapt {campaign_id, llm_model_id?}` → fetches the campaign's current template plus its recent unsuccessful `TrafficEvent`s (`GET /events?campaign_id=...&success_detected=false`); `llm_model_id` defaults to the campaign's `generator_llm_model_id` if not given explicitly; asks the LLM to reason about likely failure and propose a different variant, creates it (tagged `adapted_from:<id>`, `campaign:<id>`).
- Verified against a real provider (see `docs/running-locally.md` — register an `LLMModel` from `.env`'s `LLM_PROVIDER_*` creds) for all three endpoints; there is no mock LLM stand-in for this service.

### Fuzz engine (one-shot jailbreak/injection fuzzing, direct only)

Extends the same `generator` service with an autonomous, budget-driven search loop over
`InjectionTemplate` variants — a `FuzzRun` (`control-api/app/models.py`) — instead of manually
triggering `/generate`/`/mutate`/`/adapt` one at a time. Built after a literature review of
GPTFuzzer, PAIR/TAP, AgentVigil, and InjecAgent/AgentDojo, which converge on: a persisted log
of attempts, a seed pool + mutation operators, a bandit-style seed-selection strategy, and a
judge/oracle scoring each attempt.

**Direct only** (`injection_target=user_message`) — `control-api/app/api/fuzz_runs.py:
create_fuzz_run` rejects any other target with 400. Indirect (`tool_result`) fuzzing moved
entirely to the "Injection tree" mechanism below once it became clear real tool-calling agents
need the whole subsequent run judged, not one exchange, to tell whether an injection worked —
see that section for why.

- **`control-api`**: two new tables, `FuzzRun` (binds to a `base_campaign_id` for
  session/agent/LLM config, `mode` is `adaptive`/`non_adaptive`, `seed_template_ids`/
  `max_iterations`/`stop_on_success`/`status`) and `FuzzAttempt` (one row per iteration: seed
  template "arm", the mutated template actually tried, the ephemeral delivery `Campaign`,
  detector + judge verdicts, combined `reward`). New `/fuzz-runs` router, same
  CRUD/list-with-filters shape as the existing routers.
- **`generator`**: `bandit.py` (pure UCB1 `select_seed`, same exploration/exploitation strategy
  GPTFuzzer/AgentVigil use), `seed_corpus.py` (a small hand-authored jailbreak seed library,
  bootstrapped into `control-api` on first use per `injection_target` — hand-written rather
  than LLM-generated, since GPTFuzzer found diverse human seeds outperform LLM-authored ones
  as a starting pool), `judge.py` (LLM-as-judge oracle: classifies whether the agent's reply
  actually complied with the injected goal — needed because the existing regex/signature
  `detector` only recognizes tool-call/pattern-shaped success, not a plain jailbreak that
  produced disallowed prose with no tool call), `mutators.py` (named non-adaptive operators —
  rephrase/expand/shorten/encode_obfuscate/persona_shift — reusing `prompts.py`'s existing
  `MUTATION_PROMPT` substitution convention rather than new templates), and `fuzz_engine.py`
  (the orchestration loop, run as a background `asyncio` task via `POST /fuzz/{id}/start`,
  cooperatively stoppable via `POST /fuzz/{id}/stop`).
- **Delivery mechanism, deliberately unchanged**: each iteration creates a new
  `InjectionTemplate` + a fresh ephemeral `Campaign` (same session/agent/LLM config as the
  `base_campaign`, reusing `campaigns.py`'s existing "activating a campaign auto-pauses
  siblings for that `session_id`" behavior so `Campaign.template_id`'s immutable-after-creation
  convention never needs to be touched) and calls `interactor`'s existing `/run
  {max_turns: 1}` — `proxy`'s `injector`/`detector` need zero changes, since a `FuzzRun` is
  just a fast-moving source of ordinary templates/campaigns feeding the same Phase 1-3
  interception path.
- Because every iteration's full state is a durable `FuzzAttempt` row, pausing a run and
  inspecting/resuming it later requires no special snapshot mechanism — it falls out of the
  data model for free. See `docs/running-locally.md`'s "Using the fuzz engine" for the curl
  walkthrough (direct, adaptive/non-adaptive).

### Injection tree (indirect fuzzing: per-tool-call A/B branching)

Real tool-calling agents often run many internal tool calls — and, for `langgraph`-mode agents
especially, an ongoing human-in-the-loop dialogue — to complete one task. A single injected
exchange (what the one-shot engine above does) can't tell you whether a poisoned tool result
actually changed the agent's behavior; that's only visible from the agent's *entire* subsequent
run. So indirect (`tool_result`) fuzzing works differently: walk one real, clean conversation
(the **backbone**) forward. At every point the agent receives a new tool result (a
**checkpoint**), fuzz it — several mutated payloads, bandit + mutation, reusing the one-shot
engine's machinery — each run to the agent's own natural completion (or until success is already
confirmed), then compared against what the backbone itself actually did from that same point.

**The realization that made this tractable**: a single *external* exchange (one `interactor` <->
agent call) can contain many *internal* tool calls, each a separate request the agent makes to
its own LLM backend — and `proxy` already intercepts every one of those, regardless of
`interaction_mode` (`api` or `langgraph`) and regardless of how many external turns it took to
produce them. So checkpoint discovery doesn't need to happen at the external-turn level at all —
it's read straight back out of `control-api`'s own `TrafficEvent` log for a campaign. This is
what makes the feature **mode-agnostic** (works the same for `api` and `langgraph`), and is what
let a much simpler mechanism replace an earlier design that needed careful per-turn campaign
swapping and real LangGraph-thread continuity to work at all.

- **`proxy`** (one small additive change): `Campaign` gained `inject_at_occurrence: Optional[int]`
  (1-indexed). `proxy/addon.py`'s `InjectionAddon` tracks an in-memory
  `{(session_id, campaign_id): count}` counter of target-eligible exchanges seen so far
  (`openai_provider.has_matching_message`/`injector.is_eligible_for_request_injection`, factored
  out of the existing `inject_request` check) and injects only when the counter equals
  `inject_at_occurrence`, ignoring `injection_rate` — falls back to the original
  `random.random() < injection_rate` behavior when unset, so every existing campaign is
  unaffected. This lets one ephemeral `Campaign` stay active for a probe attempt's **entire**
  run (however many external turns that takes) with no mid-run PATCHing: `proxy` naturally
  passes occurrences before and after the targeted one through clean.
- **`interactor`**: a new resumable single-turn primitive, `POST /session/turn
  {campaign_id, session_token, message}`, alongside the existing (unchanged) `/run`.
  `message: null` lets interactor's own persona LLM decide the next line (factored out of
  `/run`'s loop into `_generate_persona_message`), so it keeps playing a real user turn-by-turn
  for as long as the caller keeps calling this endpoint — needed because not every tested agent
  finishes in one exchange. `session_token` is a real LangGraph `thread_id` for `langgraph` mode
  (`target_client.py:LangGraphSession.start()` now accepts an existing one and skips creating a
  new thread); for `api` mode it's a no-op (`send_via_api` has no session-continuity primitive
  today, an existing platform limitation this doesn't attempt to fix).
- **`control-api`**: `TreeRun` (the search config: `base_campaign_id` — must be `status=active`
  with `injection_rate=0.0`/`inject_at_occurrence=None` (validated at `/tree/{id}/start`), a
  genuinely clean backbone that `proxy` is actually considering for this `session_id` —
  `max_backbone_turns`/`max_probe_turns`/`max_checkpoints`/`attempts_per_checkpoint`/`mode`),
  `ConversationNode` (one backbone external turn, just enough to replay the same message
  sequence for a probe), and `InjectionProbe` (one fuzzing attempt at one checkpoint occurrence,
  holding its full `trajectory`, `stopped_reason`, detector+judge verdict, and a structural
  `divergence_detail` against the backbone's own real continuation). New `/tree-runs` router.
- **`generator/app/tree_engine.py`**: reuses `bandit.py`/`mutators.py`/`judge.py`/
  `seed_corpus.py` unchanged from the one-shot engine (`seed_corpus.ensure_seed_pool` factored
  out for both to share), plus a new `checkpoints.py` (`checkpoints_from_events`, parses a
  campaign's `TrafficEvent.raw_excerpt` bodies for newly-appeared `role: tool` messages).
  Phase A walks the backbone via `/session/turn` until a turn adds no new tool-result events (a
  documented simplification of "the agent believes it's done") or `max_backbone_turns`. Phase B,
  per checkpoint: create a fresh ephemeral `Campaign` with `inject_at_occurrence` set to that
  checkpoint's occurrence number, replay the backbone's own recorded messages turn-by-turn (
  falling back to persona-driven `message: null` if a poisoned run needs more human-in-the-loop
  turns than the backbone did), score with the existing detector + judge, and stop early the
  moment either confirms success. Runs as a background `asyncio` task
  (`POST /tree/{id}/start`/`POST /tree/{id}/stop`, same pattern as the one-shot engine).
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

**Scan progress view** (`web/src/pages/ScanDetail.tsx`, route `/campaigns/:id`):
a per-scan dashboard — stat cards (exchanges/injected/successes), agent
launch controls (calls `launcher` directly via `VITE_LAUNCHER_URL`, CORS-enabled
for this same reason) with live-polled status, a "Run interactor" button
(calls `interactor` via `VITE_INTERACTOR_URL`) rendering the resulting
transcript as chat bubbles, and `web/src/components/FlowTimeline.tsx` — groups
`TrafficEvent`s by `flow_id` into request/response pairs, live-polled every
3s, with injected/success badges and `detector.evaluate()`'s JSON `detail`
parsed into chips (indicator match, per-vuln-class signature findings).

Two new `control-api` entities back the scan-configuration screens:

- **`LLMModel`** (renamed from an earlier `ProviderCredential` design once it became clear each role needed its own explicit choice, not a shared reusable credential): `name`, `provider_type` (`openai`/`anthropic`), `base_url`, `api_key`, `model` (passed to LiteLLM, e.g. `"gpt-4o-mini"` or `"claude-3-5-sonnet-latest"`). Stored in **plain text** — an explicitly accepted MVP tech-debt item, not a long-term security posture. Used for the platform's own two outbound LLM roles, each with its **own explicit FK**, not a shared "credential" reused by role:
  - the interactor's model: `Campaign.interactor_llm_model_id`;
  - the generator's model: `Campaign.generator_llm_model_id`.

  The tested agent's own model is *not* an `LLMModel` row at all — see the MITM pivot above: it's just whatever real provider config is in `AgentConfig.env_vars`, intercepted transparently rather than resolved by the platform. (An earlier iteration added `AgentConfig.target_llm_model_id` for this; removed when the MITM pivot made it unnecessary — `proxy` no longer needs to know the target upstream in advance.)
- **`AgentConfig`**: `git_repo_url`, `git_ref` (default `main`), `git_access_token`
  (optional — a Personal Access Token for private HTTPS repos, embedded
  into the clone URL as `https://<token>@host/...` by `launcher/app/git_auth.py`,
  the convention GitHub/GitLab/Bitbucket all accept; no-op for the platform's
  own `git://` test servers or `ssh://` remotes. Plain text, same accepted
  MVP tech-debt posture as `LLMModel.api_key` — see the security note in
  `git_auth.py`'s docstring about clone-failure logs), `dockerfile_path`
  (default `"Dockerfile"` — path to the Dockerfile itself, relative to the
  repo root; the build context is always the repo root, matching normal
  Docker semantics), `env_example_path` (optional — a `.env.example`-style
  file in the repo that `launcher` reads to auto-fill any `env_vars` keys
  not already set, see Phase 6), `api_port` (optional — if the agent
  listens on one, `launcher` auto-exposes it via a `NodePort` Service, see
  Phase 6), `entrypoint` (optional command override), `env_vars` (JSON dict
  — this is where the agent's real LLM provider config lives, as plain env
  vars, exactly like a real deployment), `resources` (optional
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
  allowed/told to do; only `benign_user` is currently honored, see Phase 7)
  — additive, Phase 1 rows are unaffected.

New routes: `/llm-models` (list responses mask `api_key`; only `GET /llm-models/{id}`
returns it in full) and `/agent-configs`, both standard CRUD.

> **No DB migrations yet** (`SQLModel.metadata.create_all()` only adds
> missing tables, it doesn't alter existing ones): after a schema change,
> a dev environment with a pre-existing `control-api-data` volume needs
> `docker volume rm agent-scanner_control-api-data` before the next
> `docker compose up`. Accepted as MVP tech debt; revisit with Alembic if
> this needs to survive real production data.

## Phase 3 — Detection hardening

Extends `proxy/app/detector.py` beyond the Phase 1 regex-only `success_indicator` check, without any schema change (`TrafficEvent.detail` was always a free-text `str`; it now holds a JSON-encoded string instead of a plain sentence).

- **`proxy/app/vuln_signatures.py`**: regex signature sets for five vuln classes — `ssrf` (cloud metadata endpoint, localhost/private-IP URLs, `file://`), `sqli` (UNION SELECT, tautology `OR 1=1`, comment/drop-table sequences), `rce` (shell metacharacter chains, `` `cmd` ``/`$(cmd)`), `path_traversal` (`../`, `/etc/passwd`), `xss` (`<script>`, `on*=` handlers, `javascript:`).
- **`detector.scan_vuln_signatures(request_body, response_body)`**: scans every tool call's `arguments` in the response against all signature sets, and separately checks for **XSS echo-back** — a `role: tool` message earlier in the request's conversation history that looked like XSS reappearing verbatim in the assistant's response text (a proxy for "rendered unescaped downstream").
- **`detector.evaluate(...)`** combines this with the existing `check_success` (renamed usage, same regex logic): `success_detected` is true if *either* the campaign's own `success_indicator` matches *or* any signature fires. `detail` becomes `{"indicator_match": "...", "vuln_signatures": [{"class": "ssrf", "field": "tool_arguments", "tool": "...", "snippet": "..."}]}`.
- Wired into both `_proxy_non_streaming` and `_proxy_streaming` in `main.py`, same hook points as Phase 1.

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
