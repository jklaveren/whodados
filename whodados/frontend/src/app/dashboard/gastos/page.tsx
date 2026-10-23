"use client";

import { useCallback, useEffect, useState } from "react";
import {
  listarGastos,
  resumoGastos,
  listarCategoriasGasto,
  criarGasto,
  removerGasto,
  restaurarGasto,
  type Gasto,
  type ResumoGastos,
} from "@/lib/api";

const ICONE_CATEGORIA: Record<string, string> = {
  software: "💻",
  marketing: "📣",
  infraestrutura: "🔌",
  servicos: "🧰",
  equipamento: "🖥️",
  impostos: "🧾",
  viagem: "✈️",
  outros: "•",
};

function moeda(valor: number): string {
  return valor.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function dataBR(iso: string): string {
  const [a, m, d] = iso.split("-");
  return `${d}/${m}/${a}`;
}

// Fuso local: new Date().toISOString() devolve UTC e pode cair no dia anterior.
function hojeISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function primeiroDiaDoMes(): string {
  return `${hojeISO().slice(0, 7)}-01`;
}

const FORM_VAZIO = {
  descricao: "",
  valor: "",
  data: hojeISO(),
  categoria: "outros",
  forma_pagamento: "",
  observacao: "",
};

export default function GastosPage() {
  const [gastos, setGastos] = useState<Gasto[]>([]);
  const [resumo, setResumo] = useState<ResumoGastos | null>(null);
  const [categorias, setCategorias] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState("");

  const [de, setDe] = useState(primeiroDiaDoMes());
  const [ate, setAte] = useState(hojeISO());
  const [verRemovidos, setVerRemovidos] = useState(false);

  const [formAberto, setFormAberto] = useState(false);
  const [form, setForm] = useState(FORM_VAZIO);
  const [salvando, setSalvando] = useState(false);

  const carregar = useCallback(async () => {
    setLoading(true);
    setErro("");
    try {
      const [lista, res] = await Promise.all([
        listarGastos({ de, ate, incluir_removidos: verRemovidos }),
        resumoGastos(de, ate),
      ]);
      setGastos(lista);
      setResumo(res);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não consegui carregar os gastos");
    } finally {
      setLoading(false);
    }
  }, [de, ate, verRemovidos]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  useEffect(() => {
    listarCategoriasGasto().then(setCategorias).catch(() => setCategorias([]));
  }, []);

  async function salvar(e: React.FormEvent) {
    e.preventDefault();
    const valor = Number(form.valor.replace(",", "."));
    if (!form.descricao.trim() || !valor) return;
    setSalvando(true);
    setErro("");
    try {
      await criarGasto({
        descricao: form.descricao.trim(),
        valor,
        data: form.data || undefined,
        categoria: form.categoria,
        forma_pagamento: form.forma_pagamento.trim() || undefined,
        observacao: form.observacao.trim() || undefined,
      });
      setForm({ ...FORM_VAZIO, data: form.data, categoria: form.categoria });
      setFormAberto(false);
      await carregar();
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Não consegui salvar o gasto");
    } finally {
      setSalvando(false);
    }
  }

  async function excluir(g: Gasto) {
    if (!confirm(`Excluir "${g.descricao}"? O registro fica guardado e dá pra restaurar.`)) return;
    await removerGasto(g.id);
    await carregar();
  }

  async function restaurar(g: Gasto) {
    await restaurarGasto(g.id);
    await carregar();
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Gastos</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Despesas já realizadas. Nada é apagado de vez — excluir só tira do total.
          </p>
        </div>
        <button
          onClick={() => setFormAberto(!formAberto)}
          className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium px-4 py-2 rounded-lg"
        >
          {formAberto ? "Cancelar" : "+ Novo gasto"}
        </button>
      </div>

      {erro && <div className="rounded-lg bg-red-50 p-4 text-red-700 text-sm">{erro}</div>}

      {formAberto && (
        <form onSubmit={salvar} className="rounded-xl bg-white border border-slate-200 p-5 space-y-3 shadow-sm">
          <div className="grid grid-cols-1 md:grid-cols-[2fr_1fr] gap-3">
            <input
              autoFocus
              type="text"
              placeholder="Com o que foi o gasto?"
              value={form.descricao}
              onChange={e => setForm({ ...form, descricao: e.target.value })}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
            />
            <input
              type="text"
              inputMode="decimal"
              placeholder="Valor (R$)"
              value={form.valor}
              onChange={e => setForm({ ...form, valor: e.target.value })}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">Data</label>
              <input
                type="date"
                value={form.data}
                onChange={e => setForm({ ...form, data: e.target.value })}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm cursor-pointer"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">Categoria</label>
              <select
                value={form.categoria}
                onChange={e => setForm({ ...form, categoria: e.target.value })}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white"
              >
                {categorias.map(c => (
                  <option key={c} value={c}>
                    {ICONE_CATEGORIA[c] || "•"} {c}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">Como pagou</label>
              <input
                type="text"
                placeholder="Pix, cartão, boleto..."
                value={form.forma_pagamento}
                onChange={e => setForm({ ...form, forma_pagamento: e.target.value })}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          <textarea
            placeholder="Observação (opcional)"
            value={form.observacao}
            onChange={e => setForm({ ...form, observacao: e.target.value })}
            rows={2}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
          />

          <button
            type="submit"
            disabled={salvando || !form.descricao.trim() || !form.valor}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white text-sm font-medium px-5 py-2 rounded-lg"
          >
            {salvando ? "Salvando..." : "Lançar gasto"}
          </button>
        </form>
      )}

      <div className="rounded-xl bg-white border border-slate-200 p-4 shadow-sm space-y-3">
        <div className="flex items-end gap-3 flex-wrap">
          <div className="flex flex-col gap-1">
            <label className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">De</label>
            <input type="date" value={de} onChange={e => setDe(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">Até</label>
            <input type="date" value={ate} onChange={e => setAte(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
          </div>
          <label className="flex items-center gap-1.5 text-xs text-slate-500 pb-2">
            <input type="checkbox" checked={verRemovidos} onChange={e => setVerRemovidos(e.target.checked)} />
            Mostrar excluídos
          </label>

          <div className="ml-auto text-right">
            <p className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">Total no período</p>
            <p className="text-2xl font-bold text-slate-800">{moeda(resumo?.total ?? 0)}</p>
            <p className="text-xs text-slate-400">{resumo?.quantidade ?? 0} lançamento(s)</p>
          </div>
        </div>

        {resumo && resumo.por_categoria.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1 border-t border-slate-100">
            {resumo.por_categoria.map(c => (
              <span key={c.categoria} className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full mt-2">
                {ICONE_CATEGORIA[c.categoria] || "•"} {c.categoria}: <b className="text-slate-800">{moeda(c.total)}</b>
              </span>
            ))}
          </div>
        )}
      </div>

      {loading ? (
        <p className="text-center text-slate-400 py-12">Carregando...</p>
      ) : gastos.length === 0 ? (
        <div className="text-center py-16 bg-white rounded-2xl border border-slate-200">
          <div className="text-5xl mb-3">🧾</div>
          <p className="text-slate-600 font-medium">Nenhum gasto no período</p>
          <p className="text-sm text-slate-400 mt-1">Use o botão &quot;+ Novo gasto&quot; para lançar o primeiro.</p>
        </div>
      ) : (
        <div className="rounded-xl bg-white border border-slate-200 shadow-sm divide-y divide-slate-100">
          {gastos.map(g => {
            const excluido = !!g.removido_em;
            return (
              <div key={g.id} className={`flex items-center gap-3 px-4 py-3 ${excluido ? "opacity-50" : ""}`}>
                <span className="text-lg shrink-0">{ICONE_CATEGORIA[g.categoria] || "•"}</span>
                <div className="min-w-0 flex-1">
                  <p className={`text-sm font-medium text-slate-800 ${excluido ? "line-through" : ""}`}>
                    {g.descricao}
                  </p>
                  <p className="text-xs text-slate-400">
                    {dataBR(g.data)} · {g.categoria}
                    {g.forma_pagamento ? ` · ${g.forma_pagamento}` : ""}
                    {g.criado_por ? ` · lançado por ${g.criado_por}` : ""}
                    {excluido && g.removido_por ? ` · excluído por ${g.removido_por}` : ""}
                  </p>
                  {g.observacao && <p className="text-xs text-slate-500 mt-0.5">{g.observacao}</p>}
                </div>
                <span className={`text-sm font-semibold shrink-0 ${excluido ? "text-slate-400" : "text-slate-800"}`}>
                  {moeda(Number(g.valor))}
                </span>
                {excluido ? (
                  <button onClick={() => restaurar(g)} className="text-xs text-indigo-600 hover:underline shrink-0">
                    restaurar
                  </button>
                ) : (
                  <button onClick={() => excluir(g)} className="text-slate-300 hover:text-red-500 text-xs shrink-0" title="Excluir">
                    ✕
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
