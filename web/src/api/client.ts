function makeClient(baseUrl: string) {
  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const res = await fetch(`${baseUrl}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers ?? {}),
      },
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status} ${res.statusText}: ${text}`);
    }
    if (res.status === 204) {
      return undefined as T;
    }
    return (await res.json()) as T;
  }

  return {
    get: <T>(path: string) => request<T>(path),
    post: <T>(path: string, body: unknown) =>
      request<T>(path, { method: "POST", body: JSON.stringify(body) }),
    put: <T>(path: string, body: unknown) =>
      request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
    patch: <T>(path: string, body: unknown) =>
      request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
    delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  };
}

// control-api: campaigns, templates, credentials, agent-configs, events.
export const api = makeClient(import.meta.env.VITE_CONTROL_API_URL ?? "http://localhost:8000");

// launcher: builds/launches the tested agent as a k8s Pod (see docs/architecture.md
// Phase 6). Only reachable if the deployment wires up the launcher's host-published
// port -- see the networking caveat in docs/running-locally.md.
export const launcherApi = makeClient(import.meta.env.VITE_LAUNCHER_URL ?? "http://localhost:8400");

// interactor: drives a conversation with the tested agent (see docs/architecture.md
// Phase 7). Same networking caveat as launcherApi.
export const interactorApi = makeClient(import.meta.env.VITE_INTERACTOR_URL ?? "http://localhost:8500");

// generator: attack-class generation/mutation/adaptation, plus the one-shot fuzz
// engine (/fuzz/{id}/start|stop) and the injection tree (/tree/{id}/start|stop) --
// see docs/architecture.md's "Fuzz engine" and "Injection tree" sections.
export const generatorApi = makeClient(import.meta.env.VITE_GENERATOR_URL ?? "http://localhost:8300");
