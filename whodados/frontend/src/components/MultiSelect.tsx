"use client";

import { useMemo, useState } from "react";

export interface Option {
  value: string;
  label: string;
}

interface MultiSelectProps {
  options: Option[];
  selected: string[];
  onChange: (selected: string[]) => void;
  placeholder?: string;
}

export function MultiSelect({ options, selected, onChange, placeholder = "Selecione..." }: MultiSelectProps) {
  const [open, setOpen] = useState(false);
  const [busca, setBusca] = useState("");

  const filtradas = useMemo(
    () => options.filter(o => o.label.toLowerCase().includes(busca.toLowerCase())),
    [options, busca]
  );

  const toggle = (value: string) => {
    if (selected.includes(value)) {
      onChange(selected.filter(v => v !== value));
    } else {
      onChange([...selected, value]);
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-left text-sm outline-none focus:border-indigo-500"
      >
        {selected.length === 0
          ? placeholder
          : `${selected.length} selecionado(s)`}
      </button>
      {open && (
        <div className="absolute z-10 mt-1 w-full rounded-lg border border-slate-200 bg-white shadow-lg">
          <input
            type="text"
            value={busca}
            onChange={e => setBusca(e.target.value)}
            placeholder="Buscar..."
            className="w-full rounded-t-lg border-b border-slate-200 px-3 py-2 text-sm outline-none"
          />
          <div className="max-h-60 overflow-y-auto p-1">
            {filtradas.map(opt => (
              <label
                key={opt.value}
                className="flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-slate-50 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(opt.value)}
                  onChange={() => toggle(opt.value)}
                  className="rounded"
                />
                <span className="truncate">{opt.label}</span>
              </label>
            ))}
            {filtradas.length === 0 && (
              <div className="px-2 py-3 text-center text-sm text-slate-500">
                Nenhuma opção
              </div>
            )}
          </div>
          <div className="flex justify-between border-t border-slate-200 p-2">
            <button onClick={() => onChange([])} className="text-xs text-slate-500 hover:text-slate-700">Limpar</button>
            <button onClick={() => setOpen(false)} className="text-xs font-semibold text-indigo-600">Fechar</button>
          </div>
        </div>
      )}
    </div>
  );
}
