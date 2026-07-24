# agent-scanner

A testing platform for web applications that integrate LLMs with Tool Calling,
focused on prompt-injection attacks against tool-calling logic (unauthorized
tool invocation, parameter tampering, sandbox escape) and on using tool
calling as a trigger/proxy for classic web vulnerabilities (XSS, SSRF, RCE,
IDOR, SQLi) reachable through tool arguments or tool results.

Injection happens directly in LLM traffic — user messages, tool results, and
assistant responses — at an **LLM Proxy** layer, not by tampering with
infrastructure below the LLM conversation.

See [`docs/architecture.md`](docs/architecture.md) for the full design and
phased roadmap. Implemented so far: the LLM proxy/injection core, an LLM-based
attack generator, classic-web-vuln signature detection, the web UI, and a
Kubernetes-based agent launcher + interactor (agents are built from a git
repo in-cluster and run as Pods; only Anthropic-format support and Skills
support remain).

## How an agent attaches

**Zero changes.** A tested agent's own real LLM config — `OPENAI_API_KEY`,
`OPENAI_BASE_URL`, whatever it already has — is left completely untouched.
The platform intercepts its outbound HTTPS traffic transparently at the
network level: each agent Pod gets a CA trust-store overwrite plus an
iptables redirect into an `mitm-proxy` sidecar that terminates and re-signs
the connection on the fly (see `docs/architecture.md`'s "MITM pivot"
section for the full mechanism). The agent never needs to know the platform
exists.

## Quickstart

Every LLM call in this platform — the tested agent's own traffic, the
attack generator, the interactor, and any local example agent — goes
through a real OpenAI-compatible provider. There are no mock LLM stand-ins.
Copy `.env.example` to `.env` and fill in `LLM_PROVIDER_BASE_URL` /
`LLM_PROVIDER_API_KEY` / `LLM_PROVIDER_MODEL` (any OpenAI-compatible
endpoint works: OpenAI itself, OpenRouter, a self-hosted vLLM/Ollama server,
etc. — pick something cheap).

```
cp .env.example .env   # then edit it
docker compose up --build
```

This brings up the full platform: `control-api` (campaign/template/LLM-model
store), `proxy` (the MITM interception point, with classic-web-vuln
signature detection on tool arguments), `web` (the dashboard UI, at
`http://localhost:4173`), `generator` (the LLM-based attack generator), and
two real example agents (`stub-agent`, a minimal tool-calling script;
`customer-support-agent`, a real LangGraph-framework agent — see below) that
exercise the whole platform against your configured provider.

`launcher` and `interactor` additionally need a **Kubernetes cluster**
reachable via a kubeconfig — tested agents are built from a git repo
in-cluster (git-clone + Kaniko) and launched as Pods, not plain Docker
containers, so the MITM interception above has a real Pod network namespace
to work in. See [`docs/running-locally.md`](docs/running-locally.md) for the
one-time local `kind`-cluster setup this requires, and full walkthroughs of
every piece — including a complete real-world case study: a real LangGraph
customer-support agent (`examples/langgraph-customer-support`) with tools
that move real (simulated) money, launched in-cluster, driven by the
`interactor` LLM as an ordinary customer, and hijacked via an injected
prompt into issuing an unauthorized refund — all through the transparent
MITM path, with the agent never told the platform exists.
