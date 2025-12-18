import React from 'react';

import { storage } from '../storage';

type AuthState = {
  token: string | null;
  isLoading: boolean;
};

type AuthContextValue = AuthState & {
  setToken: (token: string) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
};

export const AuthContext = React.createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<AuthState>({ token: null, isLoading: true });

  const refresh = React.useCallback(async () => {
    const token = await storage.getToken();
    setState({ token, isLoading: false });
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const setToken = React.useCallback(async (token: string) => {
    await storage.setToken(token);
    setState({ token, isLoading: false });
  }, []);

  const signOut = React.useCallback(async () => {
    await storage.clearToken();
    setState({ token: null, isLoading: false });
  }, []);

  const value: AuthContextValue = { ...state, setToken, signOut, refresh };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error('AuthContext missing');
  return ctx;
}
