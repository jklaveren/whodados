"use client";

import { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  PieChart, Pie, Cell, ResponsiveContainer, Legend,
} from "recharts";
import {
  getAnalyticsResumo, getAnalyticsPorCidade, getAnalyticsPorSetor, getAnalyticsPorPorte,
  AnalyticsFiltros, AnalyticsResumo, CidadeAgg, SetorAgg, PorteAgg,
} from "@/lib/api";

const COLORS = ["#4f46e5", "#0ea5e9", "#0d9488", "#7c3aed", "#0891b2", "#64748b"];

function brl(v: number): string {
  if (Math.abs(v) >= 1e9) return `R$ ${(v / 1e9).toFixed(1)} bi`;
  if (Math.abs(v) >= 1e6) return `R$ ${(v / 1e6).toFixed(1)} mi`;
  if (Math.abs(v) >= 1e3) return `R$ ${(v / 1e3).toFixed(0)} mil`;
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

const num = (v: number) => v.toLocaleString("pt-BR");

/**
 * Panorama da selecao atual do funil, calculado no servidor sobre a base
 * filtrada inteira (nao sobre a pagina exibida).
 *
 * Os graficos medem QUANTAS empresas existem por recorte -- a pergunta de
 * quem prospecta e "onde estao meus clientes". Valores financeiros ficam
 * nos indicadores, sem virar o eixo dos graficos.
 */
export function FunilInsights({ filtros }: { filtros: AnalyticsFiltros }) {
  const [resumo, setResumo] = useState<AnalyticsResumo | null>(null);
  const [cidades, setCidades] = useState<CidadeAgg[]>([]);
  const [setores, setSetores] = useState<SetorAgg[]>([]);
  const [portes, setPortes] = useState<PorteAgg[]>([]);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState(false);

  useEffect(() => {
    let cancel = false;
    setLoading(true);
    setErro(false);
    Promise.all([
      getAnalyticsResumo(filtros),
      getAnalyticsPorCidade(filtros, 12),
      getAnalyticsPorSetor(filtros, 10),
      getAnalyticsPorPorte(filtros),
    ])
      .then(([r, c, s, p]) => {
        if (!cancel) { setResumo(r); setCidades(c); setSetores(s); setPortes(p); }
      })
      .catch(() => { if (!cancel) setErro(true); })
      .finally(() => { if (!cancel) setLoading(false); });
    return () => { cancel = true; };
  }, [filtros]);

  const kpis = resumo ? [
    { label: "Empresas", valor: num(resumo.total_empresas), destaque: true },
    { label: "Cidades", valor: num(resumo.qtd_cidades) },
    { label: "Setores", valor: num(resumo.qtd_setores) },
    { label: "Capital total", valor: brl(resumo.capital_total) },
    { label: "Capital médio", valor: brl(resumo.capital_medio) },
    { label: "Dívida ativa", valor: brl(resumo.divida_total) },
  ] : [];

  const cidadeData = cidades.map(c => ({ name: c.cidade, qtd: c.qtd }));
  const setorData = setores.map(s => ({
    name: (s.descricao || s.cnae).slice(0, 30), qtd: s.qtd,
  }));
  const porteData = portes.map(p => ({ name: p.porte || "Não informado", value: p.qtd }));

  // Base vazia nao e erro: e o estado normal antes da primeira carga de dados.
  const semDados = !loading && !erro && resumo != null && resumo.total_empresas === 0;

  if (erro) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-8 text-center">
        <p className="font-medium text-slate-700">Não foi possível carregar o panorama</p>
        <p className="mt-1 text-sm text-slate-500">
          Verifique se o servidor está no ar e recarregue a página.
        </p>
      </div>
    );
  }

  if (semDados) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-10 text-center">
        <p className="font-medium text-slate-700">Nenhuma empresa nesta seleção</p>
        <p className="mt-1 text-sm text-slate-500">
          Ajuste os filtros acima — ou aguarde a próxima carga, se a base ainda
          não foi populada.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        {(loading && !resumo ? Array.from({ length: 6 }) : kpis).map((k, i) => {
          const item = k as { label?: string; valor?: string; destaque?: boolean };
          return (
            <div
              key={i}
              className={`rounded-lg border p-4 ${
                item?.destaque
                  ? "border-indigo-200 bg-indigo-50/60"
                  : "border-slate-200 bg-white"
              }`}
            >
              <div className="text-[11px] uppercase tracking-wide text-slate-500">
                {item?.label ?? "…"}
              </div>
              <div
                className={`mt-1.5 text-xl font-semibold tabular-nums ${
                  item?.destaque ? "text-indigo-700" : "text-slate-800"
                }`}
              >
                {item?.valor ?? "—"}
              </div>
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h3 className="font-semibold text-slate-800">Empresas por cidade</h3>
          <p className="mb-4 mt-0.5 text-xs text-slate-500">
            Onde está concentrada a sua seleção
          </p>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={cidadeData} layout="vertical" margin={{ left: 8, right: 24 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#f1f5f9" />
                <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => num(Number(v))} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={95} />
                <Tooltip formatter={(v) => [num(Number(v)), "Empresas"] as [string, string]} />
                <Bar dataKey="qtd" name="Empresas" fill="#4f46e5" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h3 className="font-semibold text-slate-800">Empresas por setor</h3>
          <p className="mb-4 mt-0.5 text-xs text-slate-500">
            Atividades com mais empresas na seleção
          </p>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={setorData} layout="vertical" margin={{ left: 8, right: 24 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#f1f5f9" />
                <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => num(Number(v))} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={150} />
                <Tooltip formatter={(v) => [num(Number(v)), "Empresas"] as [string, string]} />
                <Bar dataKey="qtd" name="Empresas" fill="#0d9488" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-5 lg:col-span-2">
          <h3 className="font-semibold text-slate-800">Distribuição por porte</h3>
          <p className="mb-4 mt-0.5 text-xs text-slate-500">
            Perfil de tamanho das empresas selecionadas
          </p>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={porteData}
                  cx="50%"
                  cy="50%"
                  innerRadius={55}
                  outerRadius={85}
                  paddingAngle={2}
                  dataKey="value"
                >
                  {porteData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Pie>
                <Tooltip formatter={(v) => [num(Number(v)), "Empresas"] as [string, string]} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
