"use client";

import { useTema, type Tema } from "@/lib/tema";

const OPCOES: { valor: Tema; rotulo: string; icone: string }[] = [
  { valor: "claro", rotulo: "Claro", icone: "☀️" },
  { valor: "escuro", rotulo: "Escuro", icone: "🌙" },
  { valor: "sistema", rotulo: "Sistema", icone: "💻" },
];

/** Alterna entre os tres modos. `compacto` mostra so o icone do atual,
 *  para caber na barra lateral. */
export function SeletorTema({ compacto = false }: { compacto?: boolean }) {
  const { tema, efetivo, definir } = useTema();

  if (compacto) {
    const proximo: Tema = tema === "claro" ? "escuro" : tema === "escuro" ? "sistema" : "claro";
    const atual = OPCOES.find(o => o.valor === tema)!;
    return (
      <button
        onClick={() => definir(proximo)}
        title={`Tema: ${atual.rotulo}${tema === "sistema" ? ` (${efetivo})` : ""}`}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
      >
        <span>{atual.icone}</span>
        <span>Tema: {atual.rotulo}</span>
      </button>
    );
  }

  return (
    <div className="inline-flex rounded-lg border border-slate-300 p-0.5">
      {OPCOES.map(o => (
        <button
          key={o.valor}
          onClick={() => definir(o.valor)}
          className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
            tema === o.valor
              ? "bg-indigo-600 text-white"
              : "text-slate-600 hover:bg-slate-100"
          }`}
        >
          <span>{o.icone}</span>
          {o.rotulo}
        </button>
      ))}
    </div>
  );
}
