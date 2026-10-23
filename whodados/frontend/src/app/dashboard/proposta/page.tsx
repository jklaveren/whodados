"use client";

import { useCallback, useEffect, useState } from "react";
import {
  camposDaProposta, identidadeDaEmpresa, listarPropostas, abrirProposta,
  gerarProposta, previaProposta, salvarProposta, atualizarProposta, removerProposta,
  type CampoProposta, type ConteudoProposta, type IdentidadeEmpresa, type Proposta,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const STATUS: Record<Proposta["status"], { rotulo: string; cor: string }> = {
  rascunho: { rotulo: "Rascunho", cor: "bg-slate-100 text-slate-600" },
  enviada: { rotulo: "Enviada", cor: "bg-blue-100 text-blue-700" },
  aceita: { rotulo: "Aceita", cor: "bg-emerald-100 text-emerald-700" },
  recusada: { rotulo: "Recusada", cor: "bg-slate-100 text-slate-400" },
};

/** Campos que ganham caixa alta no formulário — o resto é uma linha só. */
const LONGOS = new Set(["necessidade", "meu_diferencial", "escopo", "observacoes"]);

export default function PropostaPage() {
  const { activeOrg } = useAuth();
  const [campos, setCampos] = useState<CampoProposta[]>([]);
  const [identidade, setIdentidade] = useState<IdentidadeEmpresa | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [conteudo, setConteudo] = useState<ConteudoProposta | null>(null);
  const [html, setHtml] = useState("");
  const [texto, setTexto] = useState("");
  const [lista, setLista] = useState<Proposta[]>([]);
  const [abertaId, setAbertaId] = useState<number | null>(null);

  const [gerando, setGerando] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");
  const [copiado, setCopiado] = useState(false);

  const carregarLista = useCallback(() => {
    listarPropostas().then(setLista).catch(() => setLista([]));
  }, []);

  useEffect(() => {
    camposDaProposta().then(setCampos).catch(() => setCampos([]));
    identidadeDaEmpresa().then(setIdentidade).catch(() => setIdentidade(null));
    carregarLista();
  }, [carregarLista, activeOrg?.id]);

  async function gerar() {
    setGerando(true);
    setErro("");
    try {
      const r = await gerarProposta(form);
      setConteudo(r.conteudo);
      setHtml(r.html);
      setTexto(r.texto);
      setAbertaId(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não consegui gerar a proposta");
    } finally {
      setGerando(false);
    }
  }

  async function verComoFica(c: ConteudoProposta) {
    const r = await previaProposta(c);
    setHtml(r.html);
    setTexto(r.texto);
  }

  async function salvar() {
    if (!conteudo) return;
    const cliente = (form.cliente || "").trim();
    if (!cliente) { setErro("Diga para quem é a proposta no campo Cliente / projeto."); return; }
    setSalvando(true);
    setErro("");
    try {
      if (abertaId) {
        await atualizarProposta(abertaId, { cliente, titulo: conteudo.titulo, campos: form, conteudo });
      } else {
        const nova = await salvarProposta({ cliente, titulo: conteudo.titulo, campos: form, conteudo });
        setAbertaId(nova.id);
      }
      carregarLista();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não consegui salvar");
    } finally {
      setSalvando(false);
    }
  }

  async function abrir(id: number) {
    const p = await abrirProposta(id);
    setAbertaId(p.id);
    setForm((p.campos as Record<string, string>) || {});
    setConteudo(p.conteudo || null);
    setHtml(p.html || "");
    setTexto(p.texto || "");
  }

  async function excluir(p: Proposta) {
    if (!confirm(`Excluir a proposta para "${p.cliente}"?`)) return;
    await removerProposta(p.id);
    if (abertaId === p.id) { setAbertaId(null); setConteudo(null); setHtml(""); setTexto(""); }
    carregarLista();
  }

  function novaProposta() {
    setAbertaId(null); setForm({}); setConteudo(null); setHtml(""); setTexto(""); setErro("");
  }

  async function copiar() {
    await navigator.clipboard.writeText(texto);
    setCopiado(true);
    setTimeout(() => setCopiado(false), 2000);
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Propostas</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Você preenche o que sabe do cliente; sai uma proposta no desenho da{" "}
            {activeOrg?.nome ?? "empresa"}.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {identidade && (
            <span className="flex items-center gap-2 text-xs text-slate-500">
              <span className="w-4 h-4 rounded-full border border-slate-300"
                    style={{ backgroundColor: identidade.cor_principal }} />
              identidade da {activeOrg?.nome}
            </span>
          )}
          <button onClick={novaProposta}
                  className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium px-4 py-2 rounded-lg">
            + Nova proposta
          </button>
        </div>
      </div>

      {erro && <div className="rounded-lg bg-red-50 p-4 text-red-700 text-sm">{erro}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* o que a pessoa sabe */}
        <div className="rounded-xl bg-white border border-slate-200 p-5 space-y-3 shadow-sm">
          <h2 className="font-semibold text-slate-800 text-sm">O que você sabe</h2>
          {campos.map(c => (
            <div key={c.chave}>
              <label className="block text-xs font-medium text-slate-600 mb-1">{c.rotulo}</label>
              {LONGOS.has(c.chave) ? (
                <textarea
                  rows={2}
                  value={form[c.chave] || ""}
                  onChange={e => setForm({ ...form, [c.chave]: e.target.value })}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
                />
              ) : (
                <input
                  type="text"
                  value={form[c.chave] || ""}
                  onChange={e => setForm({ ...form, [c.chave]: e.target.value })}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
                />
              )}
            </div>
          ))}
          <button
            onClick={gerar}
            disabled={gerando}
            className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white text-sm font-medium py-2.5 rounded-lg"
          >
            {gerando ? "Escrevendo..." : "Montar a proposta"}
          </button>
          <p className="text-[11px] text-slate-400">
            Nada é gravado aqui. Você lê, ajusta e só então salva.
          </p>
        </div>

        {/* como fica */}
        <div className="rounded-xl bg-white border border-slate-200 shadow-sm overflow-hidden flex flex-col">
          <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
            <h2 className="font-semibold text-slate-800 text-sm">Como fica</h2>
            {texto && (
              <div className="flex gap-2">
                <button onClick={copiar}
                        className="text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 px-3 py-1.5 rounded-lg">
                  {copiado ? "copiado!" : "copiar texto"}
                </button>
                <button onClick={salvar} disabled={salvando}
                        className="text-xs bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 text-white px-3 py-1.5 rounded-lg">
                  {salvando ? "salvando..." : abertaId ? "salvar alterações" : "salvar proposta"}
                </button>
              </div>
            )}
          </div>

          {html ? (
            <>
              <iframe title="Proposta" sandbox="" srcDoc={html} className="w-full h-[460px] border-0" />
              {conteudo?.porque && (
                <div className="px-5 py-3 bg-amber-50 border-t border-amber-100 text-xs text-amber-900">
                  <b>Por que ficou assim:</b> {conteudo.porque}
                  <span className="block text-amber-700 mt-0.5">Isto é para você — não vai para o cliente.</span>
                </div>
              )}
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center p-10 text-center">
              <p className="text-sm text-slate-400">
                Preencha ao lado e clique em <b>Montar a proposta</b>.<br />
                O resultado aparece aqui, já nas cores da {activeOrg?.nome ?? "empresa"}.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* propostas guardadas */}
      <div className="rounded-xl bg-white border border-slate-200 shadow-sm">
        <div className="px-5 py-3 border-b border-slate-100">
          <h2 className="font-semibold text-slate-800 text-sm">
            Propostas da {activeOrg?.nome ?? "empresa"}
            {lista.length > 0 && <span className="text-slate-400 font-normal"> · {lista.length}</span>}
          </h2>
        </div>
        {lista.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-slate-400">
            Nenhuma proposta guardada ainda.
          </p>
        ) : (
          <div className="divide-y divide-slate-100">
            {lista.map(p => (
              <div key={p.id} className="flex items-center gap-3 px-5 py-3">
                <button onClick={() => abrir(p.id)} className="min-w-0 flex-1 text-left">
                  <p className="text-sm font-medium text-slate-800 truncate">{p.cliente}</p>
                  <p className="text-xs text-slate-400 truncate">
                    {p.titulo || "sem título"} · {new Date(p.criado_em).toLocaleDateString("pt-BR")}
                    {p.criado_por ? ` · ${p.criado_por}` : ""}
                  </p>
                </button>
                <select
                  value={p.status}
                  onChange={async e => {
                    await atualizarProposta(p.id, { status: e.target.value as Proposta["status"] });
                    carregarLista();
                  }}
                  className={`text-xs rounded-full px-2 py-1 border-0 ${STATUS[p.status].cor}`}
                >
                  {Object.entries(STATUS).map(([k, v]) => (
                    <option key={k} value={k}>{v.rotulo}</option>
                  ))}
                </select>
                <button onClick={() => excluir(p)}
                        className="text-slate-300 hover:text-red-500 text-xs shrink-0">✕</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
