"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { getAnalyticsTopEmpresas, AnalyticsFiltros } from "@/lib/api";

function formatBRL(v: number): string {
  if (Math.abs(v) >= 1e9) return `R$ ${(v / 1e9).toFixed(1)} bi`;
  if (Math.abs(v) >= 1e6) return `R$ ${(v / 1e6).toFixed(1)} mi`;
  if (Math.abs(v) >= 1e3) return `R$ ${(v / 1e3).toFixed(0)} mil`;
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

/**
 * Ranking das maiores empresas da selecao atual, por divida ou capital
 * social. Usa /api/v1/analytics/top-empresas -- endpoint que ja existia no
 * backend mas nenhuma tela chamava (o "so existe no repo" que a Jessica
 * apontou). Complementa a tabela paginada por RAZAO_SOCIAL: aqui a
 * pergunta e "quem sao os maiores", nao "liste todo mundo".
 */
export function TopEmpresasRanking({ filtros }: { filtros: AnalyticsFiltros }) {
  const [ordenarPor, setOrdenarPor] = useState<"divida" | "capital">("divida");
  const limite = 10;

  const { data, isLoading, isError } = useQuery({
    queryKey: ["top-empresas", filtros, ordenarPor, limite],
    queryFn: () => getAnalyticsTopEmpresas(ordenarPor, limite, filtros),
  });

  const empresas = data ?? [];
  // Backend degrada sozinho pra capital quando a base nao tem DIVIDA_TOTAL
  // ainda (ETL legado). Avisa em vez de fingir que o ranking pedido rodou.
  const degradado = empresas.length > 0 && empresas[0].sem_divida && ordenarPor === "divida";

  return (
    <div className="rounded-xl bg-white p-5 shadow-sm border border-slate-200">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-1">
        <h3 className="font-semibold text-slate-800">Top empresas da seleção</h3>
        <div className="flex rounded-lg border border-slate-200 overflow-hidden text-xs">
          <button
            onClick={() => setOrdenarPor("divida")}
            className={`px-3 py-1.5 font-medium ${ordenarPor === "divida" ? "bg-red-50 text-red-700" : "bg-white text-slate-500 hover:bg-slate-50"}`}
          >
            Por dívida
          </button>
          <button
            onClick={() => setOrdenarPor("capital")}
            className={`px-3 py-1.5 font-medium border-l border-slate-200 ${ordenarPor === "capital" ? "bg-indigo-50 text-indigo-700" : "bg-white text-slate-500 hover:bg-slate-50"}`}
          >
            Por capital
          </button>
        </div>
      </div>
      <p className="text-xs text-slate-400 mb-4">
        {ordenarPor === "divida" ? "Maior passivo ativo primeiro" : "Maior capital social primeiro"}
        {degradado && " — sem dados de dívida na base; mostrando por capital"}
      </p>

      {isLoading && <div className="py-8 text-center text-sm text-slate-400">Carregando...</div>}
      {isError && <div className="py-8 text-center text-sm text-red-600">Erro ao carregar o ranking.</div>}
      {!isLoading && !isError && empresas.length === 0 && (
        <div className="py-8 text-center text-sm text-slate-400">Nenhuma empresa nesta seleção.</div>
      )}

      {empresas.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-400 border-b border-slate-100">
                <th className="py-2 pr-3 font-medium">#</th>
                <th className="py-2 pr-3 font-medium">Empresa</th>
                <th className="py-2 pr-3 font-medium">Município</th>
                <th className="py-2 pr-3 font-medium">Porte</th>
                <th className="py-2 pr-3 font-medium text-right">Capital</th>
                <th className="py-2 pr-3 font-medium text-right">Dívida</th>
                <th className="py-2"></th>
              </tr>
            </thead>
            <tbody>
              {empresas.map((e, i) => (
                <tr key={e.cnpj_completo} className="border-b border-slate-50 last:border-0">
                  <td className="py-2 pr-3 text-slate-400">{i + 1}</td>
                  <td className="py-2 pr-3">
                    <div className="font-medium text-slate-800">{e.razao_social}</div>
                    <div className="text-xs text-slate-400">{e.cnae_descricao || e.cnae_principal || "—"}</div>
                  </td>
                  <td className="py-2 pr-3 text-slate-600">{e.municipio || "—"}</td>
                  <td className="py-2 pr-3 text-slate-600">{e.porte_nome || "—"}</td>
                  <td className="py-2 pr-3 text-right font-medium text-slate-700">{formatBRL(e.capital_social)}</td>
                  <td className="py-2 pr-3 text-right font-medium text-red-600">
                    {e.sem_divida ? "—" : formatBRL(e.divida_total)}
                  </td>
                  <td className="py-2 text-right">
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
        </div>
      )}
    </div>
  );
}
