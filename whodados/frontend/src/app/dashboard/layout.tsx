"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { SeletorTema } from "@/components/SeletorTema";
import { useRequireAuth } from "@/lib/auth-context";
import { useRouter } from "next/navigation";
import OrgSwitcher from "@/components/OrgSwitcher";
import { contarNotificacoesNaoLidas } from "@/lib/api";

// Duas perguntas independentes decidem o menu:
//   baseReceita    -> a tela so' faz sentido com a base da Receita (escopo_base)
//   carteiraPropria-> a tela so' faz sentido com lista de trabalho (tem_carteira)
// Nao sao opostos: a Alfa pesquisa na base da Receita E tem carteira, entao
// ve os dois grupos. Tratar como opostos foi o que escondeu o Disparar dela.
// ocultaNaCarteira: telas que o time nao usa numa empresa de lista propria. So' saem do MENU: o endereco segue
// funcionando, e Alfa/Gama continuam vendo tudo.
// O resto das telas serve as duas fontes -- empresa com carteira propria ve
// as mesmas telas, com os dados dela.
const NAV_LINKS = [
  { href: "/dashboard", label: "Inicio", icon: "🏠" },
  { href: "/dashboard/empresas", label: "Empresas", icon: "📊", baseReceita: true },
  { href: "/dashboard/carteira", label: "Carteira", icon: "🗃️", carteiraPropria: true },
  { href: "/dashboard/socios", label: "Sócios", icon: "🧑‍🤝‍🧑", baseReceita: true },
  { href: "/dashboard/crm", label: "Clientes", icon: "🗂️" },
  { href: "/dashboard/atividades", label: "Atividades", icon: "✅" },
  { href: "/dashboard/gastos", label: "Gastos", icon: "🧾", ocultaNaCarteira: true },
  { href: "/dashboard/disparar", label: "Disparar", icon: "🚀", carteiraPropria: true },
  { href: "/dashboard/proposta", label: "Propostas", icon: "📄" },
  { href: "/dashboard/templates", label: "Templates", icon: "📝" },
  { href: "/dashboard/notificacoes", label: "Notificações", icon: "🔔" },
  { href: "/dashboard/configuracoes", label: "Configurações", icon: "⚙️" },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { username, isLoading, logout, activeOrg, orgsCarregadas } = useRequireAuth();
  const router = useRouter();
  const pathname = usePathname();
  const isVisitante = activeOrg?.papel === "visitante";
  // Empresa que prospecta sobre carteira propria nao tem quadro societario
  // (isso so' existe na base da Receita). Todo o resto ela ve normalmente.
  const temBaseReceita = activeOrg?.escopo_base !== "carteira";
  const temCarteira = activeOrg?.tem_carteira === true;
  // Sem empresa ativa nao se sabe qual menu mostrar. Antes isso caia em "base da
  // Receita" e a Beta via, por um instante ou para sempre, as telas da Alfa
  // (Empresas, Socios, Envios, Lotes...). Na duvida, so' o que serve a todas.
  const empresaConhecida = activeOrg !== null;
  const navLinks = !empresaConhecida
    ? NAV_LINKS.filter(l => l.href === "/dashboard" || l.href === "/dashboard/configuracoes")
    : isVisitante
    ? NAV_LINKS.filter(l => l.href === "/dashboard"
        || (l.href === "/dashboard/empresas" && temBaseReceita))
    : NAV_LINKS.filter(l =>
        (!l.baseReceita || temBaseReceita)
        && (!l.carteiraPropria || temCarteira)
        && (!l.ocultaNaCarteira || temBaseReceita));

  // !username inclui o instante entre "terminou de carregar" e o
  // redirect pro /login efetivamente acontecer (useRequireAuth so'
  // dispara o router.replace num efeito, que roda DEPOIS do render) --
  // sem isso, esse instante renderizava o dashboard inteiro (menu,
  // cabecalho) por um frame antes de sair da tela.
  // Contador de nao lidas no menu. Antes, uma tarefa atribuida so' aparecia
  // pra quem entrasse em Notificacoes -- da tela nao mudava nada, entao a
  // notificacao existia e ninguem via.
  const [naoLidas, setNaoLidas] = useState(0);
  const atualizarNaoLidas = useCallback(() => {
    if (!username) return;
    contarNotificacoesNaoLidas()
      .then(r => setNaoLidas(r.total))
      .catch(() => {/* sem badge e' melhor que quebrar o menu */});
  }, [username]);

  useEffect(() => {
    atualizarNaoLidas();
    const t = setInterval(atualizarNaoLidas, 60_000);
    return () => clearInterval(t);
  }, [atualizarNaoLidas]);

  // Trocar de tela (e sair de Notificacoes, onde elas viram lidas) recontar.
  useEffect(() => {
    atualizarNaoLidas();
  }, [pathname, activeOrg?.id, atualizarNaoLidas]);

  // No celular o menu vira gaveta: fixo por cima so' enquanto aberto, e some
  // ao navegar. Como coluna fixa, os 256px comeriam dois tercos de uma tela
  // de 375px.
  const [menuAberto, setMenuAberto] = useState(false);

  // No desktop o menu pode ficar recolhido (so' os icones), pra sobrar
  // largura pro conteudo. A escolha fica salva -- quem recolheu nao quer
  // reabrir a cada visita.
  const [recolhido, setRecolhido] = useState(false);

  useEffect(() => {
    setRecolhido(localStorage.getItem("menu_recolhido") === "1");
  }, []);

  function alternarRecolhido() {
    setRecolhido(atual => {
      localStorage.setItem("menu_recolhido", atual ? "0" : "1");
      return !atual;
    });
  }

  useEffect(() => {
    setMenuAberto(false);
  }, [pathname]);

  const rotaBloqueada =
    NAV_LINKS.some(l => pathname === l.href
      && ((l.baseReceita && !temBaseReceita) || (l.carteiraPropria && !temCarteira)));

  useEffect(() => {
    if (!isLoading && username && rotaBloqueada) router.replace("/dashboard");
  }, [isLoading, username, rotaBloqueada, router]);

  // orgsCarregadas: o menu depende da empresa; mostrar antes dela chegar e' o que
  // fazia o menu da Alfa piscar na Beta.
  if (isLoading || !username || !orgsCarregadas || rotaBloqueada) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <div className="text-4xl mb-4">🛡️</div>
          <p className="text-slate-500">Carregando...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-slate-50 flex">
      {/* Fundo escuro so' no modo gaveta: fecha o menu ao tocar fora. */}
      {menuAberto && (
        <div
          className="fixed inset-0 z-30 bg-slate-900/40 md:hidden"
          onClick={() => setMenuAberto(false)}
          aria-hidden
        />
      )}

      <aside
        className={`w-64 bg-white/95 md:bg-white/70 border-r border-slate-200/50 flex flex-col shadow-sm
          fixed inset-y-0 left-0 z-40 transition-transform duration-200 overflow-y-auto
          md:static md:z-auto md:translate-x-0 md:transition-[width] md:duration-200
          ${menuAberto ? "translate-x-0" : "-translate-x-full"}
          ${recolhido ? "md:w-[68px]" : "md:w-64"}`}
      >
        <div className={`relative border-b border-slate-200/50 bg-gradient-to-b from-indigo-500 to-purple-600 text-white ${recolhido ? "p-4 md:px-3" : "p-5"}`}>
          <Link href="/dashboard" className="text-xl font-bold flex items-center gap-3">
            <span className="text-2xl">🛡️</span>
            <span className={recolhido ? "md:hidden" : ""}>WhoDados</span>
          </Link>
          <p className={`text-sm text-indigo-100 mt-1 ${recolhido ? "md:hidden" : ""}`}>Análise Empresarial</p>
          <button
            onClick={() => setMenuAberto(false)}
            className="md:hidden absolute top-4 right-4 text-white/80 hover:text-white text-xl leading-none"
            aria-label="Fechar menu"
          >
            ✕
          </button>
        </div>
        {isVisitante && (
          <div className={`mx-3 mt-3 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-700 font-medium ${recolhido ? "md:hidden" : ""}`}>
            👁️ Modo visitante — dados de exemplo, sem acesso de edição
          </div>
        )}
        <nav className="flex-1 p-3 space-y-1">
          {navLinks.map(link => {
            const active = pathname === link.href || (link.href !== "/dashboard" && pathname.startsWith(link.href));
            return (
              <Link
                key={link.href}
                href={link.href}
                title={recolhido ? link.label : undefined}
                className={`flex items-center gap-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 ${
                  recolhido ? "px-3 md:justify-center md:px-0" : "px-3"
                } ${
                  active 
                    ? "bg-gradient-to-r from-indigo-500 to-purple-600 text-white shadow-md" 
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 hover:shadow-sm"
                }`}
              >
                <span className="text-lg relative">
                  {link.icon}
                  {/* Recolhido nao ha' espaco pro numero: vira so' o pontinho. */}
                  {recolhido && link.href === "/dashboard/notificacoes" && naoLidas > 0 && (
                    <span className="hidden md:block absolute -top-0.5 -right-1 w-2 h-2 rounded-full bg-red-500" />
                  )}
                </span>
                <span className={`flex-1 ${recolhido ? "md:hidden" : ""}`}>{link.label}</span>
                {link.href === "/dashboard/notificacoes" && naoLidas > 0 && (
                  <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded-full min-w-[20px] text-center ${
                    active ? "bg-white text-indigo-700" : "bg-red-500 text-white"
                  } ${recolhido ? "md:hidden" : ""}`}>
                    {naoLidas > 99 ? "99+" : naoLidas}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
        <div className="p-4 border-t border-slate-200/50 bg-white/50">
          <div className={`mb-2 ${recolhido ? "md:hidden" : ""}`}>
            <SeletorTema compacto />
          </div>
          <div className={`flex items-center justify-between ${recolhido ? "md:justify-center" : ""}`}>
            <div className={`flex flex-col ${recolhido ? "md:hidden" : ""}`}>
              <span className="text-xs text-slate-500">Logado como:</span>
              <span className="text-sm font-medium text-slate-700">@{username}</span>
            </div>
            <button
              onClick={() => { logout(); router.push("/login"); }}
              title={recolhido ? `Sair (@${username})` : undefined}
              className="text-xs text-slate-400 hover:text-red-500 transition-all duration-200 hover:scale-105"
            >
              🡒<span className={recolhido ? "md:hidden" : ""}> Sair</span>
            </button>
          </div>
        </div>
      </aside>

      {/* min-w-0: sem isso o flex item nao encolhe abaixo do conteudo e
          qualquer tabela larga empurra a pagina inteira no celular. */}
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-slate-200/50 bg-white/80 px-4 md:px-6 py-3 backdrop-blur-sm">
          <button
            onClick={() => setMenuAberto(true)}
            className="md:hidden relative -ml-1 p-1.5 text-slate-600 hover:text-slate-900"
            aria-label="Abrir menu"
          >
            <span className="text-xl leading-none">☰</span>
            {naoLidas > 0 && (
              <span className="absolute top-0 right-0 w-2 h-2 rounded-full bg-red-500" />
            )}
          </button>
          <button
            onClick={alternarRecolhido}
            className="hidden md:flex items-center justify-center -ml-1 w-8 h-8 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800"
            title={recolhido ? "Mostrar menu" : "Recolher menu"}
            aria-label={recolhido ? "Mostrar menu" : "Recolher menu"}
          >
            <span className="text-lg leading-none">{recolhido ? "»" : "«"}</span>
          </button>
          <span className="md:hidden font-semibold text-slate-700">WhoDados</span>
          <div className="ml-auto">
            <OrgSwitcher />
          </div>
        </header>
        <main className="flex-1 p-4 md:p-6 overflow-x-hidden">{children}</main>
      </div>
    </div>
  );
}
