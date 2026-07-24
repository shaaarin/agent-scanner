# Self-hosted git:// server for verifying the launcher's git-clone-based
# build pipeline without depending on GitHub reachability/rate limits.
# Bakes examples/echo-agent's files into a real git repo at build time and
# serves it over the native git protocol (port 9418). Also serves
# examples/stub-agent's files as a second repo ("stub-agent") and
# examples/langgraph-customer-support's files as a third ("customer-support-agent")
# -- the latter is a REAL LangGraph agent (real framework, real LLM calls),
# used for the platform's primary real-world MITM + interactor case study:
# an agent with a normal-looking OPENAI_API_BASE/OPENAI_API_KEY env config
# and zero proxy-awareness, whose outbound HTTPS traffic gets transparently
# intercepted.
FROM alpine:3.20

RUN apk add --no-cache git git-daemon

WORKDIR /srv/git/echo-agent
COPY repo-content/ ./
RUN git init -b main \
    && git config user.email "test@agent-scanner.local" \
    && git config user.name "agent-scanner" \
    && git add -A \
    && git commit -m "initial commit"

WORKDIR /srv/git/stub-agent
COPY stub-agent-content/ ./
RUN git init -b main \
    && git config user.email "test@agent-scanner.local" \
    && git config user.name "agent-scanner" \
    && git add -A \
    && git commit -m "initial commit"

WORKDIR /srv/git/customer-support-agent
COPY customer-support-agent-content/ ./
RUN git init -b main \
    && git config user.email "test@agent-scanner.local" \
    && git config user.name "agent-scanner" \
    && git add -A \
    && git commit -m "initial commit"

EXPOSE 9418
CMD ["git", "daemon", "--reuseaddr", "--base-path=/srv/git", "--export-all", "/srv/git"]
