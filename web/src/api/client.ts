function makeClient(baseUrl: string) {
  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const isFormData = options.body instanceof FormData;
    const res = await fetch(`${baseUrl}${path}`, {
      ...options,
      headers: {
        ...(!isFormData ? { "Content-Type": "application/json" } : {}),
        ...(options.headers ?? {}),
      },
    });
    if (!res.ok) {
      const text = await res.text();
      // FastAPI отдаёт причину в {"detail": "..."} -- показываем её, а не сырой JSON.
      let detail = text;
      try {
        const parsed = JSON.parse(text);
        if (typeof parsed?.detail === "string") detail = parsed.detail;
      } catch {
        // не JSON -- оставляем текст как есть
      }
      throw new Error(`${res.status} ${res.statusText}: ${detail}`);
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
    postForm: <T>(path: string, body: FormData) =>
      request<T>(path, { method: "POST", body }),
    put: <T>(path: string, body: unknown) =>
      request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
    patch: <T>(path: string, body: unknown) =>
      request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
    delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  };
}

// Базовый URL нужен не только клиенту: выгрузки (SARIF, диалоги атак)
// открываются прямой ссылкой на эндпоинт, чтобы браузер скачал файл сам.
export const CONTROL_API_URL = import.meta.env.VITE_CONTROL_API_URL ?? "http://localhost:8000";

export const api = makeClient(CONTROL_API_URL);
export const launcherApi = makeClient(import.meta.env.VITE_LAUNCHER_URL ?? "http://localhost:8400");
