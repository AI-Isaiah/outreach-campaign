import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";

interface User {
  id: number;
  email: string;
  name: string;
}

interface AuthContextValue {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  login: (token: string, user: User) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const stored = localStorage.getItem("auth_token");
    if (!stored) {
      setIsLoading(false);
      return;
    }

    // Decode JWT client-side (no verification — just for display)
    try {
      const payload = JSON.parse(atob(stored.split(".")[1]));
      if (payload.exp * 1000 < Date.now()) {
        localStorage.removeItem("auth_token");
        setIsLoading(false);
        return;
      }
      setToken(stored);
      setUser({ id: payload.sub, email: payload.email, name: payload.name });
    } catch {
      localStorage.removeItem("auth_token");
    }
    setIsLoading(false);
  }, []);

  // Listen for 401 events from request.ts
  useEffect(() => {
    const handler = () => {
      localStorage.removeItem("auth_token");
      setUser(null);
      setToken(null);
    };
    window.addEventListener("auth:expired", handler);
    return () => window.removeEventListener("auth:expired", handler);
  }, []);

  const login = useCallback((newToken: string, newUser: User) => {
    localStorage.setItem("auth_token", newToken);
    setToken(newToken);
    setUser(newUser);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("auth_token");
    setUser(null);
    setToken(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
