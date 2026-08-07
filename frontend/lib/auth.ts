"use client";

/**
 * Auth helpers — token storage + authenticated fetch wrapper.
 *
 * Token is kept in localStorage (simple, fine for local dev). For production
 * you'd use httpOnly cookies set by the backend; that's a v2 concern.
 */

const TOKEN_KEY = "agenora:token";
const USER_KEY = "agenora:user";

export type User = {
  id: string;
  email: string;
  display_name: string;
  created_at: string | null;
  /** Admin dashboard (06-01): optional so older cached user objects (pre-admin)
   *  still type-check. Source of truth is /api/auth/me → to_public_dict(). */
  is_admin?: boolean;
  is_active?: boolean;
};

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function getUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function setUser(user: User): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearAuth(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

/** Clear stale credentials and send the user back to login (once per page load). */
export function handleSessionExpired(reason = "session_expired"): void {
  if (typeof window === "undefined") return;
  clearAuth();
  const path = window.location.pathname;
  if (
    path.startsWith("/login") ||
    path.startsWith("/register") ||
    path.startsWith("/welcome")
  ) {
    return;
  }
  // Avoid redirect storms when many API calls fail at once.
  if ((window as Window & { __agenoraAuthRedirect?: boolean }).__agenoraAuthRedirect) {
    return;
  }
  (window as Window & { __agenoraAuthRedirect?: boolean }).__agenoraAuthRedirect = true;
  const next = encodeURIComponent(`${path}${window.location.search}`);
  window.location.href = `/login?next=${next}&reason=${encodeURIComponent(reason)}`;
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

/** fetch wrapper that auto-attaches Bearer token. */
export async function authFetch(input: RequestInfo, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(input, { ...init, headers });
  if (response.status === 401) {
    handleSessionExpired();
  }
  return response;
}

// ---------------------------------------------------------------------------
// Auth API
// ---------------------------------------------------------------------------
type AuthResponse = { token: string; user: User };

function localizeApiMessage(message: string): string {
  const text = message.trim();
  const lower = text.toLowerCase();
  if (lower.includes("email already registered")) {
    return "这个邮箱已经注册过，请直接登录。";
  }
  if (lower.includes("invalid email or password")) {
    return "邮箱或密码不正确。";
  }
  if (lower.includes("account disabled")) {
    return "该账号已被禁用。";
  }
  if (lower.includes("user not found")) {
    return "未找到当前账号，请重新登录。";
  }
  if (lower.includes("incorrect old password")) {
    return "旧密码不正确。";
  }
  if (
    lower.includes("not a valid email address") ||
    lower.includes("valid email")
  ) {
    return "请输入有效的邮箱地址。";
  }
  if (lower.includes("special-use") || lower.includes("reserved name")) {
    return "邮箱域名不能使用保留域名，请换一个常用邮箱。";
  }
  if (lower.includes("string should have at least 8 characters")) {
    return "密码至少需要 8 位。";
  }
  return text;
}

function localizeApiField(value: unknown): string {
  const key = String(value ?? "");
  if (key === "email") return "邮箱";
  if (key === "password") return "密码";
  if (key === "display_name") return "昵称";
  return key;
}

function stringifyApiDetail(value: unknown, fallback: string): string {
  if (typeof value === "string") return localizeApiMessage(value);
  if (Array.isArray(value)) {
    const parts = value
      .map((item) => stringifyApiDetail(item, ""))
      .filter(Boolean);
    return parts.length > 0 ? parts.join("；") : fallback;
  }
  if (value && typeof value === "object") {
    const obj = value as {
      detail?: unknown;
      message?: unknown;
      msg?: unknown;
      loc?: unknown;
    };
    if (obj.detail !== undefined) return stringifyApiDetail(obj.detail, fallback);
    if (obj.message !== undefined) return stringifyApiDetail(obj.message, fallback);
    if (obj.msg !== undefined) {
      const msg = stringifyApiDetail(obj.msg, fallback);
      if (Array.isArray(obj.loc) && obj.loc.length > 0) {
        return `${localizeApiField(obj.loc[obj.loc.length - 1])}: ${msg}`;
      }
      return msg;
    }
    try {
      return JSON.stringify(value);
    } catch {
      return fallback;
    }
  }
  return fallback;
}

async function readApiError(response: Response, fallback: string): Promise<string> {
  const detail = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
  return stringifyApiDetail(detail, fallback);
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const r = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!r.ok) {
    throw new Error(await readApiError(r, "login failed"));
  }
  const data = (await r.json()) as AuthResponse;
  setToken(data.token);
  setUser(data.user);
  return data;
}

export async function register(
  email: string,
  password: string,
  display_name = ""
): Promise<AuthResponse> {
  const r = await fetch("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, display_name }),
  });
  if (!r.ok) {
    throw new Error(await readApiError(r, "register failed"));
  }
  const data = (await r.json()) as AuthResponse;
  setToken(data.token);
  setUser(data.user);
  return data;
}

export function logout(): void {
  clearAuth();
}

/** Re-fetch the current user from /api/auth/me and refresh the localStorage
 *  cache. Used by admin pages to pick up an is_admin flag that was granted
 *  after the cached login. Returns null when not authenticated / on error. */
export async function refreshMe(): Promise<User | null> {
  if (!getToken()) return null;
  const r = await authFetch("/api/auth/me");
  if (!r.ok) return null;
  const user = (await r.json()) as User;
  setUser(user);
  return user;
}

// ---------------------------------------------------------------------------
// v3-M5: profile editing
// ---------------------------------------------------------------------------
export async function updateProfile(displayName: string): Promise<User> {
  const r = await authFetch("/api/auth/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: displayName }),
  });
  if (!r.ok) {
    throw new Error(await readApiError(r, "保存个人资料失败"));
  }
  const user = (await r.json()) as User;
  setUser(user);
  return user;
}

export async function changePassword(
  oldPassword: string,
  newPassword: string
): Promise<void> {
  const r = await authFetch("/api/auth/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });
  if (!r.ok) {
    throw new Error(await readApiError(r, "修改密码失败"));
  }
}

export async function deleteAccount(): Promise<void> {
  const r = await authFetch("/api/auth/me", { method: "DELETE" });
  if (!r.ok) {
    throw new Error(await readApiError(r, "删除账号失败"));
  }
  clearAuth();
}
