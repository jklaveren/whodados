"use client";

import { useEffect, useState } from "react";
import { previewTemplate, type PreviewEmail } from "@/lib/api";

/**
 * Mostra o e-mail do jeito que o destinatário vai receber: dados de uma
 * empresa real da base, assinatura da empresa e rodapé de descadastro.
 * O HTML vai num iframe com sandbox para o estilo do e-mail não vazar
 * para o app (e o do app não maquiar o e-mail).
 */
export default function PreviewTemplate({
  templateId,
  cnpjInicial,
  onFechar,
}: {
  templateId: number;
  cnpjInicial?: string;
  onFechar: () => void;
}) {
  const [preview, setPreview] = useState<PreviewEmail | null>(null);
  const [erro, setErro] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [cnpj, setCnpj] = useState(cnpjInicial || "");

  async function carregar(alvo?: string) {
    setCarregando(true);
    setErro("");
    try {
      setPreview(await previewTemplate(templateId, alvo));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não consegui montar o preview");
    } finally {
      setCarregando(false);
    }
  }

  useEffect(() => {
    carregar(cnpjInicial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateId]);

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4" onClick={onFechar}>
      <div
        className="bg-white rounded-2xl w-full max-w-2xl max-h-[90vh] flex flex-col shadow-xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-slate-200 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="font-semibold text-slate-800">Como o e-mail vai chegar</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Dados reais de uma empresa da base — é exatamente o que sai no envio.
            </p>
          </div>
          <button onClick={onFechar} className="text-slate-400 hover:text-slate-700 text-lg leading-none">✕</button>
        </div>

        <div className="px-5 py-3 border-b border-slate-100 flex gap-2 items-center">
          <input
            type="text"
            value={cnpj}
            onChange={e => setCnpj(e.target.value)}
            placeholder="Testar com outro CNPJ (opcional)"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs outline-none focus:border-indigo-500"
          />
          <button
            onClick={() => carregar(cnpj.replace(/\D/g, ""))}
            className="text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 px-3 py-1.5 rounded-lg"
          >
            Recarregar
          </button>
        </div>

        {carregando ? (
          <p className="p-8 text-center text-sm text-slate-400">Montando o e-mail...</p>
        ) : erro ? (
          <p className="p-8 text-center text-sm text-red-600">{erro}</p>
        ) : preview ? (
          <div className="flex-1 overflow-y-auto">
            <div className="px-5 py-3 bg-slate-50 border-b border-slate-100 text-xs space-y-1">
              <p>
                <span className="text-slate-400">Para:</span>{" "}
                <span className="text-slate-700">{preview.destinatario}</span>
                <span className="text-slate-400"> · {preview.empresa}</span>
              </p>
              <p>
                <span className="text-slate-400">Assunto:</span>{" "}
                <span className="text-slate-800 font-medium">{preview.assunto}</span>
              </p>
            </div>

            <iframe
              title="Preview do e-mail"
              sandbox=""
              srcDoc={preview.corpo_html}
              className="w-full h-[420px] border-0"
            />

            <div className="px-5 py-3 border-t border-slate-100">
              <p className="text-[11px] uppercase tracking-wide text-slate-400 font-medium mb-1.5">
                Variáveis preenchidas
              </p>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(preview.variaveis)
                  .filter(([, v]) => v)
                  .map(([k, v]) => (
                    <span key={k} className="text-[11px] bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full">
                      {k}: <span className="text-slate-800">{String(v).slice(0, 40)}</span>
                    </span>
                  ))}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
