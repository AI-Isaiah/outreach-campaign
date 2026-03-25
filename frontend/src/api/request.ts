/** Base fetch wrapper with error handling and auth token injection. */

export const BASE = import.meta.env.VITE_API_BASE_URL || "/api";

/** Get auth headers for raw fetch calls (e.g., FormData uploads). */
export function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem("auth_token");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const res = await fetch(`${BASE}${path}`, {
    headers: { ...headers, ...(options?.headers as Record<string, string>) },
    ...options,
  });

  if (res.status === 401) {
    localStorage.removeItem("auth_token");
    window.dispatchEvent(new Event("auth:expired"));
    throw new Error("Session expired");
  }

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `HTTP ${res.status}`);
  }
  return res.json();
}
