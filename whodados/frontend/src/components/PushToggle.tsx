"use client";

import { useEffect, useState } from "react";
import { pushSuportado, pushAtivo, ativarPush, desativarPush } from "@/lib/push";

/** Liga/desliga os avisos push neste aparelho (celular ou navegador). */
export function PushToggle() {
  const [suportado, setSuportado] = useState(false);
  const [ativo, setAtivo] = useState(false);
  const [busy, setBusy] = useState(true);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    setSuportado(pushSuportado());
    pushAtivo().then((v) => { setAtivo(v); setBusy(false); });
  }, []);

  if (!suportado) return null;

  async function toggle() {
    setBusy(true);
    setMsg("");
    try {
      if (ativo) {
        await desativarPush();
        setAtivo(false);
      } else {
        const r = await ativarPush();
        if (r.ok) setAtivo(true);
        else setMsg(r.motivo ?? "Não foi possível ativar.");
      }
    } catch (e: unknown) {
      setMsg(e instanceof Error ? e.message : "Erro inesperado.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 flex items-center gap-3">
      <div className="text-2xl">{ativo ? "🔔" : "🔕"}</div>
      <div className="flex-1 min-w-0">
        <p className="font-semibold text-slate-800 text-sm">
          Avisos neste aparelho {ativo ? "ativados" : "desativados"}
        </p>
        <p className="text-xs text-slate-500">
          {ativo
            ? "Você recebe os avisos da sua empresa aqui."
            : "Ative para receber os avisos da sua empresa aqui."}
        </p>
        {msg && <p className="text-xs text-red-600 mt-1">{msg}</p>}
      </div>
      <button
        onClick={toggle}
        disabled={busy}
        className={`px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-40 ${
          ativo ? "bg-slate-100 text-slate-600 hover:bg-slate-200" : "bg-indigo-600 text-white hover:bg-indigo-700"
        }`}
      >
        {busy ? "..." : ativo ? "Desativar" : "Ativar"}
      </button>
    </div>
  );
}
