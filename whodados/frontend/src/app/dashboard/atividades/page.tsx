"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import AcompanhamentoAtividade from "@/components/AcompanhamentoAtividade";
import { useAuth } from "@/lib/auth-context";
import {
  listarTodasAtividades, moverAtividadeCrm, deletarAtividadeCrm,
  criarAtividadeAvulsa, buscarEmpresaRapido, listarUsuariosOrg,
  AtividadeCrm, StatusAtividade, UsuarioOrg, EmpresaBusca,
} from "@/lib/api";

const COLUNAS: { status: StatusAtividade; label: string; cor: string }[] = [
  { status: "pendente", label: "A fazer", cor: "border-slate-300 bg-slate-50" },
  { status: "em_andamento", label: "Em andamento", cor: "border-sky-300 bg-sky-50" },
  { status: "concluida", label: "Concluída", cor: "border-emerald-300 bg-emerald-50" },
];

const TIPO_ICONE: Record<string, string> = {
  tarefa: "📋", ligacao: "📞", reuniao: "🗓️", email: "📧", outro: "•",
};

// Toda atividade ja' nasce com prazo (2 dias a frente) -- sem prazo ela nunca
// fica vermelha e some do radar. Da' pra limpar ou trocar no formulario.
function formVazio() {
  return { titulo: "", tipo: "tarefa", responsavel_user_id: "", prazo: emDias(2), descricao: "" };
}

const SEMAFORO: Record<string, { ponto: string; barra: string; rotulo: string }> = {
  verde:    { ponto: "bg-emerald-500", barra: "bg-emerald-500", rotulo: "No prazo" },
  amarelo:  { ponto: "bg-amber-500",   barra: "bg-amber-500",   rotulo: "Vence logo" },
  vermelho: { ponto: "bg-red-500",     barra: "bg-red-500",     rotulo: "Atrasada" },
  cinza:    { ponto: "bg-slate-300",   barra: "bg-slate-300",   rotulo: "Concluída" },
};

function textoTempo(a: AtividadeCrm): string {
  if (a.status === "concluida") return a.dias_aberta != null ? `fechada em ${a.dias_aberta}d` : "concluída";
  if (a.dias_para_prazo != null) {
    if (a.dias_para_prazo < 0) return `${Math.abs(a.dias_para_prazo)}d atrasada`;
    if (a.dias_para_prazo === 0) return "vence hoje";
    if (a.dias_para_prazo === 1) return "vence amanhã";
    return `vence em ${a.dias_para_prazo}d`;
  }
  if (a.dias_aberta == null) return "";
  return a.dias_aberta === 0 ? "aberta hoje" : `aberta há ${a.dias_aberta}d`;
}

function hojeISO(): string {
  return emDias(0);
}

function emDias(dias: number): string {
  const d = new Date();
  d.setDate(d.getDate() + dias);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function formatPrazo(prazo: string | null): { texto: string; atrasado: boolean } {
  if (!prazo) return { texto: "", atrasado: false };
  const d = new Date(prazo + "T00:00:00");
  const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
  return { texto: d.toLocaleDateString("pt-BR"), atrasado: d < hoje };
}

export default function AtividadesPage() {
  const [atividades, setAtividades] = useState<AtividadeCrm[]>([]);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState("");
  const [aberta, setAberta] = useState<number | null>(null);
  const { activeOrg } = useAuth();
  // Empresa com base propria: nao ha o que buscar pra vincular.
  const temBaseReceita = activeOrg?.escopo_base !== "carteira";
  const [movendo, setMovendo] = useState<number | null>(null);
  const [filtroResp, setFiltroResp] = useState<string>("");
  const [usuarios, setUsuarios] = useState<UsuarioOrg[]>([]);
  const [formAberto, setFormAberto] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [form, setForm] = useState(() => formVazio());
  const [buscaEmpresa, setBuscaEmpresa] = useState("");
  const [sugestoes, setSugestoes] = useState<EmpresaBusca[]>([]);
  const [empresaVinculada, setEmpresaVinculada] = useState<EmpresaBusca | null>(null);

  const carregar = async () => {
    try {
      setAtividades(await listarTodasAtividades());
    } catch {
      setErro("Erro ao carregar atividades.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    carregar();
    listarUsuariosOrg().then(setUsuarios).catch(() => {});
  }, []);

  // Busca de empresa com atraso -- nao dispara a cada tecla digitada.
  useEffect(() => {
    if (buscaEmpresa.trim().length < 3) { setSugestoes([]); return; }
    const t = setTimeout(() => {
      buscarEmpresaRapido(buscaEmpresa.trim()).then(setSugestoes).catch(() => setSugestoes([]));
    }, 350);
    return () => clearTimeout(t);
  }, [buscaEmpresa]);

  const limparForm = () => {
    setForm(formVazio());
    setBuscaEmpresa(""); setSugestoes([]); setEmpresaVinculada(null);
  };

  const criar = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.titulo.trim()) return;
    setSalvando(true);
    try {
      await criarAtividadeAvulsa({
        titulo: form.titulo.trim(),
        tipo: form.tipo,
        descricao: form.descricao.trim() || undefined,
        responsavel_user_id: form.responsavel_user_id ? Number(form.responsavel_user_id) : undefined,
        prazo: form.prazo || undefined,
        cnpj: empresaVinculada?.cnpj_completo,
      });
      limparForm();
      setFormAberto(false);
      await carregar();
    } catch {
      setErro("Não foi possível criar a atividade.");
    } finally {
      setSalvando(false);
    }
  };

  const responsaveis = useMemo(
    () => Array.from(new Set(atividades.map(a => a.responsavel_username).filter(Boolean))) as string[],
    [atividades]
  );

  const filtradas = useMemo(() => {
    const base = filtroResp ? atividades.filter(a => a.responsavel_username === filtroResp) : atividades;
    // Ordem cronológica: prazo mais próximo primeiro; sem prazo vai pro fim
    // (não tem data pra comparar, não pode furar a fila de quem tem).
    // Empate no prazo desempata pela ordem em que foram criadas.
    return [...base].sort((a, b) => {
      if (a.prazo !== b.prazo) {
        if (!a.prazo) return 1;
        if (!b.prazo) return -1;
        return a.prazo < b.prazo ? -1 : 1;
      }
      return a.criado_em < b.criado_em ? -1 : 1;
    });
  }, [atividades, filtroResp]);

  const mover = async (id: number, status: StatusAtividade) => {
    setMovendo(id);
    setAtividades(prev => prev.map(a => a.id === id ? { ...a, status } : a));
    try { await moverAtividadeCrm(id, status); }
    catch { await carregar(); }
    finally { setMovendo(null); }
  };

  const remover = async (id: number) => {
    if (!confirm("Excluir esta atividade?")) return;
    setAtividades(prev => prev.filter(a => a.id !== id));
    try { await deletarAtividadeCrm(id); } catch { await carregar(); }
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Atividades</h1>
          <p className="text-slate-500 mt-1 text-sm">
            Tarefas da equipe. Vincular a uma empresa é opcional.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {responsaveis.length > 0 && (
            <select value={filtroResp} onChange={e => setFiltroResp(e.target.value)} className="text-sm rounded-lg border border-slate-300 px-3 py-2 bg-white">
              <option value="">Todos os responsáveis</option>
              {responsaveis.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          )}
          <button
            onClick={() => setFormAberto(v => !v)}
            className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            {formAberto ? "Cancelar" : "+ Nova atividade"}
          </button>
        </div>
      </header>

      {erro && <div className="rounded-lg bg-red-50 p-4 text-red-700 text-sm">{erro}</div>}

      {formAberto && (
        <form onSubmit={criar} className="rounded-xl bg-white border border-slate-200 p-5 space-y-3 shadow-sm">
          <input
            autoFocus
            type="text"
            placeholder="O que precisa ser feito?"
            value={form.titulo}
            onChange={e => setForm({ ...form, titulo: e.target.value })}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
          />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <select value={form.tipo} onChange={e => setForm({ ...form, tipo: e.target.value })} className="rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white">
              <option value="tarefa">📋 Tarefa</option>
              <option value="ligacao">📞 Ligação</option>
              <option value="reuniao">🗓️ Reunião</option>
              <option value="email">📧 E-mail</option>
              <option value="outro">• Outro</option>
            </select>
            <select value={form.responsavel_user_id} onChange={e => setForm({ ...form, responsavel_user_id: e.target.value })} className="rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white">
              <option value="">Responsável...</option>
              {usuarios.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
            </select>
            <div className="flex flex-col gap-1">
              <label className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">Prazo</label>
              <input
                type="date"
                value={form.prazo}
                min={hojeISO()}
                onChange={e => setForm({ ...form, prazo: e.target.value })}
                onClick={e => { try { (e.target as HTMLInputElement & { showPicker?: () => void }).showPicker?.(); } catch { /* navegador sem showPicker: abre pelo icone mesmo */ } }}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm cursor-pointer focus:border-indigo-500 outline-none"
              />
              <div className="flex gap-1 flex-wrap">
                {[["Hoje", 0], ["Amanhã", 1], ["+7 dias", 7], ["+30 dias", 30]].map(([rotulo, dias]) => (
                  <button
                    key={rotulo as string}
                    type="button"
                    onClick={() => setForm({ ...form, prazo: emDias(dias as number) })}
                    className={`text-[11px] px-2 py-0.5 rounded-full border transition ${
                      form.prazo === emDias(dias as number)
                        ? "bg-indigo-600 border-indigo-600 text-white"
                        : "bg-white border-slate-200 text-slate-500 hover:border-indigo-400 hover:text-indigo-600"
                    }`}
                  >
                    {rotulo as string}
                  </button>
                ))}
                {form.prazo && (
                  <button type="button" onClick={() => setForm({ ...form, prazo: "" })} className="text-[11px] px-2 py-0.5 text-slate-400 hover:text-red-600">
                    limpar
                  </button>
                )}
              </div>
            </div>
          </div>

          {temBaseReceita && (
          <div className="relative">
            {empresaVinculada ? (
              <div className="flex items-center gap-2 text-sm bg-indigo-50 border border-indigo-200 rounded-lg px-3 py-2">
                <span className="text-indigo-800 flex-1 truncate">{empresaVinculada.razao_social}</span>
                <button type="button" onClick={() => setEmpresaVinculada(null)} className="text-indigo-400 hover:text-indigo-700 text-xs">remover</button>
              </div>
            ) : (
              <input
                type="text"
                placeholder="Vincular a uma empresa (opcional) — digite o nome ou CNPJ"
                value={buscaEmpresa}
                onChange={e => setBuscaEmpresa(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
            )}
            {sugestoes.length > 0 && !empresaVinculada && (
              <div className="absolute z-10 mt-1 w-full bg-white border border-slate-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                {sugestoes.map(emp => (
                  <button
                    key={emp.cnpj_completo}
                    type="button"
                    onClick={() => { setEmpresaVinculada(emp); setBuscaEmpresa(""); setSugestoes([]); }}
                    className="block w-full text-left px-3 py-2 text-sm hover:bg-indigo-50 border-b border-slate-100 last:border-0"
                  >
                    <span className="text-slate-800">{emp.razao_social}</span>
                    {emp.municipio && <span className="text-slate-400 text-xs"> · {emp.municipio}</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
          )}

          <textarea
            placeholder="Detalhes (opcional)"
            value={form.descricao}
            onChange={e => setForm({ ...form, descricao: e.target.value })}
            rows={2}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
          />

          <button type="submit" disabled={salvando || !form.titulo.trim()} className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white text-sm font-medium px-5 py-2 rounded-lg">
            {salvando ? "Criando..." : "Criar atividade"}
          </button>
        </form>
      )}

      {loading ? (
        <p className="text-center text-slate-400 py-12">Carregando...</p>
      ) : atividades.length === 0 ? (
        <div className="text-center py-16 bg-white rounded-2xl border border-slate-200">
          <div className="text-5xl mb-3">📋</div>
          <p className="text-slate-600 font-medium">Nenhuma atividade ainda</p>
          <p className="text-sm text-slate-400 mt-1">Use o botão "+ Nova atividade" acima para criar a primeira.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {COLUNAS.map(coluna => {
            const itens = filtradas.filter(a => a.status === coluna.status);
            return (
              <div key={coluna.status} className={`rounded-xl border ${coluna.cor} p-3 flex flex-col gap-2 min-h-[300px]`}>
                <div className="flex items-center justify-between px-1">
                  <h2 className="text-sm font-semibold text-slate-700">{coluna.label}</h2>
                  <span className="text-xs font-medium text-slate-500 bg-white rounded-full px-2 py-0.5">{itens.length}</span>
                </div>

                {itens.length === 0 && <p className="text-xs text-slate-400 px-1 py-4 text-center">Nada aqui</p>}

                {itens.map(a => {
                  const prazo = formatPrazo(a.prazo);
                  return (
                    <div key={a.id} className="bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
                      <div className={`h-1 ${(SEMAFORO[a.semaforo] || SEMAFORO.cinza).barra}`} />
                      <div className="p-3">
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-sm font-medium text-slate-800">
                          {TIPO_ICONE[a.tipo] || "•"} {a.titulo}
                        </p>
                        <button onClick={() => remover(a.id)} className="text-slate-300 hover:text-red-500 text-xs shrink-0" title="Excluir">✕</button>
                      </div>
                      {a.cnpj && (
                        <Link href={`/dashboard/empresa/${encodeURIComponent(a.cnpj)}`} className="text-xs text-indigo-600 hover:underline line-clamp-1 block mt-1">
                          {a.razao_social || a.cnpj}
                        </Link>
                      )}
                      <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                        {a.responsavel_username && (
                          <span className="text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded-full">{a.responsavel_username}</span>
                        )}
                        {prazo.texto && (
                          <span className={`text-xs px-1.5 py-0.5 rounded-full ${prazo.atrasado && a.status !== "concluida" ? "bg-red-100 text-red-700" : "bg-slate-100 text-slate-500"}`}>
                            {prazo.atrasado && a.status !== "concluida" ? "⚠️ " : ""}{prazo.texto}
                          </span>
                        )}
                        <span
                          className="text-xs text-slate-500 inline-flex items-center gap-1"
                          title={(SEMAFORO[a.semaforo] || SEMAFORO.cinza).rotulo}
                        >
                          <span className={`inline-block w-2 h-2 rounded-full ${(SEMAFORO[a.semaforo] || SEMAFORO.cinza).ponto}`} />
                          {textoTempo(a)}
                        </span>
                      </div>
                      <select
                        value={a.status}
                        disabled={movendo === a.id}
                        onChange={e => mover(a.id, e.target.value as StatusAtividade)}
                        className="mt-2 w-full text-xs border border-slate-200 rounded-md px-2 py-1 text-slate-600 disabled:opacity-50"
                      >
                        {COLUNAS.map(c => (
                          <option key={c.status} value={c.status}>Mover para: {c.label}</option>
                        ))}
                      </select>
                      <button
                        type="button"
                        onClick={() => setAberta(aberta === a.id ? null : a.id)}
                        className="mt-1.5 w-full text-xs text-slate-500 hover:text-indigo-600 text-left"
                      >
                        {aberta === a.id
                          ? "▾ Fechar acompanhamento"
                          : `▸ Acompanhamento${a.n_historico ? ` (${a.n_historico})` : ""}${a.n_anexos ? ` 📎${a.n_anexos}` : ""}`}
                      </button>
                      {aberta === a.id && <AcompanhamentoAtividade atividade={a} onMudou={carregar} />}
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
