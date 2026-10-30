// API 클라이언트 — 모든 화면이 이 함수만 쓴다. 오류는 {detail} 문구를 Error.message 로 던진다.
// 관리 화면은 localStorage 'axreview-admin-token' 이 있으면 X-Admin-Token 헤더로 보낸다 (backend .env ADMIN_TOKEN).

export class ApiError extends Error {
  status: number;
  data: Record<string, unknown> | null; // detail 이 객체({message, …})일 때 그 객체 — 예: 구독 이메일 오타 제안
  constructor(status: number, message: string, data: Record<string, unknown> | null = null) {
    super(message);
    this.status = status;
    this.data = data;
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
  // X-Requested-With: 서버가 상태를 바꾸는 요청(POST·PUT·DELETE)에 요구한다 — 다른 사이트에서 보낸 위조 요청 차단 (backend/api/main.py)
  const headers: Record<string, string> = { "X-Requested-With": "axreview", ...(init.headers as Record<string, string> | undefined) };
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
  if (res.status === 428) {
    // 서버가 새 버전으로 바뀌었는데 이 탭은 예전 화면 — 한 번만 자동 새로고침 (무한 반복 방지)
    try {
      if (!sessionStorage.getItem("ax_reloaded")) { sessionStorage.setItem("ax_reloaded", "1"); window.location.reload(); }
    } catch { /* 저장소를 못 쓰면 안내 문구만 */ }
  }
  if (!res.ok) {
    const raw = data && typeof data === "object" ? (data as Record<string, unknown>).detail : undefined;
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      const obj = raw as Record<string, unknown>;
      throw new ApiError(res.status, String(obj.message ?? `요청 실패 (${res.status})`), obj);
    }
    throw new ApiError(res.status, raw !== undefined && typeof raw !== "object" ? String(raw) : `요청 실패 (${res.status})`);
  }
  return data as T;
}

export const get = <T = unknown>(path: string) => api<T>(path);
export const post = <T = unknown>(path: string, json?: unknown) => api<T>(path, { method: "POST", json });
export const put = <T = unknown>(path: string, json?: unknown) => api<T>(path, { method: "PUT", json });
export const del = <T = unknown>(path: string, json?: unknown) => api<T>(path, { method: "DELETE", json });

/** 참여 기록 (공유·공유 유입·구독 창 열기 등). 실패해도 화면을 막지 않는다. */
export function track(kind: string, item = "", value = "", extra?: Record<string, unknown>): void {
  post("engage", extra ? { kind, item, value, extra } : { kind, item, value }).catch(() => undefined);
}
