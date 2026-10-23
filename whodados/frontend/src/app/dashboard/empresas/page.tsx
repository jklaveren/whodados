"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { MultiSelect } from "@/components/MultiSelect";
import { FunilInsights } from "@/components/FunilInsights";
import { TopEmpresasRanking } from "@/components/TopEmpresasRanking";
import { ConsultaNaturalBox } from "@/components/ConsultaNaturalBox";
import { useAuth } from "@/lib/auth-context";
import { listarEmpresas, contarEmpresas, getOpcoesFiltro, getFiltroSalvo, salvarFiltroSalvo, EmpresaItem, EmpresaFiltros, AnalyticsFiltros, OpcoesFiltro } from "@/lib/api";

const PAGE_SIZE = 50;

// Guarda a ultima configuracao de filtros no navegador -- reabrir a tela
// (ou voltar de outra aba) retoma de onde parou em vez de comecar zerado.
// So conveniencia de UI: nao sincroniza entre abas/dispositivos, entao
// nunca deve ser a unica fonte de um dado importante.
const FILTROS_STORAGE_KEY = "whodados:empresas:filtros";

// Abaixo disto o LIKE '%x%' casa com quase toda a base e nao usa
// idx_dados_empresas_razao_social (curinga a esquerda).
const BUSCA_MIN_CHARS = 3;

/**
 * Gate de consulta: sem selecao restringida a tela nao vai ao banco.
 * Sem filtro o mount disparava 7 queries sobre 1,68M linhas
 * (count + pagina + 4 agregados + ranking).
 *
 * `incluir_inativas` excluido: default ligado, nao selecao do usuario, e
 * nao reduz o custo da query.
 */
function temFiltroAtivo(f: EmpresaFiltros): boolean {
  return Boolean(
    f.cidade?.length ||
    f.cnae?.length ||
    f.porte?.length ||
    (f.busca && f.busca.trim().length >= BUSCA_MIN_CHARS) ||
    f.divida_min != null || f.divida_max != null ||
    f.capital_min != null || f.capital_max != null ||
    f.fundacao_de || f.fundacao_ate
  );
}

// `type` e nao `interface`: interface nao ganha index signature implicita,
// entao nao seria aceita onde o client espera FiltrosPainel (Record<string,
// unknown>) ao gravar a pesquisa fixada.
type FiltrosSalvos = {
  cidade: string[]; porte: string[]; cnae: string[]; busca: string;
  dividaMin: string; dividaMax: string; capitalMin: string; capitalMax: string;
  fundacaoDe: string; fundacaoAte: string; incluirInativas: boolean;
};

function lerFiltrosSalvos(): Partial<FiltrosSalvos> {
  try {
    const bruto = localStorage.getItem(FILTROS_STORAGE_KEY);
    return bruto ? JSON.parse(bruto) : {};
  } catch {
    return {}; // storage bloqueado (aba privada) ou JSON invalido -- comeca zerado
  }
}

function formatSalvoEm(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const hoje = new Date();
  const mesmoDia = d.toDateString() === hoje.toDateString();
  const hora = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return mesmoDia ? `hoje às ${hora}` : `${d.toLocaleDateString("pt-BR")} às ${hora}`;
}

function formatBRL(v: number) {
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

export default function DashboardPage() {
  const { activeOrg } = useAuth();
  const isVisitante = activeOrg?.papel === "visitante";

  // Filtros do funil (estado bruto) -- inicializado com o que ficou salvo
  // da ultima visita (lazy initializer: so le localStorage uma vez, no mount).
  const [salvos] = useState(lerFiltrosSalvos);
  const [cidade, setCidade] = useState<string[]>(salvos.cidade ?? []);
  const [porte, setPorte] = useState<string[]>(salvos.porte ?? []);
  const [cnae, setCnae] = useState<string[]>(salvos.cnae ?? []);
  const [busca, setBusca] = useState(salvos.busca ?? "");
  const [dividaMin, setDividaMin] = useState(salvos.dividaMin ?? "");
  const [dividaMax, setDividaMax] = useState(salvos.dividaMax ?? "");
  const [capitalMin, setCapitalMin] = useState(salvos.capitalMin ?? "");
  const [capitalMax, setCapitalMax] = useState(salvos.capitalMax ?? "");
  const [fundacaoDe, setFundacaoDe] = useState(salvos.fundacaoDe ?? "");
  const [fundacaoAte, setFundacaoAte] = useState(salvos.fundacaoAte ?? "");
  // Falencia/RJ fora por padrao (mesmo default do backend e dos agregados).
  const [incluirInativas, setIncluirInativas] = useState(salvos.incluirInativas ?? false);
  // Pesquisa fixada no banco: um slot por usuario/empresa, salvar sobrescreve.
  // Vive no banco (e nao so' no localStorage) pra ser ponto de retorno de
  // verdade -- volta em qualquer maquina e nao e' perdida ao mexer nos campos.
  const [salvoEm, setSalvoEm] = useState<string | null>(null);
  const [salvandoFiltro, setSalvandoFiltro] = useState(false);
  const [page, setPage] = useState(0);
  const [avisoLote, setAvisoLote] = useState("");
  const [loteCriado, setLoteCriado] = useState(false); // false = aviso de erro (vermelho)

  // Opcoes dos multiselects -- cachea por 30min (cidades/portes/cnaes mudam
  // raro). Assim voltar pra tela nao dispara essa query.
  const opcoesQuery = useQuery({
    queryKey: ["opcoes-filtro"],
    queryFn: getOpcoesFiltro,
    staleTime: 30 * 60 * 1000,
  });
  const opcoes: OpcoesFiltro | null = opcoesQuery.data ?? null;

  // Filtros "crus" -> aplicados com atraso (nao dispara a cada tecla nos campos)
  const filtros: EmpresaFiltros = useMemo(() => ({
    cidade, porte, cnae,
    busca: busca || undefined,
    divida_min: dividaMin ? Number(dividaMin) : undefined,
    divida_max: dividaMax ? Number(dividaMax) : undefined,
    capital_min: capitalMin ? Number(capitalMin) : undefined,
    capital_max: capitalMax ? Number(capitalMax) : undefined,
    fundacao_de: fundacaoDe || undefined,
    fundacao_ate: fundacaoAte || undefined,
    incluir_inativas: incluirInativas,
    ordenar_por: "razao_social",
  }), [cidade, porte, cnae, busca, dividaMin, dividaMax, capitalMin, capitalMax, fundacaoDe, fundacaoAte, incluirInativas]);

  const filtrosKey = JSON.stringify(filtros);
  const [applied, setApplied] = useState<EmpresaFiltros>(filtros);
  useEffect(() => {
    const t = setTimeout(() => setApplied(filtros), 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtrosKey]);

  // Persiste a config atual pra proxima visita. Mesmo debounce dos filtros
  // aplicados -- nao grava a cada tecla digitada na busca.
  useEffect(() => {
    const t = setTimeout(() => {
      try {
        const dados: FiltrosSalvos = {
          cidade, porte, cnae, busca, dividaMin, dividaMax,
          capitalMin, capitalMax, fundacaoDe, fundacaoAte, incluirInativas,
        };
        localStorage.setItem(FILTROS_STORAGE_KEY, JSON.stringify(dados));
      } catch { /* storage bloqueado -- so perde a conveniencia, segue normal */ }
    }, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtrosKey]);

  const appliedKey = JSON.stringify(applied);

  // Filtros para os insights agregados (analytics nao usa busca/fundacao)
  const analyticsFiltros: AnalyticsFiltros = useMemo(() => ({
    cidade: applied.cidade, cnae: applied.cnae, porte: applied.porte,
    divida_min: applied.divida_min, divida_max: applied.divida_max,
    capital_min: applied.capital_min, capital_max: applied.capital_max,
    incluir_inativas: applied.incluir_inativas,
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [appliedKey]);

  // Volta pra primeira pagina quando o filtro aplicado muda
  useEffect(() => { setPage(0); }, [appliedKey]);

  // Contagem do funil -- cacheada pela combinacao de filtros. Trocar
  // filtro dispara uma nova query; voltar pra combinacao antiga usa o
  // valor em memoria (sem re-hit no banco).
  // Deriva de `applied` (debounced 400ms): digitar na busca nao alterna o
  // gate a cada tecla.
  const temFiltro = temFiltroAtivo(applied);

  const countQuery = useQuery({
    queryKey: ["empresas-count", applied],
    queryFn: () => contarEmpresas(applied),
    enabled: temFiltro,
  });
  const total = countQuery.data?.total ?? null;

  // Pagina atual -- cacheada por (filtros, pagina). Navegar/voltar em outra
  // aba e voltar aqui reidrata instantaneo com o valor em memoria.
  // placeholderData: keepPreviousData evita "flash" de tabela vazia
  // enquanto a proxima pagina carrega.
  const empresasQuery = useQuery({
    queryKey: ["empresas", applied, page],
    queryFn: () => listarEmpresas(applied, PAGE_SIZE, page * PAGE_SIZE),
    placeholderData: (prev) => prev,
    enabled: temFiltro,
  });
  const empresas: EmpresaItem[] = empresasQuery.data ?? [];
  // isLoading, nao isPending: com enabled=false o status fica 'pending'
  // indefinidamente e a tabela exibiria "Carregando..." sem query em voo.
  const loading = empresasQuery.isLoading;
  const error = empresasQuery.isError ? "Erro ao carregar empresas." : "";

  const cidadeOptions = useMemo(() => (opcoes?.cidades ?? []).map(c => ({ value: c, label: c })), [opcoes]);
  const porteOptions = useMemo(() => (opcoes?.portes ?? []).map(p => ({ value: p, label: p })), [opcoes]);
  const cnaeOptions = useMemo(() => (opcoes?.cnaes ?? []).map(c => ({
    value: c.codigo,
    label: `${c.codigo} - ${c.descricao}${c.qtd ? ` (${c.qtd.toLocaleString("pt-BR")})` : ""}`,
  })), [opcoes]);

  const totalPages = total != null ? Math.max(1, Math.ceil(total / PAGE_SIZE)) : null;

  const aplicarFiltros = (f: Partial<FiltrosSalvos>) => {
    setCidade(f.cidade ?? []); setPorte(f.porte ?? []); setCnae(f.cnae ?? []);
    setBusca(f.busca ?? "");
    setDividaMin(f.dividaMin ?? ""); setDividaMax(f.dividaMax ?? "");
    setCapitalMin(f.capitalMin ?? ""); setCapitalMax(f.capitalMax ?? "");
    setFundacaoDe(f.fundacaoDe ?? ""); setFundacaoAte(f.fundacaoAte ?? "");
    setIncluirInativas(f.incluirInativas ?? false);
    setPage(0);
  };

  // Ao abrir a tela, a pesquisa fixada no banco manda mais que o cache do
  // navegador: e' o que a pessoa escolheu guardar. Sem nada salvo, fica o
  // que o localStorage ja' tinha posto nos campos no mount.
  useEffect(() => {
    let vivo = true;
    getFiltroSalvo()
      .then(r => {
        if (!vivo || !r.filtros) return;
        aplicarFiltros(r.filtros as Partial<FiltrosSalvos>);
        setSalvoEm(r.atualizado_em);
      })
      .catch(() => { /* sem ponto de retorno nao e' erro de tela */ });
    return () => { vivo = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeOrg?.id]);

  async function fixarPesquisa() {
    setSalvandoFiltro(true);
    try {
      const dados: FiltrosSalvos = {
        cidade, porte, cnae, busca, dividaMin, dividaMax,
        capitalMin, capitalMax, fundacaoDe, fundacaoAte, incluirInativas,
      };
      const r = await salvarFiltroSalvo(dados);
      setSalvoEm(r.atualizado_em);
    } catch {
      setAvisoLote("Não consegui salvar a pesquisa. Tente de novo.");
      setLoteCriado(false);
    } finally {
      setSalvandoFiltro(false);
    }
  }

  const limparFiltros = () => {
    setCidade([]); setPorte([]); setCnae([]); setBusca("");
    setDividaMin(""); setDividaMax(""); setCapitalMin(""); setCapitalMax("");
    setFundacaoDe(""); setFundacaoAte(""); setIncluirInativas(false);
    try { localStorage.removeItem(FILTROS_STORAGE_KEY); } catch { /* ignora */ }
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Empresas</h1>
          <p className="text-slate-500 mt-1">
            {!temFiltro
              ? "Escolha um filtro para consultar a base"
              : total != null
                ? <><strong className="text-indigo-700">{total.toLocaleString("pt-BR")}</strong> empresas neste filtro</>
                : "Contando..."}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {!isVisitante && (
            <button
              onClick={fixarPesquisa}
              disabled={salvandoFiltro}
              title="Guarda esta pesquisa como ponto de retorno. Salvar de novo substitui a anterior."
              className="rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-40"
            >
              {salvandoFiltro ? "Salvando..." : "Salvar pesquisa"}
            </button>
          )}
          <button onClick={limparFiltros} className="text-sm text-slate-500 hover:text-slate-800 underline">Limpar filtros</button>
        </div>
      </header>

      {salvoEm && (
        <p className="-mt-2 text-xs text-slate-500">
          Pesquisa salva {formatSalvoEm(salvoEm)} — é ela que abre quando você volta.
        </p>
      )}

      {avisoLote && (
        <div className={`rounded-lg p-3 text-sm ${loteCriado ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700"}`}>
          {avisoLote}
        </div>
      )}

      <ConsultaNaturalBox />

      {/* Funil de filtros */}
      <div className="rounded-xl bg-white p-4 shadow-sm border border-slate-200 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          <input
            type="text"
            placeholder="Buscar por razão social / fantasia..."
            value={busca}
            onChange={e => setBusca(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500"
          />
          <MultiSelect options={cidadeOptions} selected={cidade} onChange={setCidade} placeholder="Cidades..." />
          <MultiSelect options={porteOptions} selected={porte} onChange={setPorte} placeholder="Porte..." />
        </div>

        <MultiSelect options={cnaeOptions} selected={cnae} onChange={setCnae} placeholder="Setores (CNAE — código e descrição)..." />

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          <label className="text-xs text-slate-500">Passivo (R$)
            <div className="mt-1 flex gap-2">
              <input type="number" placeholder="min" value={dividaMin} onChange={e => setDividaMin(e.target.value)} className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
              <input type="number" placeholder="max" value={dividaMax} onChange={e => setDividaMax(e.target.value)} className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
            </div>
          </label>
          <label className="text-xs text-slate-500">Capital social (R$)
            <div className="mt-1 flex gap-2">
              <input type="number" placeholder="min" value={capitalMin} onChange={e => setCapitalMin(e.target.value)} className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
              <input type="number" placeholder="max" value={capitalMax} onChange={e => setCapitalMax(e.target.value)} className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
            </div>
          </label>
          <label className="text-xs text-slate-500">Fundação (de / até)
            <div className="mt-1 flex gap-2">
              <input type="date" value={fundacaoDe} onChange={e => setFundacaoDe(e.target.value)} className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
              <input type="date" value={fundacaoAte} onChange={e => setFundacaoAte(e.target.value)} className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
            </div>
          </label>
          <label className="flex items-end gap-2 text-sm text-slate-600 pb-1">
            <input type="checkbox" checked={!incluirInativas} onChange={e => setIncluirInativas(!e.target.checked)} />
            Ocultar Falência / Rec. Judicial
          </label>
        </div>
      </div>

      {/* Gate por montagem, nao por visibilidade: componente nao montado nao
          dispara useQuery/useEffect. E' o que corta os 5 agregados de
          FunilInsights e TopEmpresasRanking, nao so' a lista paginada. */}
      {!temFiltro && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-12 text-center">
          <p className="text-base font-medium text-slate-700">Escolha um filtro para começar</p>
          <p className="mx-auto mt-2 max-w-md text-sm text-slate-500">
            A base tem mais de 1,6 milhão de empresas. Selecione uma cidade, um
            setor ou um porte acima — ou digite ao menos {BUSCA_MIN_CHARS} letras
            na busca — e o painel carrega só a sua seleção.
          </p>
        </div>
      )}

      {/* Insights agregados sobre a base filtrada inteira */}
      {temFiltro && <FunilInsights filtros={analyticsFiltros} />}

      {/* Ranking das maiores empresas (divida ou capital) na selecao atual */}
      {temFiltro && <TopEmpresasRanking filtros={analyticsFiltros} />}

      {error && <div className="rounded-lg bg-red-50 p-4 text-red-700">{error}</div>}

      {/* Tabela (página) */}
      {temFiltro && (
      <div className="rounded-xl bg-white shadow-sm border border-slate-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-700">
              <tr>
                <th className="px-4 py-3 text-left">CNPJ</th>
                <th className="px-4 py-3 text-left">Razão Social</th>
                <th className="px-4 py-3 text-left">Município</th>
                <th className="px-4 py-3 text-left">CNAE</th>
                <th className="px-4 py-3 text-right">Capital</th>
                <th className="px-4 py-3 text-right">Dívida</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-slate-400">Carregando...</td></tr>
              ) : empresas.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-slate-400">Nenhuma empresa para este filtro.</td></tr>
              ) : empresas.map(e => (
                <tr key={e.cnpj_completo} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-3 font-mono text-xs">{e.cnpj_completo}</td>
                  <td className="px-4 py-3 font-medium">{e.razao_social}</td>
                  <td className="px-4 py-3">{e.municipio || "-"}</td>
                  <td className="px-4 py-3 text-xs">{e.cnae_principal || "-"}{e.cnae_descricao ? ` - ${e.cnae_descricao}` : ""}</td>
                  <td className="px-4 py-3 text-right">{formatBRL(e.capital_social)}</td>
                  <td className="px-4 py-3 text-right text-red-600">{formatBRL(e.divida_total)}</td>
                  <td className="px-4 py-3 text-right">
                    {!isVisitante && (
                      <Link href={`/dashboard/empresa/${encodeURIComponent(e.cnpj_completo)}`} className="rounded-lg bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-600 hover:bg-indigo-100">
                        Ver detalhes
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {totalPages != null && total! > 0 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-slate-100 text-sm text-slate-600">
            <span>Página {page + 1} de {totalPages.toLocaleString("pt-BR")}</span>
            <div className="flex gap-2">
              <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} className="px-3 py-1 rounded border border-slate-300 disabled:opacity-40">Anterior</button>
              <button onClick={() => setPage(p => (totalPages && p + 1 < totalPages ? p + 1 : p))} disabled={totalPages != null && page + 1 >= totalPages} className="px-3 py-1 rounded border border-slate-300 disabled:opacity-40">Próxima</button>
            </div>
          </div>
        )}
      </div>
      )}
    </div>
  );
}
