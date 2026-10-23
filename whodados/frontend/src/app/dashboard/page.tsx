"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth-context";
import { getPainelInicio, PainelInicio } from "@/lib/api";

/**
 * Tela inicial: o que esta empresa esta fazendo, nao o que a base tem.
 *
 * Um unico GET /painel/inicio alimenta tudo. Oito queries paralelas no cold
 * start do Render rendem oito chances de montar meio painel.
 *
 * O que NAO esta aqui: passivo/divida. E' a tela que define a prioridade de
 * quem abre o sistema, e divida nao e' criterio de prioridade neste produto.
 */

// De quanto em quanto tempo o painel se refaz. 30s porque a metrica que mais
// muda e' "enviados hoje", e o motor manda de 10 em 10 a cada 10 minutos --
// mais rapido que isso seria pedir ao Render sem nada novo pra mostrar.
const INTERVALO_MS = 30_000;

// Rampa ordinal do funil: um unico tom, claro -> escuro, acompanhando o
// avanco da etapa. Validada com scripts/validate_palette.js --ordinal nas
// duas superficies reais do app (branco no claro, #131c31 no escuro, que e'
// o que `bg-white` vira em globals.css). Nao trocar um passo sem revalidar:
// o fim claro precisa de 2:1 contra a superficie e os passos de dL >= 0.06.
const ETAPAS = [
  { chave: "novo", rotulo: "Novo", cor: "var(--funil-1)" },
  { chave: "em_contato", rotulo: "Em contato", cor: "var(--funil-2)" },
  { chave: "negociando", rotulo: "Negociando", cor: "var(--funil-3)" },
  { chave: "convertido", rotulo: "Convertido", cor: "var(--funil-4)" },
  // Descartado e' estado, nao etapa: fica em cinza pra nao parecer o fim bom
  // da rampa, e entra por ultimo.
  { chave: "descartado", rotulo: "Descartado", cor: "var(--neutro)" },
];

function num(n: number | null | undefined): string {
  return n == null ? "—" : n.toLocaleString("pt-BR");
}

function pct(parte: number | undefined, total: number | undefined): string | null {
  if (!total || parte == null) return null;
  return `${Math.round((parte / total) * 100)}%`;
}

function diaCurto(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
}

/** Tile de numero. Sem plot, entao sem hover -- o numero ja' e' a resposta. */
function Tile({
  rotulo, valor, nota, destaque, href,
}: {
  rotulo: string; valor: string; nota?: string | null; destaque?: boolean; href?: string;
}) {
  const corpo = (
    <>
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{rotulo}</p>
      <p className={`mt-1.5 text-2xl font-bold tabular-nums ${destaque ? "text-emerald-700" : "text-slate-800"}`}>
        {valor}
      </p>
      {nota && <p className="mt-1 text-xs text-slate-500">{nota}</p>}
    </>
  );
  const classe = "block rounded-xl border border-slate-200 bg-white p-4 shadow-sm";
  return href
    ? <Link href={href} className={`${classe} transition hover:border-emerald-400 hover:shadow-md`}>{corpo}</Link>
    : <div className={classe}>{corpo}</div>;
}

/** Barras de um dia cada. Serie unica: sem legenda, o titulo nomeia o dado. */
function EnviosPorDia({ serie }: { serie: { dia: string; n: number }[] }) {
  const [sobre, setSobre] = useState<number | null>(null);
  const max = Math.max(1, ...serie.map(d => d.n));
  const L = 700, A = 150, BASE = A - 22, TOPO = 12;
  const larguraFaixa = L / Math.max(serie.length, 1);
  // 2px de folga entre barras: o vao e' superficie, nao borda.
  const larguraBarra = Math.max(3, larguraFaixa - 2);
  const diaMax = serie.reduce((a, b) => (b.n > a.n ? b : a), serie[0]);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-700">E-mails enviados por dia</h2>
        <span className="text-xs text-slate-400">últimos {serie.length} dias com envio</span>
      </div>

      {serie.length === 0 ? (
        <p className="py-8 text-center text-sm text-slate-500">
          Nenhum envio registrado na janela. Isso é ausência de envio, não falha de carregamento.
        </p>
      ) : (
        <>
          <div className="relative mt-3">
            <svg viewBox={`0 0 ${L} ${A}`} className="h-auto w-full" role="img"
                 aria-label={`Envios por dia; pico de ${diaMax?.n ?? 0} em ${diaMax ? diaCurto(diaMax.dia) : "-"}`}>
              {/* Grade recessiva: so' o teto da escala. */}
              <line x1="0" y1={TOPO} x2={L} y2={TOPO} stroke="var(--grade)" strokeWidth="1" strokeDasharray="3 4" />
              <line x1="0" y1={BASE} x2={L} y2={BASE} stroke="var(--grade)" strokeWidth="1" />
              {serie.map((d, i) => {
                const h = Math.max(2, ((BASE - TOPO) * d.n) / max);
                const x = i * larguraFaixa + (larguraFaixa - larguraBarra) / 2;
                return (
                  <g key={d.dia}>
                    {/* Alvo de hover maior que a marca: a faixa inteira. */}
                    <rect x={i * larguraFaixa} y={TOPO} width={larguraFaixa} height={BASE - TOPO}
                          fill="transparent" onMouseEnter={() => setSobre(i)} onMouseLeave={() => setSobre(null)} />
                    <rect x={x} y={BASE - h} width={larguraBarra} height={h} rx="4"
                          fill={sobre === i ? "var(--funil-4)" : "var(--barra)"} pointerEvents="none" />
                  </g>
                );
              })}
              {/* Rotulo direto so' no pico e na ponta -- nunca em todo ponto. */}
              {serie.length > 1 && diaMax && (
                <text x={serie.indexOf(diaMax) * larguraFaixa + larguraFaixa / 2} y={BASE + 16}
                      textAnchor="middle" fontSize="11" fill="var(--tinta-2)">
                  {diaCurto(diaMax.dia)}
                </text>
              )}
              <text x={L - 2} y={BASE + 16} textAnchor="end" fontSize="11" fill="var(--tinta-2)">
                {diaCurto(serie[serie.length - 1].dia)}
              </text>
            </svg>
            {sobre != null && serie[sobre] && (
              <div className="pointer-events-none absolute -top-1 left-1/2 -translate-x-1/2 rounded-lg bg-slate-800 px-2.5 py-1 text-xs font-medium text-white shadow-lg">
                {diaCurto(serie[sobre].dia)}: {num(serie[sobre].n)} enviados
              </div>
            )}
          </div>

          {/* Mesma serie em texto: serve leitor de tela, impressao e quem
              precisa do numero exato de um dia que nao e' o pico. */}
          <details className="mt-2">
            <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700">Ver os números</summary>
            <table className="mt-2 w-full text-xs">
              <thead className="text-slate-500">
                <tr><th className="py-1 text-left font-medium">Dia</th><th className="py-1 text-right font-medium">Enviados</th></tr>
              </thead>
              <tbody className="tabular-nums">
                {serie.map(d => (
                  <tr key={d.dia} className="border-t border-slate-100">
                    <td className="py-1">{diaCurto(d.dia)}</td>
                    <td className="py-1 text-right">{num(d.n)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </div>
  );
}

function FunilCrm({ crm, total }: { crm: Record<string, number>; total: number }) {
  const max = Math.max(1, ...Object.values(crm));
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-700">Funil de clientes</h2>
        <Link href="/dashboard/crm" className="text-xs font-semibold text-emerald-700 hover:underline">Abrir CRM →</Link>
      </div>
      {total === 0 ? (
        <p className="py-6 text-center text-sm text-slate-500">
          Nenhuma empresa no CRM ainda. Ela entra quando você classifica ou contata alguém.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {ETAPAS.map(et => {
            const n = crm[et.chave] ?? 0;
            return (
              <li key={et.chave} className="flex items-center gap-3">
                {/* Rotulo sempre presente: a cor acompanha a etapa, nunca a
                    identifica sozinha. */}
                <span className="w-24 shrink-0 text-xs text-slate-600">{et.rotulo}</span>
                <span className="h-5 min-w-0 flex-1 overflow-hidden rounded-md bg-slate-100">
                  <span className="block h-full rounded-md" style={{ width: `${(n / max) * 100}%`, background: et.cor }} />
                </span>
                <span className="w-16 shrink-0 text-right text-xs font-semibold tabular-nums text-slate-700">
                  {num(n)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

const ATALHOS = [
  { href: "/dashboard/empresas", rotulo: "Empresas", desc: "Filtrar a base e criar lote", icone: "📊" },
  { href: "/dashboard/carteira", rotulo: "Carteira", desc: "Sua lista própria", icone: "🗃️", soCarteira: true },
  { href: "/dashboard/disparar", rotulo: "Disparar", desc: "Enviar, fila e resultado por modelo", icone: "🚀", soCarteira: true },
  { href: "/dashboard/atividades", rotulo: "Atividades", desc: "Tarefas e prazos", icone: "✅" },
];

export default function InicioPage() {
  const { activeOrg, orgs } = useAuth();
  // Os blocos de prospeccao do inicio falam da lista de trabalho, entao
  // seguem tem_carteira -- nao a fonte de pesquisa.
  const ehCarteira = activeOrg?.tem_carteira === true;

  const q = useQuery({
    queryKey: ["painel-inicio", activeOrg?.id],
    queryFn: () => getPainelInicio(14),
    refetchInterval: INTERVALO_MS,
    refetchOnWindowFocus: true,
  });
  const d: PainelInicio | undefined = q.data;

  // Relogio do "atualizado ha Xs". Anda sozinho entre refetches, senao o
  // texto mentiria que o dado e' recente enquanto a aba ficou parada.
  const [agora, setAgora] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setAgora(Date.now()), 5_000);
    return () => clearInterval(t);
  }, []);
  const segundos = useMemo(() => {
    if (!q.dataUpdatedAt) return null;
    return Math.max(0, Math.round((agora - q.dataUpdatedAt) / 1000));
  }, [agora, q.dataUpdatedAt]);

  const atalhos = ATALHOS.filter(a => !a.soCarteira || ehCarteira);
  const eng = d?.engajamento ?? {};
  const penetracao = d?.alcance.penetracao_pct ?? null;

  return (
    <div
      className="space-y-5"
      style={{
        // Papeis, nao hex, no corpo da tela -- claro/escuro troca num lugar.
        ["--funil-1" as string]: "var(--f1, #10b981)",
        ["--funil-2" as string]: "var(--f2, #059669)",
        ["--funil-3" as string]: "var(--f3, #047857)",
        ["--funil-4" as string]: "var(--f4, #064e3b)",
        ["--barra" as string]: "var(--f2, #059669)",
        ["--neutro" as string]: "#94a3b8",
        ["--grade" as string]: "#e2e8f0",
        ["--tinta-2" as string]: "#64748b",
      }}
    >
      {/* Passos do escuro: mesma rampa re-escalonada pra superficie escura
          (#131c31), nao um espelho automatico da clara. Tambem validada. */}
      <style>{`
        [data-tema="dark"] .painel-inicio {
          --f1: #6ee7b7; --f2: #34d399; --f3: #10b981; --f4: #059669;
          --grade: #24314d; --tinta-2: #94a3b8;
        }
      `}</style>

      <div className="painel-inicio space-y-5">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-slate-800">
              {activeOrg?.nome ?? "Painel"}
            </h1>
            <p className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-slate-500">
              <span>{ehCarteira ? "Prospecção sobre lista própria" : "Prospecção sobre a base da Receita"}</span>
              {segundos != null && (
                <>
                  <span aria-hidden className="text-slate-300">·</span>
                  <span className="inline-flex items-center gap-1.5">
                    <span
                      aria-hidden
                      className={`inline-block h-1.5 w-1.5 rounded-full ${q.isFetching ? "animate-pulse bg-emerald-500" : "bg-slate-300"}`}
                    />
                    {q.isFetching ? "atualizando..." : `atualizado há ${segundos}s`}
                  </span>
                </>
              )}
            </p>
          </div>
          {orgs.length > 1 && (
            <Link
              href="/selecionar-empresa"
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Trocar de empresa
            </Link>
          )}
        </header>

        {q.isError && (
          <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700">
            Não consegui carregar o painel. Os números abaixo não existem — não são zero.
          </div>
        )}

        {/* O teto e' da conta, nao da empresa: sem este aviso a empresa veria
            o envio parar sem motivo aparente. */}
        {d?.envios.teto_atingido && (
          <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm font-medium text-amber-800">
            <span aria-hidden>⏸️</span>
            Teto diário da conta atingido ({num(d.envios.limite)}/dia). Os envios
            retomam amanhã — a fila não foi perdida.
          </div>
        )}

        {/* Atraso e' estado, nao metrica: vem com icone e texto, nunca so' cor. */}
        {!!d?.atividades.atrasadas && (
          <Link
            href="/dashboard/atividades"
            className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-700 hover:bg-red-100"
          >
            <span aria-hidden>⚠️</span>
            {d.atividades.atrasadas === 1
              ? "1 atividade com prazo vencido"
              : `${num(d.atividades.atrasadas)} atividades com prazo vencido`}
            <span className="ml-auto font-semibold">Ver →</span>
          </Link>
        )}

        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Tile
            rotulo={ehCarteira ? "Na sua lista" : "Na base"}
            valor={num(d?.base.total)}
            nota={
              d?.base.estimado
                ? "estimativa — contar exato custaria varredura"
                : d?.base.com_email != null
                  ? `${num(d.base.com_email)} com e-mail · ${num(d.base.cidades)} cidades`
                  : null
            }
            href={ehCarteira ? "/dashboard/carteira" : "/dashboard/empresas"}
          />
          <Tile
            rotulo="Já contatadas"
            valor={num(d?.alcance.contatados)}
            nota={penetracao != null ? `${penetracao.toLocaleString("pt-BR")}% da ${ehCarteira ? "lista" : "base"}` : "sem base pra comparar"}
            destaque
          />
          <Tile
            rotulo="Enviados hoje"
            valor={num(d?.envios.hoje_org)}
            nota={
              // hoje_conta so' vem pra admin global. Para os demais fica o
              // teto e, se estourou, o aviso -- nunca o volume da conta, de
              // onde se deduziria o da outra empresa.
              d?.envios.hoje_conta != null && d.envios.limite
                ? `teto da conta: ${num(d.envios.hoje_conta)}/${num(d.envios.limite)}`
                : d?.envios.limite
                  ? `teto da conta: ${num(d.envios.limite)}/dia`
                  : "sem teto configurado"
            }
            href="/dashboard/disparar"
          />
          <Tile
            rotulo="Na fila"
            valor={num(d?.envios.fila_pendente)}
            nota="empresas aguardando o próximo envio"
            href="/dashboard/disparar"
          />
        </section>

        {/* Penetracao: uma barra so', porque e' uma fracao de um todo. */}
        {penetracao != null && (
          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-baseline justify-between gap-3">
              <h2 className="text-sm font-semibold text-slate-700">
                Penetração {ehCarteira ? "na lista" : "na base"}
              </h2>
              <span className="text-sm font-bold tabular-nums text-emerald-700">
                {penetracao.toLocaleString("pt-BR")}%
              </span>
            </div>
            <div
              className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-slate-100"
              role="meter"
              aria-valuenow={penetracao}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Percentual da base já contatado"
            >
              <div className="h-full rounded-full" style={{ width: `${Math.min(100, penetracao)}%`, background: "var(--funil-2)" }} />
            </div>
            <p className="mt-1.5 text-xs text-slate-500">
              {num(d?.alcance.contatados)} de {num(d?.base.total)} já receberam ao menos um e-mail.
              {d?.base.estimado && " O total da base é estimado, então a porcentagem é aproximada."}
            </p>
          </section>
        )}

        <section className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <FunilCrm crm={d?.crm ?? {}} total={d?.crm_total ?? 0} />
          <EnviosPorDia serie={d?.envios.por_dia ?? []} />
        </section>

        {!!eng.enviados && (
          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="text-sm font-semibold text-slate-700">Engajamento dos últimos 14 dias</h2>
            <div className="mt-3 grid grid-cols-2 gap-4 md:grid-cols-4">
              {[
                { r: "Enviados", v: eng.enviados, p: null as string | null },
                { r: "Entregues", v: eng.entregues, p: pct(eng.entregues, eng.enviados) },
                { r: "Abertos", v: eng.abertos, p: pct(eng.abertos, eng.enviados) },
                { r: "Clicados", v: eng.clicados, p: pct(eng.clicados, eng.enviados) },
              ].map(x => (
                <div key={x.r}>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{x.r}</p>
                  <p className="mt-1 text-xl font-bold tabular-nums text-slate-800">{num(x.v)}</p>
                  {x.p && <p className="text-xs text-slate-500">{x.p} dos enviados</p>}
                </div>
              ))}
            </div>
            <p className="mt-2 text-xs text-slate-400">
              Entregues = com prova de chegada (abriu ou clicou). O Gmail não informa a entrega, então "sem confirmação" não quer dizer que não chegou. Cliente que bloqueia imagem conta como não aberto.
            </p>
          </section>
        )}

        <section>
          <h2 className="mb-2 text-sm font-semibold text-slate-700">Ir para</h2>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            {atalhos.map(a => (
              <Link
                key={a.href}
                href={a.href}
                className="group rounded-xl border border-slate-200 bg-white p-3.5 shadow-sm transition hover:border-emerald-400 hover:shadow-md"
              >
                <span className="text-xl" aria-hidden>{a.icone}</span>
                <p className="mt-1.5 text-sm font-semibold text-slate-800">{a.rotulo}</p>
                <p className="text-xs text-slate-500">{a.desc}</p>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
