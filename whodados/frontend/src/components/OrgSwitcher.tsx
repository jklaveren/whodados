"use client";

import { useAuth } from "@/lib/auth-context";

/**
 * Seletor de empresa ativa (Alfa / Beta), exibido no topo do dashboard.
 * Trocar a empresa recarrega a pagina para que todas as telas rebusquem os
 * dados (CRM/campanhas/templates/monitor) sob a nova empresa.
 */
export default function OrgSwitcher() {
  const { orgs, activeOrgId, switchOrg } = useAuth();

  if (!orgs || orgs.length === 0) return null;

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Empresa</span>
      {orgs.length === 1 ? (
        <span className="rounded-lg bg-indigo-50 px-3 py-1.5 text-sm font-semibold text-indigo-700">
          {orgs[0].nome}
        </span>
      ) : (
        <select
          value={activeOrgId ?? ""}
          onChange={e => switchOrg(Number(e.target.value))}
          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-semibold text-slate-800 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          aria-label="Selecionar empresa ativa"
        >
          {orgs.map(o => (
            <option key={o.id} value={o.id}>{o.nome}</option>
          ))}
        </select>
      )}
    </div>
  );
}
