import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "../api/client";
import type { MeResponse, MyMembership, OrgRole } from "../api/types";

const ACTIVE_ORG_KEY = "activeOrgId";

export interface AuthContextValue {
  /** true, пока идёт начальный GET /auth/me */
  loading: boolean;
  /** false -- сервер работает без авторизации (dev): вход не нужен */
  authEnabled: boolean;
  user: MeResponse["user"];
  /** Роль пользователя в активной организации (null -- открытый режим) */
  activeRole: OrgRole | null;
  /** Организации, доступные переключателю: свои либо все для системного админа */
  orgChoices: MyMembership[];
  activeOrgId: number | null;
  setActiveOrgId: (orgId: number | null) => void;
  /** Обновить /auth/me (после создания организации, выхода и т.п.) */
  refresh: () => Promise<void>;
  /** Вход по логину и паролю; бросает Error с сообщением от API */
  login: (login: string, password: string) => Promise<void>;
  /** Регистрация (и активация приглашённой записи); сессия ставится сразу */
  register: (login: string, password: string, displayName?: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Открытый режим: авторизация не настроена, всё разрешено (как раньше) */
  openMode: boolean;
  /** Наблюдателя (reader) и «не вошедших» в открытый режиме не ограничиваем */
  canEdit: boolean;
  canAdmin: boolean;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

const ROLE_LEVEL: Record<OrgRole, number> = {reader: 0, editor: 1, admin: 2};

export function AuthProvider({children}: {children: ReactNode}) {
  const [loading, setLoading] = useState(true);
  const [authEnabled, setAuthEnabled] = useState(true);
  const [user, setUser] = useState<MeResponse["user"]>(null);
  const [memberships, setMemberships] = useState<MyMembership[]>([]);
  const [allOrgs, setAllOrgs] = useState<MyMembership[] | null>(null); // для superadmin
  const [activeOrgId, setActiveOrgIdState] = useState<number | null>(() => {
    const raw = window.localStorage.getItem(ACTIVE_ORG_KEY);
    return raw ? Number(raw) || null : null;
  });
  const initialized = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const me = await api.get<MeResponse>("/auth/me");
      setAuthEnabled(me.auth_enabled);
      setUser(me.user);
      setMemberships(me.memberships);
      if (me.auth_enabled && me.user?.is_superadmin) {
        // Системный админ видит все организации, не только свои.
        try {
          const orgs = await api.get<{id: number; name: string; my_role: OrgRole | null}[]>("/orgs");
          setAllOrgs(orgs.map((org) => ({org_id: org.id, org_name: org.name, role: org.my_role ?? "admin"})));
        } catch {
          setAllOrgs(null);
        }
      } else {
        setAllOrgs(null);
      }
    } catch {
      // 401 -- не вошёл (нормальное состояние до входа); остальное -- сеть.
      setUser(null);
      setMemberships([]);
    } finally {
      setLoading(false);
      initialized.current = true;
    }
  }, []);

  useEffect(() => {
    void refresh();
    // Истечение сессии посреди работы: любой 401 из клиента переключает
    // приложение на экран входа.
    const onUnauthorized = () => {
      if (!initialized.current) return;
      setUser(null);
      setMemberships([]);
    };
    window.addEventListener("auth:unauthorized", onUnauthorized);
    return () => window.removeEventListener("auth:unauthorized", onUnauthorized);
  }, [refresh]);

  const orgChoices = useMemo<MyMembership[]>(() => {
    if (user?.is_superadmin && allOrgs) return allOrgs;
    return memberships;
  }, [user, allOrgs, memberships]);

  // Активная организация: сохранённый выбор, если он ещё доступен, иначе
  // первая из доступных; в открытом режиме -- null.
  const effectiveOrgId = useMemo(() => {
    if (!authEnabled) return null;
    if (orgChoices.length === 0) return null;
    if (activeOrgId != null && orgChoices.some((choice) => choice.org_id === activeOrgId)) {
      return activeOrgId;
    }
    return orgChoices[0].org_id;
  }, [authEnabled, orgChoices, activeOrgId]);

  const activeRole = useMemo<OrgRole | null>(() => {
    if (!authEnabled) return null;
    const choice = orgChoices.find((item) => item.org_id === effectiveOrgId);
    return choice?.role ?? null;
  }, [authEnabled, orgChoices, effectiveOrgId]);

  const setActiveOrgId = useCallback((orgId: number | null) => {
    setActiveOrgIdState(orgId);
    if (orgId == null) window.localStorage.removeItem(ACTIVE_ORG_KEY);
    else window.localStorage.setItem(ACTIVE_ORG_KEY, String(orgId));
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout", {});
    } catch {
      // сессия могла уже истечь -- не важно
    }
    setUser(null);
    setMemberships([]);
    setAllOrgs(null);
  }, []);

  const login = useCallback(async (loginValue: string, password: string) => {
    await api.post("/auth/login", {login: loginValue.trim(), password});
    await refresh();
  }, [refresh]);

  const register = useCallback(async (loginValue: string, password: string, displayName?: string) => {
    await api.post("/auth/register", {
      login: loginValue.trim(),
      password,
      display_name: displayName?.trim() || null,
    });
    await refresh();
  }, [refresh]);

  const openMode = !authEnabled;
  const canEdit = openMode || (user != null && (user.is_superadmin || (activeRole != null && ROLE_LEVEL[activeRole] >= ROLE_LEVEL.editor)));
  const canAdmin = openMode || (user != null && (user.is_superadmin || activeRole === "admin"));

  const value: AuthContextValue = {
    loading,
    authEnabled,
    user,
    activeRole,
    orgChoices,
    activeOrgId: effectiveOrgId,
    setActiveOrgId,
    refresh,
    login,
    register,
    logout,
    openMode,
    canEdit,
    canAdmin,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth должен вызываться внутри AuthProvider");
  return ctx;
}
