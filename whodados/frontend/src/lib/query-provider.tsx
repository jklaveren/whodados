"use client";

// Cache global das queries do lado do cliente. Antes: cada troca de rota
// remontava a pagina, perdia state e refetchava tudo do banco -- a UI ficava
// "carregando a base" a cada navegacao. Com o QueryClient, resultados ficam
// em memoria por chave (filtros aplicados, pagina); quando voltar pra tela
// o valor cacheado aparece instantaneo e o refetch (se stale) roda em
// background sem piscar a UI.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function QueryProvider({ children }: { children: React.ReactNode }) {
  // O QueryClient tem que ser criado UMA vez por sessao do browser. useState
  // com initializer garante isso mesmo no strict mode do React 19 (que
  // renderiza componentes duas vezes em dev).
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Depois de N ms sem interacao, uma nova montagem re-busca em
            // background. 5min cobre navegacao normal sem "queimar" dados.
            staleTime: 5 * 60 * 1000,
            // Quanto tempo o resultado fica em memoria depois que ninguem
            // mais escuta ele. 10min = se voltar pra tela dentro desse
            // prazo, o valor aparece instant.
            gcTime: 10 * 60 * 1000,
            // Nao refetcha quando a aba ganha foco -- evita "flash" de
            // loading quando o usuario so voltou pro navegador.
            refetchOnWindowFocus: false,
            // 1 retry curto e suficiente; se cair de novo a UI mostra erro.
            retry: 1,
          },
        },
      })
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
