// API 클라이언트 — 모든 화면이 이 함수만 쓴다. 오류는 {detail} 문구를 Error.message 로 던진다.
// 관리 화면은 localStorage 'axreview-admin-token' 이 있으면 X-Admin-Token 헤더로 보낸다 (backend .env ADMIN_TOKEN).

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function adminToken(): string | null {
  try {
    return localStorage.getItem("axreview-admin-token");
  } catch {
    return null;
  }
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string> | undefined) };
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  const tok = adminToken();
  if (tok) headers["X-Admin-Token"] = tok;
  const res = await fetch(path.startsWith("/") ? path : `/api/${path}`, { ...init, headers, body, credentials: "same-origin" });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = text;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    /* 그대로 둔다 */
  }
  if (!res.ok) {
    const detail = (data && typeof data === "object" && "detail" in (data as Record<string, unknown>))
      ? String((data as Record<string, unknown>).detail)
      : `요청 실패 (${res.status})`;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export const get = <T = unknown>(path: string) => api<T>(path);
export const post = <T = unknown>(path: string, json?: unknown) => api<T>(path, { method: "POST", json });
export const put = <T = unknown>(path: string, json?: unknown) => api<T>(path, { method: "PUT", json });
export const del = <T = unknown>(path: string, json?: unknown) => api<T>(path, { method: "DELETE", json });

/** 참여 기록 (공유·공유 유입·구독 창 열기 등). 실패해도 화면을 막지 않는다. */
export function track(kind: string, item = "", value = ""): void {
  post("engage", { kind, item, value }).catch(() => undefined);
}
