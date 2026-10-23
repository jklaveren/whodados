"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type Tema = "claro" | "escuro" | "sistema";

const CHAVE = "whodados:tema";

interface Ctx {
  tema: Tema;
  /** O que esta valendo agora, com "sistema" ja resolvido. */
  efetivo: "claro" | "escuro";
  definir: (t: Tema) => void;
}

const TemaContext = createContext<Ctx>({ tema: "sistema", efetivo: "claro", definir: () => {} });

function preferenciaDoSistema(): "claro" | "escuro" {
  if (typeof window === "undefined") return "claro";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "escuro" : "claro";
}

function aplicar(efetivo: "claro" | "escuro") {
  document.documentElement.setAttribute("data-tema", efetivo === "escuro" ? "dark" : "light");
}

export function TemaProvider({ children }: { children: React.ReactNode }) {
  const [tema, setTema] = useState<Tema>("sistema");
  const [efetivo, setEfetivo] = useState<"claro" | "escuro">("claro");

  useEffect(() => {
    let salvo: Tema = "sistema";
    try {
      const v = localStorage.getItem(CHAVE);
      if (v === "claro" || v === "escuro" || v === "sistema") salvo = v;
    } catch { /* storage bloqueado: fica no padrao */ }
    setTema(salvo);
    const e = salvo === "sistema" ? preferenciaDoSistema() : salvo;
    setEfetivo(e);
    aplicar(e);
  }, []);

  // Em "sistema", acompanha a troca no SO sem precisar recarregar.
  useEffect(() => {
    if (tema !== "sistema" || typeof window === "undefined") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const ouvir = () => {
      const e = mq.matches ? "escuro" : "claro";
      setEfetivo(e);
      aplicar(e);
    };
    mq.addEventListener("change", ouvir);
    return () => mq.removeEventListener("change", ouvir);
  }, [tema]);

  const definir = useCallback((t: Tema) => {
    setTema(t);
    try { localStorage.setItem(CHAVE, t); } catch { /* ignora */ }
    const e = t === "sistema" ? preferenciaDoSistema() : t;
    setEfetivo(e);
    aplicar(e);
  }, []);

  return <TemaContext.Provider value={{ tema, efetivo, definir }}>{children}</TemaContext.Provider>;
}

export const useTema = () => useContext(TemaContext);

/** Roda antes da hidratacao pra nao piscar branco em quem usa tema escuro. */
export const SCRIPT_ANTI_FLASH = `(function(){try{
var t=localStorage.getItem("${CHAVE}")||"sistema";
var e=t==="sistema"?(matchMedia("(prefers-color-scheme: dark)").matches?"escuro":"claro"):t;
document.documentElement.setAttribute("data-tema",e==="escuro"?"dark":"light");
}catch(_){}})();`;
