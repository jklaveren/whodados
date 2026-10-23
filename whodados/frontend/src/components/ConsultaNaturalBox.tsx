"use client";

import { useState } from "react";
import Link from "next/link";
import { consultaNatural, ConsultaNaturalResposta } from "@/lib/api";

function formatBRL(v: number | undefined): string {
  if (!v) return "—";
  if (Math.abs(v) >= 1e6) return `R$ ${(v / 1e6).toFixed(1)} mi`;
  if (Math.abs(v) >= 1e3) return `R$ ${(v / 1e3).toFixed(0)} mil`;
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

const EXEMPLOS = [
  "empresas de comércio em Porto Alegre",
  "as 10 maiores por dívida",
  "empresas de tecnologia com capital acima de 1 milhão",
];

/**
 * Busca em linguagem natural sobre a base de empresas (Claude traduz a
 * pergunta num filtro validado -- ver backend/nlp/service.py). Endpoint ja
 * existia (/empresas/consulta-natural) mas nenhuma tela chamava.
 *
 * Fica separada do funil de filtros: e' um atalho exploratorio, nao
 * substitui os filtros estruturados da pagina.
 */
export function ConsultaNaturalBox() {
  const [pergunta, setPergunta] = useState("");
  const [aberto, setAberto] = useState(false);
  const [carregando, setCarregando] = useState(false);
  const [resultado, setResultado] = useState<ConsultaNaturalResposta | null>(null);
  const [erro, setErro] = useState("");

  async function buscar(texto: string) {
    if (!texto.trim() || carregando) return;
    setCarregando(true);
    setErro("");
    setResultado(null);
    try {
      const r = await consultaNatural(texto.trim());
      setResultado(r);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não consegui interpretar essa pergunta.");
    } finally {
      setCarregando(false);
    }
  }

  return (
    <div className="rounded-xl bg-gradient-to-br from-indigo-50 to-white p-4 border border-indigo-100">
      <button
        onClick={() => setAberto(a => !a)}
        className="flex items-center gap-2 text-sm font-medium text-indigo-700"
      >
        <span>✨</span>
        <span>Perguntar em português sobre as empresas</span>
        <span className="text-indigo-400 text-xs">{aberto ? "▲" : "▼"}</span>
      </button>

      {aberto && (
        <div className="mt-3 space-y-3">
          <form
            onSubmit={e => { e.preventDefault(); buscar(pergunta); }}
            className="flex gap-2"
          >
            <input
              type="text"
              value={pergunta}
              onChange={e => setPergunta(e.target.value)}
              placeholder="Ex.: empresas de comércio em Porto Alegre com dívida acima de 1 milhão"
              className="flex-1 rounded-lg border border-indigo-200 px-3 py-2 text-sm outline-none focus:border-indigo-500 bg-white"
            />
            <button
              type="submit"
              disabled={carregando || !pergunta.trim()}
              className="rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-4 py-2 text-sm font-medium"
            >
              {carregando ? "Pensando..." : "Perguntar"}
            </button>
          </form>

          {!resultado && !erro && (
            <div className="flex flex-wrap gap-2">
              {EXEMPLOS.map(ex => (
                <button
                  key={ex}
                  onClick={() => { setPergunta(ex); buscar(ex); }}
                  className="text-xs bg-white border border-indigo-100 text-indigo-600 rounded-full px-3 py-1 hover:bg-indigo-50"
                >
                  {ex}
                </button>
              ))}
            </div>
          )}

          {erro && (
            <div className="rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-sm px-3 py-2">
              {erro}
            </div>
          )}

          {resultado && (
            <div className="rounded-lg bg-white border border-slate-200 overflow-hidden">
              <div className="px-3 py-2 border-b border-slate-100 text-sm text-slate-700">
                {resultado.resumo_em_texto}
              </div>
              {resultado.empresas.length > 0 && (
                <div className="overflow-x-auto max-h-80 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 text-xs text-slate-400 sticky top-0">
                      <tr>
                        <th className="px-3 py-1.5 text-left">Empresa</th>
                        <th className="px-3 py-1.5 text-left">Município</th>
                        <th className="px-3 py-1.5 text-right">Capital</th>
                        <th className="px-3 py-1.5 text-right">Dívida</th>
                        <th className="px-3 py-1.5"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {resultado.empresas.map(e => (
                        <tr key={e.cnpj_completo} className="border-t border-slate-50">
                          <td className="px-3 py-1.5 font-medium text-slate-800">{e.razao_social}</td>
                          <td className="px-3 py-1.5 text-slate-600">{e.municipio || "—"}</td>
                          <td className="px-3 py-1.5 text-right">{formatBRL(e.capital_social)}</td>
                          <td className="px-3 py-1.5 text-right text-red-600">{formatBRL(e.divida_total)}</td>
                          <td className="px-3 py-1.5 text-right">
                            <Link
                              href={`/dashboard/empresa/${encodeURIComponent(e.cnpj_completo)}`}
                              className="text-xs font-semibold text-indigo-600 hover:underline"
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
          )}
        </div>
      )}
    </div>
  );
}
