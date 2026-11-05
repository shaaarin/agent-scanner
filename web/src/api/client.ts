function makeClient(baseUrl: string) {
  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const isFormData = options.body instanceof FormData;
    const res = await fetch(`${baseUrl}${path}`, {
      ...options,
      // Сессионная cookie ставится после входа по логину и паролю и должна
      // уходить с каждым запросом (в dev API на другом порту -- кросс-домен).
      credentials: "include",
      headers: {
        ...(!isFormData ? { "Content-Type": "application/json" } : {}),
        ...(options.headers ?? {}),
      },
    });
    if (!res.ok) {
      // Сессия истекла или входа не было: сообщаем приложению централизованно,
      // чтобы показался экран входа даже из фоновых опросов (логи сканов,
      // события), которые глотают ошибки. Запросы /auth/* -- не повод: их 401
      // означает «ещё не вошли» и обрабатывается AuthContext'ом напрямую.
      if (res.status === 401 && !path.startsWith("/auth/")) {
        window.dispatchEvent(new CustomEvent("auth:unauthorized"));
      }
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
//
// По умолчанию адрес выводится из адреса страницы: дашборд, открытый по IP
// стенда или через SSH-туннель, обращается к API на опубликованном порту
// того же хоста (8000) -- пересборка при смене адреса не нужна. Явный
// build arg VITE_CONTROL_API_URL имеет приоритет. Launcher браузер не видит:
// разбор репозитория в мастере агента control-api проксирует сам
// (control-api/app/api/repo.py).
const pageHost = window.location.hostname || "localhost";

export const CONTROL_API_URL =
  import.meta.env.VITE_CONTROL_API_URL || `http://${pageHost}:8000`;

export const api = makeClient(CONTROL_API_URL);
