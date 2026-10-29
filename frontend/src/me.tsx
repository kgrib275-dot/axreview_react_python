// 방문자 상태 — GET /api/me 한 번으로 받아 모든 화면이 공유한다 (관리자 여부, 구독 여부, 월 구독, 기억한 값).
// 기억할 값(필터·진행 중인 테스트 등)은 setState 로 바꾸면 PUT /api/me/state 로 저장되어 다음 방문에도 그대로다.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { get, put } from "./api";

export type Member = { id: number; expires: string; quota: number; used: number } | null;
export type Me = {
  visitor: string;
  is_admin: boolean;
  member: Member;
  state: Record<string, unknown>; // visitor_state 스냅샷 (서버가 허용한 키만)
  privacy_active: boolean;
  ask_enabled: boolean;
  kakao_key: string;
  site_url: string;
};

type Ctx = {
  me: Me | null;
  reload: () => Promise<void>;
  state: Record<string, unknown>;
  setState: (patch: Record<string, unknown>) => void;
};

const MeCtx = createContext<Ctx>({ me: null, reload: async () => undefined, state: {}, setState: () => undefined });

export function MeProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [state, setLocal] = useState<Record<string, unknown>>({});
  const timer = useRef<number | undefined>(undefined);
  const pending = useRef<Record<string, unknown>>({});

  const reload = useCallback(async () => {
    try {
      const m = await get<Me>("me");
      setMe(m);
      setLocal(m.state || {});
    } catch {
      setMe((prev) => prev ?? ({ visitor: "", is_admin: false, member: null, state: {}, privacy_active: true, ask_enabled: false, kakao_key: "", site_url: "" } as Me));
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const setState = useCallback((patch: Record<string, unknown>) => {
    setLocal((s) => ({ ...s, ...patch }));
    pending.current = { ...pending.current, ...patch };
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const body = pending.current;
      pending.current = {};
      put("me/state", body).catch(() => undefined);
    }, 400); // 연타해도 한 번에 저장
  }, []);

  const value = useMemo(() => ({ me, reload, state, setState }), [me, reload, state, setState]);
  return <MeCtx.Provider value={value}>{children}</MeCtx.Provider>;
}

export const useMe = () => useContext(MeCtx);
