"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  getResumoCarteira, importarCarteira, ApiError,
  type ResumoCarteira, type ResultadoImportacao,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

// Colunas que o importador reconhece (_COLUNAS em endpoints_carteira.py).
// Ficam visiveis porque a duvida de quem vai subir a planilha e' sempre "meu
// cabecalho serve?" -- e a resposta e' mais generosa do que parece.
const COLUNAS_ACEITAS: [string, string][] = [
  ["CNPJ", "cnpj, cnpj_completo"],
  ["Nome", "razao_social, nome, empresa, nome_fantasia, fantasia"],
  ["Local", "municipio, cidade, uf, estado"],
  ["Contato", "email, e-mail, telefone, fone, celular, whatsapp"],
  ["Atividade", "cnae, cnae_principal, atividade, cnae_descricao"],
  ["Comercial", "porte, capital, capital_social, divida, divida_total"],
  ["Livres", "categoria, segmento, tipo, situacao, status, observacao, obs"],
];

export default function CarteiraPage() {
  const { activeOrg, isAdmin } = useAuth();
  const podeImportar = isAdmin || activeOrg?.papel === "admin";

  const [resumo, setResumo] = useState<ResumoCarteira | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [resultado, setResultado] = useState<ResultadoImportacao | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      setResumo(await getResumoCarteira());
      setErro("");
    } catch (e) {
      // Erro NAO pode virar "carteira vazia": sao coisas diferentes, e
      // confundi-las levaria alguem a reimportar a planilha achando que
      // perdeu a lista.
      setErro(e instanceof ApiError ? e.message : "Não consegui carregar a carteira.");
      setResumo(null);
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => { carregar(); }, [carregar]);

  async function enviar(arquivo: File) {
    setEnviando(true);
    setErro("");
    setResultado(null);
    try {
      const r = await importarCarteira(arquivo);
      setResultado(r);
      await carregar();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não consegui importar a planilha.");
    } finally {
      setEnviando(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  if (carregando) return <div className="p-8 text-slate-500">Carregando carteira...</div>;

  // Sem lista de trabalho a tela nao tem o que mostrar -- e dizer isso e'
  // melhor que uma tela vazia, que pareceria quebrada. O criterio e' TER
  // carteira, nao o escopo: a Alfa pesquisa na base da Receita e tem lista.
  if (resumo && !resumo.tem_carteira) {
    return (
      <div className="max-w-2xl rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-8">
        <h1 className="text-lg font-bold text-slate-800">Esta empresa não usa carteira própria</h1>
        <p className="mt-2 text-sm text-slate-600">
          {activeOrg?.nome ?? "Ela"} prospecta sobre a base da Receita Federal, então não há
          lista própria para carregar. A fonte de prospecção é trocada em{" "}
          <Link href="/dashboard/configuracoes" className="text-indigo-600 underline">
            Configurações → Empresas
          </Link>
          , pelo administrador geral.
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-800">🗃️ Carteira própria</h1>
        <p className="mt-1 text-sm text-slate-500">
          A lista de empresas que {activeOrg?.nome ?? "esta empresa"} prospecta. É ela que
          alimenta a tela de Empresas, o CRM e as campanhas.
        </p>
      </header>

      {erro && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {erro}
          <button onClick={carregar} className="ml-2 font-medium underline">Tentar de novo</button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="text-[11px] uppercase tracking-wide text-slate-500">Empresas na carteira</div>
          <div className="mt-1 text-3xl font-semibold tabular-nums text-slate-800">
            {(resumo?.total ?? 0).toLocaleString("pt-BR")}
          </div>
          {!!resumo?.total && (
            <Link href="/dashboard" className="mt-2 inline-block text-sm text-indigo-600 underline">
              Ver na tela de Empresas
            </Link>
          )}
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="text-[11px] uppercase tracking-wide text-slate-500">Categorias</div>
          {resumo?.categorias?.length ? (
            <ul className="mt-2 space-y-1 text-sm">
              {resumo.categorias.slice(0, 6).map(c => (
                <li key={c.categoria} className="flex justify-between gap-3">
                  <span className="truncate text-slate-700">{c.categoria || "(sem categoria)"}</span>
                  <span className="tabular-nums text-slate-500">{c.total.toLocaleString("pt-BR")}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-slate-500">
              Nenhuma ainda. A coluna <code className="text-xs">categoria</code> da planilha vira o
              filtro que substitui o CNAE aqui.
            </p>
          )}
        </div>
      </div>

      {podeImportar ? (
        <div className="rounded-xl border border-slate-200 bg-white p-5 space-y-3">
          <h2 className="font-semibold text-slate-800">Carregar planilha</h2>
          <p className="text-sm text-slate-600">
            CSV, até 5 MB e 5.000 linhas por carga. <strong>Só o CNPJ é obrigatório</strong> — o
            resto entra se vier. Subir a mesma planilha de novo <strong>atualiza</strong> em vez de
            duplicar, e coluna vazia não apaga o que já estava preenchido.
          </p>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            disabled={enviando}
            onChange={e => { const f = e.target.files?.[0]; if (f) enviar(f); }}
            className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-indigo-600 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-indigo-700 disabled:opacity-40"
          />
          {enviando && <p className="text-sm text-slate-500">Importando... não feche a página.</p>}

          <details className="pt-1">
            <summary className="cursor-pointer text-sm text-slate-600">
              Que nomes de coluna são aceitos?
            </summary>
            <table className="mt-2 w-full text-xs">
              <tbody>
                {COLUNAS_ACEITAS.map(([grupo, nomes]) => (
                  <tr key={grupo} className="border-t border-slate-100">
                    <td className="py-1.5 pr-3 align-top font-medium whitespace-nowrap text-slate-700">{grupo}</td>
                    <td className="py-1.5 text-slate-500">{nomes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-slate-400">
              Maiúsculas, acentos e separador (vírgula ou ponto e vírgula) não importam. Planilha
              salva pelo Excel em português costuma funcionar sem nenhum ajuste.
            </p>
          </details>
        </div>
      ) : (
        <p className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
          Só o administrador da empresa pode carregar ou alterar a carteira.
        </p>
      )}

      {resultado && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5">
          <h3 className="font-semibold text-emerald-900">
            {resultado.salvos.toLocaleString("pt-BR")} empresa
            {resultado.salvos === 1 ? "" : "s"} carregada{resultado.salvos === 1 ? "" : "s"}
          </h3>
          <p className="mt-1 text-sm text-emerald-800">
            A carteira tem agora {resultado.total_na_carteira.toLocaleString("pt-BR")} empresas.
          </p>
          {resultado.total_ignorados > 0 && (
            <div className="mt-3 rounded-lg bg-white/70 p-3">
              <p className="text-sm font-medium text-amber-800">
                {resultado.total_ignorados.toLocaleString("pt-BR")} linha
                {resultado.total_ignorados === 1 ? "" : "s"} ficou de fora
                {resultado.ignorados.length < resultado.total_ignorados
                  ? ` (as ${resultado.ignorados.length} primeiras abaixo)`
                  : ""}
                :
              </p>
              <ul className="mt-1.5 space-y-0.5 text-xs text-amber-700">
                {resultado.ignorados.map(i => (
                  <li key={i.linha}>Linha {i.linha}: {i.motivo}</li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-amber-600">
                Corrija essas linhas na planilha e suba de novo — as que já entraram serão
                atualizadas, não duplicadas.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
