"use client";

import PreviewTemplate from "@/components/PreviewTemplate";

import { useEffect, useMemo, useRef, useState } from "react";
import { listarTemplates, criarTemplate, atualizarTemplate, deletarTemplate, enviarTesteTemplate, uploadTemplateImagem, Template } from "@/lib/api";

// Destino e empresa usados no teste de template.
const TESTE_EMAIL_PADRAO = "klaverenjv@gmail.com";
const TESTE_CNPJ_PADRAO = "";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const CATEGORIAS = ["todos", "tecnologia", "comercio", "industria", "servicos"];

const CAT_COR: Record<string, string> = {
  todos: "bg-slate-100 text-slate-600",
  tecnologia: "bg-indigo-50 text-indigo-700",
  comercio: "bg-amber-50 text-amber-700",
  industria: "bg-sky-50 text-sky-700",
  servicos: "bg-emerald-50 text-emerald-700",
};

// Variaveis suportadas pelo mailer (backend/mailer/service.py::_render_template)
const VARIAVEIS: { key: string; desc: string }[] = [
  { key: "empresa", desc: "Razão social da empresa" },
  { key: "nome_fantasia", desc: "Nome fantasia" },
  { key: "cnpj", desc: "CNPJ completo" },
  { key: "cidade", desc: "Município da empresa" },
  { key: "cnae", desc: "Código CNAE" },
  { key: "cnae_descricao", desc: "Descrição do CNAE" },
  { key: "tema", desc: "Tema por categoria (ex.: transformação digital)" },
  { key: "categoria", desc: "Descrição da categoria" },
  { key: "porte", desc: "Porte da empresa" },
  { key: "imagem", desc: "Imagem do template (card)" },
];

// Mesmos valores de exemplo usados no envio de teste do backend
const EXEMPLO: Record<string, string> = {
  empresa: "Empresa Exemplo LTDA",
  nome_fantasia: "Exemplo",
  cnpj: "00000000000000",
  cidade: "Porto Alegre",
  cnae: "6201-5/01",
  cnae_descricao: "Desenvolvimento de software",
  tema: "inteligência comercial e oportunidades de negócio",
  categoria: "soluções de negócio",
  porte: "DEMAIS",
  imagem: "",
};

type FormState = { nome: string; assunto: string; corpo_html: string; corpo_texto: string; categoria_cnae: string };
const VAZIO: FormState = { nome: "", assunto: "", corpo_html: "", corpo_texto: "", categoria_cnae: "todos" };

// Modelos prontos: o usuario comeca de um deles e edita livremente.
const PRESETS: { nome: string; assunto: string; categoria_cnae: string; corpo_html: string }[] = [
  {
    nome: "Primeiro contato",
    assunto: "{{empresa}}: análise sem compromisso para {{cidade}}",
    categoria_cnae: "todos",
    corpo_html: `<div style="font-family:Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden">
  <div style="background:#4f46e5;padding:20px 32px"><p style="margin:0;color:#ffffff;font-size:18px;font-weight:bold">WhoDados</p></div>
  <div style="padding:32px">
    <p style="margin:0 0 16px;color:#0f172a;font-size:16px">Olá, time da <strong>{{empresa}}</strong>!</p>
    <p style="margin:0 0 16px;color:#334155;font-size:14px;line-height:1.6">Acompanhamos o mercado de {{cnae_descricao}} em {{cidade}} e identificamos oportunidades que podem impactar diretamente o resultado da {{empresa}}.</p>
    {{imagem}}
    <p style="margin:0 0 20px;color:#334155;font-size:14px;line-height:1.6">Nosso escritório atua exatamente nesse ponto: {{tema}}. Posso te enviar uma análise rápida, sem compromisso?</p>
    <a href="#" style="display:inline-block;background:#4f46e5;color:#ffffff;text-decoration:none;font-size:14px;font-weight:bold;padding:12px 24px;border-radius:8px">Quero a análise</a>
    <p style="margin:24px 0 0;color:#94a3b8;font-size:12px;line-height:1.5">Você recebeu este e-mail por constar na base pública de empresas ativas. Para não receber mais, responda com &quot;sair&quot;.</p>
  </div>
</div>`,
  },
  {
    nome: "Follow-up (2º toque)",
    assunto: "Chegou a ver, {{empresa}}?",
    categoria_cnae: "todos",
    corpo_html: `<div style="font-family:Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto">
  <p style="margin:0 0 16px;color:#0f172a;font-size:16px">Olá, <strong>{{empresa}}</strong>!</p>
  <p style="margin:0 0 12px;color:#334155;font-size:14px;line-height:1.6">Passando para saber se chegou a ver minha mensagem sobre {{tema}}.</p>
  <p style="margin:0 0 16px;color:#334155;font-size:14px;line-height:1.6">Sei que a rotina em {{cnae_descricao}} é corrida, então vou direto ao ponto: <strong>empresas do seu porte em {{cidade}} estão deixando dinheiro na mesa</strong> — e a análise leva menos de 5 minutos.</p>
  {{imagem}}
  <p style="margin:0 0 20px;color:#334155;font-size:14px;line-height:1.6">Faz sentido você dar uma olhada essa semana?</p>
  <a href="#" style="display:inline-block;background:#0f172a;color:#ffffff;text-decoration:none;font-size:14px;font-weight:bold;padding:12px 24px;border-radius:8px">Sim, me envie a análise</a>
  <p style="margin:24px 0 0;color:#94a3b8;font-size:12px;line-height:1.5">Se não fizer sentido agora, me avise e não insisto mais.</p>
</div>`,
  },
  {
    nome: "Reativação de inativos",
    assunto: "Ainda dá tempo de resolver isso, {{empresa}}",
    categoria_cnae: "todos",
    corpo_html: `<div style="font-family:Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden">
  <div style="padding:24px 32px;background:#f8fafc;border-bottom:1px solid #e2e8f0"><p style="margin:0;color:#0f172a;font-size:16px;font-weight:bold">Vale a pena reabrir essa conversa</p></div>
  <div style="padding:32px">
    <p style="margin:0 0 16px;color:#0f172a;font-size:16px">Olá, <strong>{{empresa}}</strong>!</p>
    <p style="margin:0 0 16px;color:#334155;font-size:14px;line-height:1.6">Há um tempo falamos sobre {{tema}} e como isso afeta empresas de {{cnae_descricao}}.</p>
    <p style="margin:0 0 16px;color:#334155;font-size:14px;line-height:1.6">Desde então o cenário em {{cidade}} mudou bastante — e a janela para agir com tranquilidade está aberta agora.</p>
    {{imagem}}
    <p style="margin:0 0 20px"><a href="#" style="display:inline-block;background:#059669;color:#ffffff;text-decoration:none;font-size:14px;font-weight:bold;padding:12px 24px;border-radius:8px">Retomar conversa</a></p>
    <p style="margin:24px 0 0;color:#94a3b8;font-size:12px;line-height:1.5">Não quer mais ouvir sobre isso? Responda &quot;cancelar&quot; e te tiro da lista.</p>
  </div>
</div>`,
  },
];

export default function TemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showModal, setShowModal] = useState(false);
  // Preview do e-mail montado -- ver o que o destinatario recebe antes de enviar.
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [temImagem, setTemImagem] = useState(false);
  const [logoV, setLogoV] = useState(0);
  const [form, setForm] = useState<FormState>(VAZIO);
  const [saving, setSaving] = useState(false);
  const [fb, setFb] = useState<{ t: "s" | "e"; m: string } | null>(null);
  const [busca, setBusca] = useState("");
  const [filtroCat, setFiltroCat] = useState("todas");

  const templatesFiltrados = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    return templates.filter(t => {
      const bateCategoria = filtroCat === "todas" || (t.categoria_cnae || "todos") === filtroCat;
      const bateBusca = !termo
        || t.nome.toLowerCase().includes(termo)
        || t.assunto.toLowerCase().includes(termo);
      return bateCategoria && bateBusca;
    });
  }, [templates, busca, filtroCat]);

  async function load() {
    try { setTemplates(await listarTemplates()); } catch (e) { setError(e instanceof Error ? e.message : "Erro"); } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  function abrirNovo() {
    setEditId(null); setTemImagem(false); setForm(VAZIO); setFb(null); setShowModal(true);
  }
  function abrirEdicao(t: Template) {
    setEditId(t.id ?? null);
    setTemImagem(!!t.tem_imagem);
    setForm({ nome: t.nome, assunto: t.assunto, corpo_html: t.corpo_html, corpo_texto: t.corpo_texto || "", categoria_cnae: t.categoria_cnae || "todos" });
    setFb(null);
    setShowModal(true);
  }
  function abrirDuplicar(t: Template) {
    // editId=null faz o handleSave criar um template novo em vez de
    // atualizar -- o resto do form vem preenchido com o template de origem.
    setEditId(null);
    setTemImagem(false);
    setForm({
      nome: `${t.nome} (cópia)`, assunto: t.assunto, corpo_html: t.corpo_html,
      corpo_texto: t.corpo_texto || "", categoria_cnae: t.categoria_cnae || "todos",
    });
    setFb(null);
    setShowModal(true);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setFb(null);
    try {
      if (editId) {
        await atualizarTemplate(editId, form);
      } else {
        const t = await criarTemplate(form);
        setEditId(t.id ?? null); // permite enviar imagem logo apos criar
      }
      await load();
      setFb({ t: "s", m: "Template salvo." });
      if (!editId) setShowModal(false);
    } catch (e) {
      setFb({ t: "e", m: e instanceof Error ? e.message : "Erro ao salvar." });
    } finally { setSaving(false); }
  }

  async function handleDelete(id: number) {
    if (!confirm("Excluir este template?")) return;
    try { await deletarTemplate(id); load(); } catch (e) { alert(e instanceof Error ? e.message : "Erro"); }
  }

  async function handleImagem(file: File | null) {
    if (!file || !editId) return;
    setFb(null);
    try {
      await uploadTemplateImagem(editId, file);
      setTemImagem(true); setLogoV(v => v + 1);
      setFb({ t: "s", m: "Imagem enviada. Use {{imagem}} no corpo para exibi-la." });
      await load();
    } catch (e) {
      setFb({ t: "e", m: e instanceof Error ? e.message : "Erro ao enviar imagem." });
    }
  }

  async function handleTestar(t: Template) {
    // Ja vem preenchido: o teste e repetido dezenas de vezes por dia e
    // redigitar e-mail e CNPJ a cada vez atrasa sem ganho nenhum.
    const para = window.prompt(`Enviar um teste de "${t.nome}" para qual e-mail?`, TESTE_EMAIL_PADRAO);
    if (!para) return;
    const cnpj = window.prompt(
      "CNPJ de uma empresa da base, para a personalização usar os dados dela. Em branco pega uma da base da empresa ativa.",
      TESTE_CNPJ_PADRAO,
    ) || undefined;
    try {
      const r = await enviarTesteTemplate(t.id!, para, cnpj);
      if (r.sucesso) alert(r.simulado ? "Teste OK (SMTP não configurado — envio simulado)." : `Teste enviado para ${para}.`);
      else alert(`Falha: ${r.erro || "erro"}`);
    } catch (e) { alert(e instanceof Error ? e.message : "Erro"); }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6 gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Templates de Email</h1>
          <p className="text-sm text-slate-500 mt-1">Modelos com pré-visualização ao vivo, variáveis automáticas e teste antes do disparo</p>
        </div>
        <button onClick={abrirNovo} className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">+ Novo Template</button>
      </div>

      {/* Busca + filtro por categoria */}
      {templates.length > 0 && (
        <div className="flex gap-2 mb-4 flex-wrap">
          <input value={busca} onChange={e => setBusca(e.target.value)} placeholder="Buscar por nome ou assunto…" className="flex-1 min-w-[200px] rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none" />
          <select value={filtroCat} onChange={e => setFiltroCat(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white">
            <option value="todas">Todas as categorias</option>
            {CATEGORIAS.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      )}

      {loading && <div className="text-center py-12 text-slate-500">Carregando...</div>}
      {error && <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 mb-4">{error}</div>}
      {!loading && templates.length === 0 && (
        <div className="text-center py-16 text-slate-400">
          <div className="text-5xl mb-4">📝</div>
          <p className="text-lg font-medium">Nenhum template cadastrado</p>
          <p className="text-sm mt-1">Clique em &quot;Novo Template&quot; — você pode começar de um modelo pronto.</p>
        </div>
      )}
      {!loading && templates.length > 0 && templatesFiltrados.length === 0 && (
        <div className="text-center py-12 text-slate-400 text-sm">Nenhum template encontrado para os filtros atuais.</div>
      )}
      {templatesFiltrados.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          {templatesFiltrados.map(t => (
            <div key={t.id} className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm hover:shadow-md transition-shadow flex gap-4">
              {t.tem_imagem
                ? <img src={`${API_BASE}/api/v1/templates/${t.id}/imagem?v=${logoV}`} alt="" className="w-16 h-16 rounded-lg object-cover border border-slate-200 shrink-0" />
                : <div className="w-16 h-16 rounded-lg bg-slate-50 border border-slate-200 flex items-center justify-center text-2xl shrink-0">📝</div>}
              <div className="flex-1 min-w-0 flex flex-col">
                <div className="flex items-center gap-2 flex-wrap mb-0.5">
                  <h3 className="font-semibold text-slate-800 truncate">{t.nome}</h3>
                  <span className={`text-[10px] uppercase px-1.5 py-0.5 rounded ${CAT_COR[t.categoria_cnae || "todos"] || CAT_COR.todos}`}>{t.categoria_cnae || "todos"}</span>
                </div>
                <p className="text-sm text-indigo-600 font-medium truncate">{t.assunto}</p>
                <p className="text-xs text-slate-400 mt-1">{(t.corpo_html || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 120) || "Sem corpo"}</p>
                <div className="mt-auto pt-3 flex items-center gap-2 flex-wrap">
                  <button onClick={() => setPreviewId(t.id!)} className="text-xs bg-amber-50 hover:bg-amber-100 text-amber-700 px-2.5 py-1.5 rounded-lg font-medium transition-colors">👁️ Preview</button>
                  <button onClick={() => handleTestar(t)} className="text-xs bg-emerald-50 hover:bg-emerald-100 text-emerald-700 px-2.5 py-1.5 rounded-lg font-medium transition-colors">✈️ Testar</button>
                  <button onClick={() => abrirEdicao(t)} className="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 px-2.5 py-1.5 rounded-lg font-medium transition-colors">✏️ Editar</button>
                  <button onClick={() => abrirDuplicar(t)} className="text-xs bg-slate-100 hover:bg-slate-200 text-slate-600 px-2.5 py-1.5 rounded-lg font-medium transition-colors">⧉ Duplicar</button>
                  <button onClick={() => handleDelete(t.id!)} className="text-xs text-slate-400 hover:text-red-500 px-1.5 py-1.5 transition-colors ml-auto" title="Excluir">🗑️</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <div className="p-6 border-b border-slate-200"><h2 className="text-lg font-bold text-slate-800">{editId ? "Editar Template" : "Novo Template"}</h2></div>
            <form onSubmit={handleSave} className="p-6 space-y-4">
              <div><label className="block text-sm font-medium text-slate-700 mb-1">Nome</label><input required value={form.nome} onChange={e => setForm({ ...form, nome: e.target.value })} placeholder="Ex: Primeiro contato" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none" /></div>
              <div><label className="block text-sm font-medium text-slate-700 mb-1">Assunto</label><input required value={form.assunto} onChange={e => setForm({ ...form, assunto: e.target.value })} placeholder="Ex: Oportunidade de parceria" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none" /></div>
              <div><label className="block text-sm font-medium text-slate-700 mb-1">Categoria (CNAE)</label>
                <select value={form.categoria_cnae} onChange={e => setForm({ ...form, categoria_cnae: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                  {CATEGORIAS.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div><label className="block text-sm font-medium text-slate-700 mb-1">Corpo (HTML)</label><textarea required rows={8} value={form.corpo_html} onChange={e => setForm({ ...form, corpo_html: e.target.value })} placeholder="<p>Olá, {{empresa}}!</p>" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none resize-y" /><p className="text-xs text-slate-400 mt-1">Variáveis: {"{{empresa}}"}, {"{{cidade}}"}, {"{{cnae_descricao}}"}, {"{{imagem}}"} (imagem do template)</p></div>

              {/* Imagem: só após o template ter id (salvar primeiro) */}
              <div className="rounded-lg border border-slate-200 p-3">
                <label className="block text-sm font-medium text-slate-700 mb-1">Imagem do template</label>
                {editId ? (
                  <div className="flex items-center gap-3">
                    {temImagem && <img src={`${API_BASE}/api/v1/templates/${editId}/imagem?v=${logoV}`} alt="Imagem" className="h-12 border rounded bg-slate-50 p-1" />}
                    <input type="file" accept="image/*" onChange={e => handleImagem(e.target.files?.[0] ?? null)} className="text-sm" />
                  </div>
                ) : (
                  <p className="text-xs text-slate-400">Salve o template primeiro para poder anexar uma imagem.</p>
                )}
              </div>

              {fb && <div className={`p-3 rounded text-sm ${fb.t === "s" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>{fb.m}</div>}
              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowModal(false)} className="flex-1 rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">Fechar</button>
                <button type="submit" disabled={saving} className="flex-1 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium">{saving ? "Salvando..." : "Salvar Template"}</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {previewId !== null && <PreviewTemplate templateId={previewId} onFechar={() => setPreviewId(null)} />}
    </div>
  );
}
