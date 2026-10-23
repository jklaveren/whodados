"use client";

import { useState } from "react";
import { broadcastPush } from "@/lib/api";

/**
 * Composer de avisos (admin): escreve uma vez, chega no sino + celular de
 * todo mundo. Admin da empresa avisa a propria empresa; geral pode avisar
 * todas de uma vez.
 */
export function BroadcastComposer({ isGlobalAdmin, empresaNome }: { isGlobalAdmin: boolean; empresaNome: string }) {
  const [titulo, setTitulo] = useState("");
  const [mensagem, setMensagem] = useState("");
  const [todas, setTodas] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");

  async function enviar() {
    if (!titulo.trim()) { setResult("Escreva um título para o aviso."); return; }
    setBusy(true);
    setResult("");
    try {
      const r = await broadcastPush(titulo.trim(), mensagem.trim(), todas && isGlobalAdmin ? "todas" : "minha_empresa");
      const pushTxt = r.push_configurado
        ? `${r.push.enviados} push enviados${r.push.falhos ? ` (${r.push.falhos} falharam)` : ""}`
        : "push ainda não configurado no servidor (só foi pro sino)";
      setResult(`Aviso publicado em ${r.organizacoes} empresa(s). ${pushTxt}.`);
      setTitulo("");
      setMensagem("");
    } catch (e: unknown) {
      setResult(e instanceof Error ? e.message : "Erro ao publicar aviso.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-4 space-y-3">
      <h2 className="font-semibold text-slate-800 text-sm">📣 Avisar {todas && isGlobalAdmin ? "todas as empresas" : empresaNome}</h2>
      <input
        type="text"
        placeholder="Título do aviso"
        value={titulo}
        maxLength={120}
        onChange={(e) => setTitulo(e.target.value)}
        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 bg-white"
      />
      <textarea
        placeholder="Mensagem (opcional)"
        value={mensagem}
        maxLength={500}
        rows={2}
        onChange={(e) => setMensagem(e.target.value)}
        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 bg-white"
      />
      <div className="flex items-center justify-between gap-3 flex-wrap">
        {isGlobalAdmin ? (
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={todas} onChange={(e) => setTodas(e.target.checked)} />
            Enviar para todas as empresas
          </label>
        ) : <span />}
        <button
          onClick={enviar}
          disabled={busy}
          className="px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40"
        >
          {busy ? "Publicando..." : "Publicar aviso"}
        </button>
      </div>
      {result && <p className="text-xs text-slate-600">{result}</p>}
    </div>
  );
}
