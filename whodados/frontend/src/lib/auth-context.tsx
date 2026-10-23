"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import * as api from "./api";
import type { Organizacao } from "./api";

interface AuthState {
  username: string | null;
  isAdmin: boolean;
  isLoading: boolean;
  orgs: Organizacao[];
  activeOrgId: number | null;
  /** A lista de empresas ja' voltou do servidor, com sucesso ou nao. Enquanto
   *  for false, nao se sabe se a empresa e' de base Receita ou carteira
   *  propria -- e a tela nao pode decidir o que mostrar. */
  orgsCarregadas: boolean;
}

interface AuthContextValue extends AuthState {
  login: (username: string, password: string, rememberMe?: boolean) => Promise<void>;
  logout: () => void;
  switchOrg: (orgId: number) => void;
  /** Escolhe a empresa SEM recarregar -- pra tela de selecao, que navega em seguida. */
  selecionarOrg: (orgId: number) => void;
  activeOrg: Organizacao | null;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function decodeUsernameFromToken(token: string): { username: string | null; isAdmin: boolean } {
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return { username: payload.sub ?? null, isAdmin: !!payload.is_admin };
  } catch {
    return { username: null, isAdmin: false };
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({
    username: null, isAdmin: false, isLoading: true, orgs: [], activeOrgId: null, orgsCarregadas: false,
  });

  // Carrega as empresas do usuario e escolhe a ativa (a salva, se ainda valida,
  // senao a primeira). Precisa do token ja setado.
  const carregarOrgs = useCallback(async () => {
    try {
      const orgs = await api.listarOrganizacoes();
      const salva = api.getActiveOrgId();
      const ativa = orgs.find(o => o.id === salva)?.id ?? orgs[0]?.id ?? null;
      if (ativa) api.setActiveOrgId(ativa);
      setState(s => ({ ...s, orgs, activeOrgId: ativa, orgsCarregadas: true }));
    } catch {
      setState(s => ({ ...s, orgs: [], activeOrgId: null, orgsCarregadas: true }));
    }
  }, []);

  useEffect(() => {
    const token = api.getToken();
    if (token) {
      const { username, isAdmin } = decodeUsernameFromToken(token);
      setState(s => ({ ...s, username, isAdmin, isLoading: false }));
      carregarOrgs();
    } else {
      setState(s => ({ ...s, isLoading: false }));
    }
  }, [carregarOrgs]);

  const login = useCallback(async (username: string, password: string, rememberMe = false) => {
    const res = await api.login(username, password, rememberMe);
    api.setToken(res.access_token);
    const { isAdmin } = decodeUsernameFromToken(res.access_token);
    setState(s => ({ ...s, username, isAdmin, isLoading: false }));
    await carregarOrgs();
  }, [carregarOrgs]);

  const logout = useCallback(() => {
    api.removeToken();
    api.clearActiveOrgId();
    setState({ username: null, isAdmin: false, isLoading: false, orgs: [], activeOrgId: null, orgsCarregadas: false });
  }, []);

  const switchOrg = useCallback((orgId: number) => {
    api.setActiveOrgId(orgId);
    setState(s => ({ ...s, activeOrgId: orgId }));
    // Recarrega para que todas as telas rebusquem os dados sob a nova empresa.
    if (typeof window !== "undefined") window.location.reload();
  }, []);

  // switchOrg recarrega a pagina porque troca a empresa COM telas montadas
  // sob a anterior. Na tela de selecao nao ha o que recarregar: o proximo
  // passo e' navegar pro painel, e um reload no meio piscaria a tela.
  const selecionarOrg = useCallback((orgId: number) => {
    api.setActiveOrgId(orgId);
    setState(s => ({ ...s, activeOrgId: orgId }));
  }, []);

  const activeOrg = useMemo(
    () => state.orgs.find(o => o.id === state.activeOrgId) ?? null,
    [state.orgs, state.activeOrgId],
  );

  const value = useMemo(
    () => ({ ...state, login, logout, switchOrg, selecionarOrg, activeOrg }),
    [state, login, logout, switchOrg, selecionarOrg, activeOrg],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth deve ser usado dentro de <AuthProvider>");
  return ctx;
}

export function useRequireAuth() {
  const auth = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!auth.isLoading && !auth.username) {
      router.replace("/login");
    }
  }, [auth.isLoading, auth.username, router]);

  return auth;
}
