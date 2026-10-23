"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ApiError, EmpresaDetalhe, atualizarCrm, getEmpresaDetalhe,
  enviarEmailParaEmpresa, listarTemplates, previewTemplate, type Template,
  getMe, MeInfo, ItemEnriquecimento, enriquecerEmpresa, listarEnriquecimento, removerEnriquecimento,
} from "@/lib/api";

export default function EmpresaDetalhePage() {
  const params = useParams<{ cnpj: string }>();
  const cnpj = params?.cnpj ? decodeURIComponent(params.cnpj) : "";
  const [empresa, setEmpresa] = useState<EmpresaDetalhe | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [crmStatus, setCrmStatus] = useState("");
  const [crmNotas, setCrmNotas] = useState("");
  const [salvando, setSalvando] = useState(false);

  // Enriquecimento de contato via IA (so aparece pra admin -- backend tambem
  // exige, isto aqui e so pra nao mostrar um botao que vai dar 403).
  const [me, setMe] = useState<MeInfo | null>(null);
  const [enriquecimento, setEnriquecimento] = useState<ItemEnriquecimento[]>([]);
  const [enriquecendo, setEnriquecendo] = useState(false);
  const [enrFeedback, setEnrFeedback] = useState<{ tipo: "s" | "e"; msg: string } | null>(null);

  useEffect(() => {
    getMe().then(setMe).catch(() => setMe(null));
  }, []);

  useEffect(() => {
    if (!cnpj || !me?.is_admin) return;
    listarEnriquecimento(cnpj).then(setEnriquecimento).catch(() => {});
  }, [cnpj, me?.is_admin]);

  const handleEnriquecer = async () => {
    setEnriquecendo(true);
    setEnrFeedback(null);
    try {
      const r = await enriquecerEmpresa(cnpj);
      setEnriquecimento(prev => [...r.itens, ...prev]);
      setEnrFeedback({
        tipo: "s",
        msg: r.itens_encontrados > 0
          ? `${r.itens_encontrados} contato(s) encontrado(s).`
          : "Nenhum contato público novo encontrado.",
      });
    } catch (err) {
      setEnrFeedback({ tipo: "e", msg: err instanceof ApiError ? err.message : "Erro ao buscar contatos." });
    } finally {
      setEnriquecendo(false);
    }
  };

  const handleRemoverEnriquecimento = async () => {
    if (!confirm("Remover os dados de contato coletados por IA para esta empresa? Essa ação não pode ser desfeita.")) return;
    try {
      await removerEnriquecimento(cnpj);
      setEnriquecimento([]);
      setEnrFeedback({ tipo: "s", msg: "Dados removidos." });
    } catch (err) {
      setEnrFeedback({ tipo: "e", msg: err instanceof ApiError ? err.message : "Erro ao remover dados." });
    }
  };

  useEffect(() => {
    if (!cnpj) return;
    getEmpresaDetalhe(cnpj)
      .then(data => {
        setEmpresa(data);
        setCrmStatus(data.crm?.status || "");
        setCrmNotas(data.crm?.notas || "");
      })
      .catch(err => {
        if (err instanceof ApiError) setError(err.message);
        else setError("Erro ao carregar empresa");
      })
      .finally(() => setLoading(false));
  }, [cnpj]);

  const handleSalvarCrm = async () => {
    if (!empresa) return;
    setSalvando(true);
    try {
      await atualizarCrm(empresa.cnpj_completo, { status: crmStatus, notas: crmNotas });
      alert("Registro de acompanhamento atualizado!");
    } catch (err) {
      alert("Erro: " + (err instanceof ApiError ? err.message : "desconhecido"));
    } finally {
      setSalvando(false);
    }
  };

  const [emailAberto, setEmailAberto] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templateSel, setTemplateSel] = useState("");
  const [previa, setPrevia] = useState<{ assunto: string; corpo_html: string } | null>(null);
  const [emailEnviando, setEmailEnviando] = useState(false);
  const [emailFeedback, setEmailFeedback] = useState<{ tipo: "s" | "e"; msg: string } | null>(null);

  const abrirEmail = async () => {
    setEmailAberto(true);
    setEmailFeedback(null);
    setPrevia(null);
    if (!templates.length) {
      try { setTemplates(await listarTemplates()); }
      catch { setEmailFeedback({ tipo: "e", msg: "Nao consegui carregar os templates." }); }
    }
  };

  // Previa com os dados REAIS desta empresa -- mesma montagem do envio.
  const verPrevia = async (id: string) => {
    setTemplateSel(id);
    setPrevia(null);
    if (!id || !empresa) return;
    try {
      const p = await previewTemplate(Number(id), empresa.cnpj_completo);
      setPrevia({ assunto: p.assunto, corpo_html: p.corpo_html });
    } catch {
      setEmailFeedback({ tipo: "e", msg: "Nao consegui gerar a previa." });
    }
  };

  const handleEnviarEmail = async () => {
    if (!empresa || !templateSel) return;
    setEmailEnviando(true);
    setEmailFeedback(null);
    try {
      const r = await enviarEmailParaEmpresa(empresa.cnpj_completo, Number(templateSel));
      setEmailFeedback({ tipo: "s", msg: r.simulado
        ? `Simulado (sem servidor configurado): ${r.para}`
        : `E-mail enviado para ${r.para}.` });
      setEmailAberto(false);
    } catch (err) {
      setEmailFeedback({ tipo: "e", msg: err instanceof ApiError ? err.message : "Erro ao enviar." });
    } finally {
      setEmailEnviando(false);
    }
  };

  if (loading) return <div className="text-center py-12 text-slate-500">Carregando...</div>;
  if (error) return <div className="rounded-lg bg-red-50 p-4 text-red-700">{error}</div>;
  if (!empresa) return null;

  const fmt = (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

  return (
    <div className="space-y-6">
      <div>
        <Link href="/dashboard" className="text-sm text-indigo-600 hover:underline">← Voltar</Link>
        <div className="flex items-start justify-between mt-2 gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold text-slate-800">{empresa.razao_social}</h1>
            </div>
            <p className="text-slate-500 font-mono text-sm">{empresa.cnpj_completo}</p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={abrirEmail}
              className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              ✉️ Enviar e-mail
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Dados */}
        <div className="rounded-xl bg-white p-6 shadow-sm border border-slate-200">
          <h2 className="font-semibold text-slate-800 mb-4">Dados da Empresa</h2>
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between"><dt className="text-slate-500">Nome Fantasia:</dt><dd>{empresa.nome_fantasia || "-"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Porte:</dt><dd>{empresa.porte_nome || "-"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Fundação:</dt><dd>{empresa.data_fundacao || "-"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">CNAE:</dt><dd className="text-xs">{empresa.cnae_principal || "-"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Capital:</dt><dd>{fmt(empresa.capital_social)}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Telefone:</dt><dd>{empresa.contato_fone || "-"}</dd></div>
          </dl>
        </div>

        {/* CRM */}
        <div className="rounded-xl bg-white p-6 shadow-sm border border-slate-200">
          <h2 className="font-semibold text-slate-800 mb-4">Acompanhamento</h2>
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Status</label>
              <select value={crmStatus} onChange={e => setCrmStatus(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2">
                <option value="">— Selecionar —</option>
                <option value="novo">Novo</option>
                <option value="em_contato">Em Contato</option>
                <option value="negociando">Negociando</option>
                <option value="convertido">Convertido</option>
                <option value="descartado">Descartado</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Notas</label>
              <textarea value={crmNotas} onChange={e => setCrmNotas(e.target.value)} rows={6} className="w-full rounded-lg border border-slate-300 px-3 py-2" />
            </div>
            <button onClick={handleSalvarCrm} disabled={salvando} className="w-full rounded-lg bg-indigo-600 px-4 py-2 font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
              {salvando ? "Salvando..." : "Salvar acompanhamento"}
            </button>
          </div>
        </div>
      </div>

      {/* Sócios */}
      {empresa.socios && empresa.socios.length > 0 && (
        <div className="rounded-xl bg-white p-6 shadow-sm border border-slate-200">
          <h2 className="font-semibold text-slate-800 mb-4">Sócios</h2>
          <table className="w-full text-sm">
            <thead className="text-slate-700 border-b border-slate-200">
              <tr><th className="text-left pb-2">Nome</th><th className="text-left pb-2">CPF/CNPJ</th><th className="text-left pb-2">Qualificação</th></tr>
            </thead>
            <tbody>
              {empresa.socios.map((s, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="py-2 font-medium">
                    <Link
                      href={`/dashboard/socios?nome=${encodeURIComponent(s.nome_socio)}`}
                      className="text-indigo-600 hover:underline"
                      title="Ver ranking e outras empresas deste sócio"
                    >
                      {s.nome_socio}
                    </Link>
                  </td>
                  <td className="py-2 font-mono text-xs">{s.cpf_cnpj_socio || "-"}</td>
                  <td className="py-2">{s.qualif_socio || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Abordagem por e-mail: o que este lead ja' recebeu (base do teste de modelos) */}
      {empresa.abordagens && empresa.abordagens.length > 0 && (
        <div className="rounded-xl bg-white p-6 shadow-sm border border-slate-200">
          <h2 className="font-semibold text-slate-800 mb-1">Abordagem por e-mail</h2>
          {empresa.situacao_contato && (
            <p className="mb-3 text-xs text-slate-500">
              Situação: <b className="text-slate-700">{
                ({ respondeu: "respondeu", sem_interesse: "sem interesse", desinteresse_comercial: "sem interesse comercial" } as Record<string, string>)[empresa.situacao_contato] ?? empresa.situacao_contato
              }</b>
            </p>
          )}
          <ul className="divide-y divide-slate-100 text-sm">
            {empresa.abordagens.map((a, i) => (
              <li key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${a.followup ? "bg-amber-50 text-amber-700" : "bg-indigo-50 text-indigo-700"}`}>
                  {a.followup ? "Follow-up" : "1º contato"}
                </span>
                <span className="font-medium text-slate-700">{(a.modelo || "modelo não registrado").replace(/^Beta - Beleza - /, "")}</span>
                <span className="text-xs text-slate-400">
                  {a.enviado_em ? new Date(a.enviado_em).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : ""}
                </span>
                <span className="ml-auto flex gap-1.5 text-xs">
                  <span className={`rounded px-1.5 py-0.5 ${a.aberto_em ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-400"}`}>{a.aberto_em ? "abriu" : "não abriu"}</span>
                  {a.clicado_em && <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700">clicou</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Enriquecimento de contato via IA -- so admin (backend exige require_admin) */}
      {me?.is_admin && (
        <div className="rounded-xl bg-white p-6 shadow-sm border border-slate-200">
          <div className="flex items-center justify-between flex-wrap gap-2 mb-1">
            <h2 className="font-semibold text-slate-800">🔍 Contatos públicos (IA)</h2>
            <div className="flex gap-2">
              <button
                onClick={handleEnriquecer}
                disabled={enriquecendo}
                className="rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-3 py-1.5 text-xs font-medium"
              >
                {enriquecendo ? "Buscando..." : "Buscar contatos públicos"}
              </button>
              {enriquecimento.length > 0 && (
                <button
                  onClick={handleRemoverEnriquecimento}
                  className="rounded-lg border border-red-200 text-red-600 hover:bg-red-50 px-3 py-1.5 text-xs font-medium"
                >
                  🗑️ Remover dados (LGPD)
                </button>
              )}
            </div>
          </div>
          <p className="text-xs text-slate-400 mb-3">
            Busca dados de contato públicos na web (Claude + busca), sempre citando a fonte. Uso restrito a
            administradores por envolver custo de IA e dados de terceiros.
          </p>
          {enrFeedback && (
            <div className={`p-2.5 rounded text-sm mb-3 ${enrFeedback.tipo === "s" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
              {enrFeedback.msg}
            </div>
          )}
          {enriquecimento.length === 0 ? (
            <p className="text-sm text-slate-400">Nenhum contato coletado ainda para esta empresa.</p>
          ) : (
            <div className="space-y-2">
              {enriquecimento.map(item => (
                <div key={item.id} className="flex items-start justify-between gap-3 rounded-lg border border-slate-100 px-3 py-2 text-sm">
                  <div>
                    <span className="font-medium text-slate-700">{item.campo}</span>
                    {item.nome_alvo && <span className="text-slate-400"> ({item.nome_alvo})</span>}
                    <div className="text-slate-800">{item.valor}</div>
                  </div>
                  {item.fonte_url && (
                    <a href={item.fonte_url} target="_blank" rel="noreferrer" className="text-xs text-indigo-600 hover:underline shrink-0">
                      fonte ↗
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Modal WhatsApp */}
      {emailAberto && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl p-6 w-full max-w-2xl max-h-[90vh] overflow-y-auto space-y-4">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-lg font-bold text-slate-800">✉️ Enviar e-mail</h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Para <strong>{empresa.razao_social}</strong>
                  {empresa.email ? <> · {empresa.email}</> : <span className="text-red-600"> · sem e-mail cadastrado</span>}
                </p>
              </div>
              <button onClick={() => setEmailAberto(false)} className="text-slate-400 hover:text-slate-700 text-xl font-bold">✕</button>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Template</label>
              <select
                value={templateSel}
                onChange={e => verPrevia(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="">Escolha um template...</option>
                {templates.map(t => <option key={t.id} value={t.id}>{t.nome}</option>)}
              </select>
            </div>

            {previa && (
              <div className="rounded-lg border border-slate-200 overflow-hidden">
                <div className="bg-slate-50 px-3 py-2 border-b border-slate-200">
                  <p className="text-xs text-slate-500">Assunto</p>
                  <p className="text-sm font-medium text-slate-800">{previa.assunto}</p>
                </div>
                <div className="p-3 max-h-64 overflow-y-auto text-sm"
                     dangerouslySetInnerHTML={{ __html: previa.corpo_html }} />
              </div>
            )}

            {emailFeedback && (
              <div className={`rounded-lg px-3 py-2 text-sm ${emailFeedback.tipo === "s" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-700"}`}>
                {emailFeedback.msg}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button onClick={() => setEmailAberto(false)} className="px-4 py-2 rounded-lg bg-slate-200 text-slate-700 text-sm font-medium">
                Cancelar
              </button>
              <button
                onClick={handleEnviarEmail}
                disabled={emailEnviando || !templateSel || !empresa.email}
                className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium disabled:opacity-40"
              >
                {emailEnviando ? "Enviando..." : "Enviar agora"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
