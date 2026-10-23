"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { MultiSelect } from "@/components/MultiSelect";
import {
  getSociosRanking, getSocioDetalhe, getOpcoesFiltro,
  AnalyticsFiltros, SocioAgg, OpcoesFiltro,
} from "@/lib/api";

function formatBRL(v: number): string {
  if (Math.abs(v) >= 1e9) return `R$ ${(v / 1e9).toFixed(1)} bi`;
  if (Math.abs(v) >= 1e6) return `R$ ${(v / 1e6).toFixed(1)} mi`;
  if (Math.abs(v) >= 1e3) return `R$ ${(v / 1e3).toFixed(0)} mil`;
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

/**
 * Analise de Socios -- reconstroi a tela que existia no app legado
 * (LegadoStream) e que o backend ja tem pronta (analytics_socios_ranking /
 * analytics_socio_detalhe) mas nenhuma tela chamava ainda.
 *
 * Pergunta que responde: quais pessoas concentram mais passivo/capital
 * entre as empresas em que constam como socio, e em quais empresas.
 */
export default function SociosPage() {
  const searchParams = useSearchParams();
  const [cidade, setCidade] = useState<string[]>([]);
  const [cnae, setCnae] = useState<string[]>([]);
  const [porte, setPorte] = useState<string[]>([]);
  const [socioSelecionado, setSocioSelecionado] = useState<string | null>(null);

  // Vindo de um link "ver no ranking de sócios" (ex.: pagina de detalhe da
  // empresa) -- abre ja com o drill-down desse socio.
  useEffect(() => {
    const nome = searchParams?.get("nome");
    if (nome) setSocioSelecionado(nome);
  }, [searchParams]);

  const opcoesQuery = useQuery({
    queryKey: ["opcoes-filtro"],
    queryFn: getOpcoesFiltro,
    staleTime: 30 * 60 * 1000,
  });
  const opcoes: OpcoesFiltro | null = opcoesQuery.data ?? null;

  const filtros: AnalyticsFiltros = useMemo(
    () => ({ cidade, cnae, porte }),
    [cidade, cnae, porte]
  );

  const rankingQuery = useQuery({
    queryKey: ["socios-ranking", filtros],
    queryFn: () => getSociosRanking(filtros, 100),
  });
  const ranking: SocioAgg[] = rankingQuery.data ?? [];

  const detalheQuery = useQuery({
    queryKey: ["socio-detalhe", socioSelecionado],
    queryFn: () => getSocioDetalhe(socioSelecionado!),
    enabled: !!socioSelecionado,
  });

  const cidadeOptions = useMemo(() => (opcoes?.cidades ?? []).map(c => ({ value: c, label: c })), [opcoes]);
  const porteOptions = useMemo(() => (opcoes?.portes ?? []).map(p => ({ value: p, label: p })), [opcoes]);
  const cnaeOptions = useMemo(() => (opcoes?.cnaes ?? []).map(c => ({
    value: c.codigo, label: `${c.codigo} - ${c.descricao}`,
  })), [opcoes]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-800">Sócios</h1>
        <p className="text-slate-500 mt-1">
          Ranking de sócios pelo passivo/capital acumulado das empresas em que constam.
        </p>
      </header>

      <div className="rounded-xl bg-white p-4 shadow-sm border border-slate-200 grid grid-cols-1 md:grid-cols-3 gap-3">
        <MultiSelect options={cidadeOptions} selected={cidade} onChange={setCidade} placeholder="Cidades..." />
        <MultiSelect options={porteOptions} selected={porte} onChange={setPorte} placeholder="Porte..." />
        <MultiSelect options={cnaeOptions} selected={cnae} onChange={setCnae} placeholder="Setores (CNAE)..." />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Ranking */}
        <div className="rounded-xl bg-white shadow-sm border border-slate-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-100">
            <h3 className="font-semibold text-slate-800 text-sm">Ranking por passivo/capital</h3>
          </div>
          <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-500 text-xs sticky top-0">
                <tr>
                  <th className="px-4 py-2 text-left">Sócio</th>
                  <th className="px-4 py-2 text-right">Empresas</th>
                  <th className="px-4 py-2 text-right">Dívida</th>
                  <th className="px-4 py-2 text-right">Capital</th>
                </tr>
              </thead>
              <tbody>
                {rankingQuery.isLoading ? (
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">Carregando...</td></tr>
                ) : rankingQuery.isError ? (
                  // Sem isto a falha virava `data ?? []` e a tela dizia "nenhum
                  // socio PARA ESTE FILTRO" -- culpando a escolha de quem esta
                  // usando por um servico fora do ar, que faria a pessoa mexer
                  // no filtro tentando consertar o que nao e' dela.
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-sm text-red-700">
                    Não consegui carregar o ranking.{" "}
                    <button onClick={() => rankingQuery.refetch()} className="font-medium underline">Tentar de novo</button>
                  </td></tr>
                ) : ranking.length === 0 ? (
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400">Nenhum sócio para este filtro.</td></tr>
                ) : ranking.map(s => (
                  <tr
                    key={s.nome_socio}
                    onClick={() => setSocioSelecionado(s.nome_socio)}
                    className={`border-t border-slate-50 cursor-pointer hover:bg-indigo-50/60 ${socioSelecionado === s.nome_socio ? "bg-indigo-50" : ""}`}
                  >
                    <td className="px-4 py-2.5 font-medium text-slate-800">{s.nome_socio}</td>
                    <td className="px-4 py-2.5 text-right text-slate-600">{s.qtd_empresas}</td>
                    <td className="px-4 py-2.5 text-right text-red-600">{formatBRL(s.divida_total)}</td>
                    <td className="px-4 py-2.5 text-right text-slate-700">{formatBRL(s.capital_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Drill-down: empresas do socio selecionado */}
        <div className="rounded-xl bg-white shadow-sm border border-slate-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-100">
            <h3 className="font-semibold text-slate-800 text-sm">
              {socioSelecionado ? `Empresas de ${socioSelecionado}` : "Selecione um sócio no ranking"}
            </h3>
          </div>
          <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
            {!socioSelecionado ? (
              <p className="px-4 py-8 text-center text-sm text-slate-400">
                Clique em um sócio à esquerda para ver as empresas em que ele consta.
              </p>
            ) : detalheQuery.isLoading ? (
              <p className="px-4 py-8 text-center text-sm text-slate-400">Carregando...</p>
            ) : detalheQuery.isError ? (
              <p className="px-4 py-8 text-center text-sm text-red-700">
                Não consegui carregar as empresas deste sócio.{" "}
                <button onClick={() => detalheQuery.refetch()} className="font-medium underline">Tentar de novo</button>
              </p>
            ) : (detalheQuery.data ?? []).length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-slate-400">Nenhuma empresa encontrada.</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-slate-500 text-xs sticky top-0">
                  <tr>
                    <th className="px-4 py-2 text-left">Empresa</th>
                    <th className="px-4 py-2 text-left">Município</th>
                    <th className="px-4 py-2 text-right">Dívida</th>
                    <th className="px-4 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {(detalheQuery.data ?? []).map(e => (
                    <tr key={e.cnpj_completo} className="border-t border-slate-50">
                      <td className="px-4 py-2.5">
                        <div className="font-medium text-slate-800">{e.razao_social}</div>
                        <div className="text-xs text-slate-400">{e.cnae_descricao || e.cnae_principal || "—"}</div>
                      </td>
                      <td className="px-4 py-2.5 text-slate-600">{e.municipio || "—"}</td>
                      <td className="px-4 py-2.5 text-right text-red-600">{formatBRL(e.divida_total)}</td>
                      <td className="px-4 py-2.5 text-right">
                        <Link
                          href={`/dashboard/empresa/${encodeURIComponent(e.cnpj_completo)}`}
                          className="rounded-lg bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-600 hover:bg-indigo-100"
                        >
                          Ver
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
