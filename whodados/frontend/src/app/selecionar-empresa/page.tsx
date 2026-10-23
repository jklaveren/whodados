"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useRequireAuth } from "@/lib/auth-context";
import type { Organizacao } from "@/lib/api";

/**
 * Escolha da empresa, entre o login e o painel.
 *
 * A lista vem de /api/v1/organizacoes, que devolve SO' as empresas que o
 * usuario logado tem acesso (join em usuario_organizacoes) -- a tela nao
 * filtra nada por conta propria, e nao ha o que esconder no cliente.
 *
 * Com uma empresa so' a tela nao aparece: perguntar o que nao tem alternativa
 * e' so' um clique a mais em todo login. Com varias, perguntar e' melhor que
 * adivinhar -- escrever na empresa errada ja' aconteceu neste sistema.
 */

const PAPEL_ROTULO: Record<string, string> = {
  admin: "Administrador",
  membro: "Membro",
  visitante: "Visitante",
};

function Inicial({ nome }: { nome: string }) {
  const letras = nome.trim().split(/\s+/).slice(0, 2).map(p => p[0]).join("").toUpperCase();
  return (
    <span
      aria-hidden
      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-sm font-bold text-white shadow-sm"
    >
      {letras}
    </span>
  );
}

export default function SelecionarEmpresaPage() {
  const { username, isLoading, orgs, selecionarOrg, logout } = useRequireAuth();
  const router = useRouter();

  // Uma empresa: segue direto, sem pedir confirmacao do obvio. replace e nao
  // push -- "voltar" aqui devolveria a pessoa pra uma tela que ela nunca viu.
  useEffect(() => {
    if (!isLoading && orgs.length === 1) {
      selecionarOrg(orgs[0].id);
      router.replace("/dashboard");
    }
  }, [isLoading, orgs, selecionarOrg, router]);

  function escolher(org: Organizacao) {
    selecionarOrg(org.id);
    router.push("/dashboard");
  }

  if (isLoading || !username || orgs.length === 1) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <div className="text-center">
          <div className="mb-4 text-4xl">🛡️</div>
          <p className="text-slate-500">Carregando...</p>
        </div>
      </div>
    );
  }

  // Sem empresa nenhuma o painel nao tem o que mostrar, e o backend recusaria
  // toda chamada com 403. Dizer isso aqui evita a pessoa passar pelo painel
  // vazio achando que o sistema quebrou.
  if (orgs.length === 0) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
        <div className="max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <div className="mb-3 text-4xl">🔒</div>
          <h1 className="text-lg font-bold text-slate-800">Nenhuma empresa liberada</h1>
          <p className="mt-2 text-sm text-slate-600">
            Sua conta existe, mas ainda não está vinculada a nenhuma empresa.
            Quem administra o WhoDados precisa liberar o seu acesso em
            Configurações → Usuários.
          </p>
          <button
            onClick={logout}
            className="mt-6 rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            Sair
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-emerald-50/40 px-4 py-10 md:py-16">
      <div className="mx-auto w-full max-w-2xl">
        <header className="mb-8 text-center">
          <div className="mb-3 text-4xl">🛡️</div>
          <h1 className="text-2xl font-bold text-slate-800">Qual empresa você vai operar?</h1>
          <p className="mt-2 text-sm text-slate-500">
            Olá, @{username} — tudo que você fizer a seguir fica registrado na
            empresa escolhida aqui.
          </p>
        </header>

        <ul className="space-y-3">
          {orgs.map(org => (
            <li key={org.id}>
              <button
                onClick={() => escolher(org)}
                className="group flex w-full items-center gap-4 rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-emerald-400 hover:shadow-md focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/30"
              >
                <Inicial nome={org.nome} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold text-slate-800">{org.nome}</span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
                    {org.papel && <span>{PAPEL_ROTULO[org.papel] ?? org.papel}</span>}
                    {org.papel && <span aria-hidden className="text-slate-300">·</span>}
                    {/* De onde a empresa prospecta. Dito aqui porque muda o
                        que o painel e as telas mostram -- e' a diferenca
                        entre "a base da Receita" e "a minha lista". */}
                    <span>
                      {org.escopo_base === "carteira" ? "Lista própria" : "Base da Receita"}
                    </span>
                    {!org.ativo && (
                      <>
                        <span aria-hidden className="text-slate-300">·</span>
                        <span className="font-semibold text-amber-600">inativa</span>
                      </>
                    )}
                  </span>
                </span>
                <span
                  aria-hidden
                  className="shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-emerald-600"
                >
                  →
                </span>
              </button>
            </li>
          ))}
        </ul>

        <div className="mt-8 text-center">
          <button onClick={logout} className="text-sm text-slate-400 underline hover:text-slate-600">
            Sair
          </button>
        </div>
      </div>
    </div>
  );
}
