"use client";

import { useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  PieChart, Pie, Cell, ResponsiveContainer, Legend,
} from "recharts";
import { EmpresaItem } from "@/lib/api";

const COLORS = ["#6366f1", "#8b5cf6", "#ec4899", "#f97316", "#10b981", "#3b82f6"];

interface AnalyticsChartsProps {
  empresas: EmpresaItem[];
}

export function AnalyticsCharts({ empresas }: AnalyticsChartsProps) {
  const porCidade = useMemo(() => {
    const map: Record<string, number> = {};
    empresas.forEach(e => {
      const city = e.municipio || "Desconhecido";
      map[city] = (map[city] || 0) + 1;
    });
    return Object.entries(map)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 15);
  }, [empresas]);

  const porPorte = useMemo(() => {
    const map: Record<string, number> = {};
    empresas.forEach(e => {
      const p = e.porte_nome || "DEMAIS";
      map[p] = (map[p] || 0) + 1;
    });
    return Object.entries(map).map(([name, value]) => ({ name, value }));
  }, [empresas]);

  const comDivida = useMemo(() => {
    const com = empresas.filter(e => e.divida_total > 0).length;
    const sem = empresas.length - com;
    return [
      { name: "Com Dívida", value: com },
      { name: "Sem Dívida", value: sem },
    ];
  }, [empresas]);

  if (empresas.length === 0) return null;

    return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
      {/* Por Cidade */}
      <div className="rounded-2xl bg-white/80 border border-slate-200/50 p-6 shadow-lg hover:shadow-xl transition-shadow duration-300">
        <h3 className="font-semibold text-slate-800 text-lg mb-1">Empresas por Cidade</h3>
        <p className="text-xs text-slate-400 mb-5">Distribuição geográfica</p>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={porCidade} layout="vertical" margin={{ left: 8, right: 16 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#f1f5f9" />
              <XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={100} />
              <Tooltip />
              <Bar dataKey="value" fill="url(#cityBarGradient)" radius={[0, 4, 4, 0]} />
              <defs>
                <linearGradient id="cityBarGradient" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#6366f1" />
                  <stop offset="100%" stopColor="#8b5cf6" />
                </linearGradient>
              </defs>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Por Porte */}
      <div className="rounded-2xl bg-white/80 border border-slate-200/50 p-6 shadow-lg hover:shadow-xl transition-colors duration-300">
        <h3 className="font-semibold text-slate-800 text-lg mb-1">Por Porte</h3>
        <p className="text-xs text-slate-400 mb-5">Distribuição por porte da empresa</p>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={porPorte}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={90}
                paddingAngle={2}
                dataKey="value"
              >
                {porPorte.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Com Divida */}
      <div className="rounded-2xl bg-white/80 border border-slate-200/50 p-6 shadow-lg hover:shadow-xl transition-colors duration-300 md:col-span-2">
        <h3 className="font-semibold text-slate-800 text-lg mb-1">Dívida Ativa</h3>
        <p className="text-xs text-slate-400 mb-5">Empresas com vs sem dívida</p>
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={comDivida}
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={80}
                dataKey="value"
              >
                <Cell fill="#ef4444" />
                <Cell fill="#10b981" />
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
