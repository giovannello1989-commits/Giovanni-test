import React from 'react';

const KEY = 'swipster.token';

type AuthCtx = {
  token: string | null;
  setToken: (t: string) => void;
  signOut: () => void;
};

const Ctx = React.createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = React.useState<string | null>(() => localStorage.getItem(KEY));

  const setToken = React.useCallback((t: string) => {
    localStorage.setItem(KEY, t);
    setTokenState(t);
  }, []);

  const signOut = React.useCallback(() => {
    localStorage.removeItem(KEY);
    setTokenState(null);
  }, []);

  return <Ctx.Provider value={{ token, setToken, signOut }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = React.useContext(Ctx);
  if (!v) throw new Error('AuthProvider missing');
  return v;
}
