# agent-scanner

Security research platform for testing web apps that integrate LLMs with Tool
Calling: prompt-injection attacks against tool-calling logic (unauthorized
tool invocation, parameter tampering, sandbox escape), and using tool calling
as a trigger for classic web vulns (XSS/SSRF/RCE/IDOR/SQLi) reachable through
tool arguments or tool results.

**Read `docs/architecture.md` and `docs/running-locally.md` before making
non-trivial changes.** This file is a map, not a replacement for them.

## How a tested agent attaches — read this first

**Zero changes to the tested agent.** Its own real LLM config
(`OPENAI_API_KEY`, `OPENAI_BASE_URL`, whatever it already has) is left
completely untouched. The platform intercepts its outbound HTTPS
transparently: each agent Pod gets a CA trust-store overwrite
(`ca-trust-setup` initContainer) plus an iptables redirect (`net-setup`
initContainer) into an `mitm-proxy` sidecar that terminates and re-signs the
connection on the fly (`proxy/addon.py`, mitmproxy). This **replaced** an
earlier explicit-`base_url` design — if you see old docs/plans/commits
describing "point `OPENAI_BASE_URL` at the proxy," that's stale.

## Services (each its own container)

| Service | Role |
|---|---|
| `control-api` | FastAPI + SQLModel/SQLite. Single source of truth: `InjectionTemplate`, `Campaign`, `TrafficEvent`, `LLMModel`, `AgentConfig`. |
| `proxy` | mitmproxy addon (`addon.py`), not a hand-rolled reverse proxy. The actual interception/injection/detection point. |
| `launcher` | Builds a tested agent's image in-cluster (git-clone + Kaniko) and launches it as a k8s Pod with the MITM sidecar attached. No Docker socket/CLI — talks to an external cluster via a mounted kubeconfig. |
| `interactor` | Drives a conversation with the tested agent (`api`/`langgraph` modes only — `cli` mode was removed) as a persona LLM, via LiteLLM. |
| `generator` | LLM-authored `InjectionTemplate` generation/mutation/adaptation, via LiteLLM. |
| `web` | React/Vite dashboard. **UI copy is in Russian** — keep new UI text Russian to match. |
| `control-api-mitm-bridge` | `alpine/socat` TCP forwarder. Exists solely so `control-api` itself doesn't have to join the `kind` Docker network (see gotcha below). |
| `launcher-mitm-bridge` / `interactor-mitm-bridge` | `alpine/socat` TCP forwarders that own `launcher`/`interactor`'s host-published port (`8400`/`8500`) instead of those services publishing it themselves (see gotcha below). |

`examples/` holds test/target agents (`stub-agent`, `echo-agent`,
`langgraph-customer-support`, `git-server`) used to exercise the platform —
they are not started by `docker compose up` by default; build/run them
individually or serve them via `examples/git-server` when testing the
launcher's git-clone+Kaniko path.

## Non-obvious conventions

- **No mock LLMs anywhere.** Every LLM call — the tested agent's own
  traffic, `generator`, `interactor`, example agents — goes through a real
  OpenAI-compatible provider configured via `.env`
  (`LLM_PROVIDER_BASE_URL`/`LLM_PROVIDER_API_KEY`/`LLM_PROVIDER_MODEL`).
  Results are non-deterministic by design: whether an injection lands
  depends on the real model's own resistance. Don't reintroduce a mock
  stand-in.
- **Plain-text credentials are accepted MVP tech debt**, not an oversight —
  `LLMModel.api_key`, `AgentConfig.git_access_token`, `AgentConfig.env_vars`
  are all stored unencrypted. Documented in `docs/architecture.md`, don't
  "fix" it as a drive-by.
- **No DB migrations.** `SQLModel.metadata.create_all()` only adds missing
  tables. After any `control-api/app/models.py` schema change:
  `docker compose down && docker volume rm agent-scanner_control-api-data`
  before the next `docker compose up`.
- **`AgentConfig` build flow**: clone → read `env_example_path` (if set,
  launcher does a quick local shallow clone to auto-fill missing `env_vars`
  from the repo's own declared defaults, explicit config always wins) →
  build `dockerfile_path` via Kaniko (context is always the repo root) →
  run with the merged `env_vars`, auto-exposing `api_port` via a
  launcher-created `NodePort` Service and patching the resolved address
  into `api_config.url`/`langgraph_config.base_url` automatically.
- **`git_access_token`** (PAT for private HTTPS repos) is embedded into the
  clone URL by `launcher/app/git_auth.py` — no-op for `git://`/`ssh://`.
  Known leak vector: a failed clone echoes the token-bearing URL into that
  init container's `kubectl logs`, documented not fixed.
- **CRUD pages in `web/`** (`AgentConfigs.tsx`, `Templates.tsx`,
  `LLMModels.tsx`, `Campaigns.tsx`) are dual-purpose create/edit forms
  (`editingId` state, PUT/PATCH when set). `LLMModel.api_key` edit field is
  left blank = "keep unchanged" (list endpoint only ever returns a masked
  value). `Campaign.session_id`/`template_id` are immutable once created
  (not in `CampaignUpdate`) — shown disabled in the edit form, not sent.

## Local dev

```
cp .env.example .env   # fill in LLM_PROVIDER_BASE_URL/API_KEY/MODEL
docker compose up --build control-api proxy web
```

`launcher`/`interactor` additionally need a **Kubernetes cluster** (the
platform builds/launches tested agents as Pods, not plain Docker
containers) — see `docs/running-locally.md` for the one-time local `kind`
cluster setup. If `kind`/`kubectl` aren't on `PATH` in this environment,
check `~/bin` first before assuming they need installing.

**No automated test suite exists.** Verification is live: bring up the
relevant `docker compose` services (and the `kind` cluster for
launcher/interactor changes), exercise the actual HTTP/k8s flow, check
`control-api`'s `/events` and `kubectl logs`/`get pods`. Match this pattern
for new changes rather than adding a test framework unprompted.

## Environment quirks (WSL2/Docker Desktop, this dev setup specifically)

- A service dual-homed on both the default Compose network and the `kind`
  network gets a **flaky host-published port** (connection reset/
  `ERR_EMPTY_RESPONSE`, works fine container-to-container). This is *why*
  `control-api-mitm-bridge` exists — `control-api` itself must stay off the
  `kind` network so its host port (hit constantly by the browser) stays
  reliable. `launcher`/`interactor` can't do that (they genuinely need
  `kind` for k8s API access), so instead each has its own
  `launcher-mitm-bridge`/`interactor-mitm-bridge` (`alpine/socat`,
  single-homed) that owns the host-published port (`8400`/`8500`) and
  forwards to the actual dual-homed service over the `default` network —
  same fix, aimed at the host side instead of the `kind` side. If a fresh
  `ERR_EMPTY_RESPONSE`/reset shows up again on one of these ports despite
  the bridge, fall back to driving requests via
  `docker compose exec <service> python3 -c "..."` instead of host curl to
  isolate whether it's this quirk recurring or a real app bug.
- `examples/git-server`'s attachment to the `kind` Docker network can
  silently drop after sitting idle — `docker compose restart git-server`
  fixes it. Not a code bug.
- Kaniko build context is **always the repo root**; `AgentConfig.dockerfile_path`
  is just where the Dockerfile lives, not a context subdir (matches normal
  `docker build -f` semantics).
