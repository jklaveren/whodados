"use client";

import { useEffect, useState } from "react";
import {
  listarHistoricoAtividade,
  comentarAtividade,
  alterarPrazoAtividade,
  listarAnexosAtividade,
  anexarArquivoAtividade,
  removerAnexoAtividade,
  baixarAnexoAtividade,
  atribuirAtividade,
  listarUsuariosOrg,
  type HistoricoAtividade,
  type AnexoAtividade,
  type AtividadeCrm,
  type UsuarioOrg,
} from "@/lib/api";

const ROTULO_STATUS: Record<string, string> = {
  pendente: "Pendente",
  em_andamento: "Em andamento",
  concluida: "Concluída",
};

function quando(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function dataBR(valor: string | null): string {
  if (!valor) return "sem prazo";
  const [a, m, d] = valor.split("-");
  return `${d}/${m}/${a}`;
}

/** Uma linha da linha do tempo, já no jeito "Operador moveu para Em andamento". */
function descrever(h: HistoricoAtividade): string {
  const autor = h.autor || "alguém";
  if (h.tipo === "comentario") return h.texto || "";
  if (h.tipo === "responsavel") {
    if (!h.para) return `${autor} tirou o responsável (era ${h.de})`;
    return `${autor} passou a tarefa ${h.de ? `de ${h.de} ` : ""}para ${h.para}`;
  }
  if (h.tipo === "anexo") return `${autor} anexou ${h.texto}`;
  if (h.tipo === "anexo_removido") return `${autor} removeu o anexo ${h.texto}`;
  if (h.tipo === "status") return `${autor} moveu de ${ROTULO_STATUS[h.de || ""] || h.de} para ${ROTULO_STATUS[h.para || ""] || h.para}`;
  return `${autor} mudou o prazo de ${dataBR(h.de)} para ${dataBR(h.para)}`;
}

const ICONE: Record<string, string> = {
  comentario: "💬", status: "🔀", prazo: "📅", anexo: "📎", anexo_removido: "🗑️", responsavel: "👤",
};

/** PDF e imagem abrem numa aba do próprio navegador; o resto o backend manda baixar. */
const ABRE_NA_TELA = ["application/pdf", "image/png", "image/jpeg", "image/webp", "image/gif"];

function tamanhoLegivel(bytes: number | null): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function iconeArquivo(mime: string | null): string {
  if (!mime) return "📄";
  if (mime.startsWith("image/")) return "🖼️";
  if (mime === "application/pdf") return "📕";
  if (mime.includes("word")) return "📘";
  if (mime.includes("sheet") || mime.includes("excel")) return "📗";
  if (mime.includes("presentation") || mime.includes("powerpoint")) return "📙";
  if (mime === "application/zip") return "🗜️";
  return "📄";
}

export default function AcompanhamentoAtividade({
  atividade,
  onMudou,
}: {
  atividade: AtividadeCrm;
  /** Chamado quando algo muda no servidor, pra lista recarregar prazo/semáforo. */
  onMudou: () => void;
}) {
  const [historico, setHistorico] = useState<HistoricoAtividade[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [texto, setTexto] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [novoPrazo, setNovoPrazo] = useState(atividade.prazo || "");
  const [anexos, setAnexos] = useState<AnexoAtividade[]>([]);
  const [enviandoArquivo, setEnviandoArquivo] = useState(false);
  const [erroArquivo, setErroArquivo] = useState("");
  const [usuarios, setUsuarios] = useState<UsuarioOrg[]>([]);

  async function carregar() {
    setCarregando(true);
    try {
      const [h, a] = await Promise.all([
        listarHistoricoAtividade(atividade.id),
        listarAnexosAtividade(atividade.id),
      ]);
      setHistorico(h);
      setAnexos(a);
    } finally {
      setCarregando(false);
    }
  }

  async function enviarArquivo(file: File | undefined) {
    if (!file) return;
    setEnviandoArquivo(true);
    setErroArquivo("");
    try {
      await anexarArquivoAtividade(atividade.id, file);
      await carregar();
      onMudou();
    } catch (e) {
      setErroArquivo(e instanceof Error ? e.message : "Não consegui anexar o arquivo");
    } finally {
      setEnviandoArquivo(false);
    }
  }

  // O anexo só sai do backend com token, então buscamos os bytes e abrimos a
  // partir de uma URL local -- não dá pra apontar um link direto pra API.
  async function abrirAnexo(anexo: AnexoAtividade, forcarDownload: boolean) {
    const { url } = await baixarAnexoAtividade(anexo.id);
    if (forcarDownload || !ABRE_NA_TELA.includes(anexo.mime || "")) {
      const a = document.createElement("a");
      a.href = url;
      a.download = anexo.nome;
      a.click();
    } else {
      window.open(url, "_blank", "noopener");
    }
    // Sem o revoke o arquivo fica preso na memória da aba até recarregar.
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  async function removerAnexo(anexo: AnexoAtividade) {
    if (!confirm(`Remover "${anexo.nome}"?`)) return;
    await removerAnexoAtividade(anexo.id);
    await carregar();
    onMudou();
  }

  // status/prazo entram nas dependencias porque a mudanca acontece FORA deste
  // painel (o select do card) e tambem vira uma linha do historico.
  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [atividade.id, atividade.status, atividade.prazo]);

  useEffect(() => {
    setNovoPrazo(atividade.prazo || "");
  }, [atividade.prazo]);

  useEffect(() => {
    listarUsuariosOrg().then(setUsuarios).catch(() => setUsuarios([]));
  }, []);

  async function trocarResponsavel(valor: string) {
    await atribuirAtividade(atividade.id, valor ? Number(valor) : null, atividade.titulo);
    await carregar();
    onMudou();
  }

  async function comentar(e: React.FormEvent) {
    e.preventDefault();
    if (!texto.trim()) return;
    setSalvando(true);
    try {
      await comentarAtividade(atividade.id, texto.trim());
      setTexto("");
      await carregar();
      onMudou();
    } finally {
      setSalvando(false);
    }
  }

  async function salvarPrazo(valor: string) {
    setNovoPrazo(valor);
    if (valor === (atividade.prazo || "")) return;
    await alterarPrazoAtividade(atividade.id, valor);
    await carregar();
    onMudou();
  }

  return (
    <div className="mt-3 pt-3 border-t border-slate-100 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <label className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">Responsável</label>
        <select
          value={atividade.responsavel_user_id ?? ""}
          onChange={e => trocarResponsavel(e.target.value)}
          className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600 bg-white"
        >
          <option value="">ninguém</option>
          {usuarios.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
        </select>
      </div>

      <div className="flex items-center gap-2">
        <label className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">Prazo</label>
        <input
          type="date"
          value={novoPrazo}
          onChange={e => salvarPrazo(e.target.value)}
          className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600 cursor-pointer"
        />
      </div>

      <div className="space-y-2 max-h-52 overflow-y-auto pr-1">
        {carregando ? (
          <p className="text-xs text-slate-400">Carregando acompanhamento...</p>
        ) : historico.length === 0 ? (
          <p className="text-xs text-slate-400">Nada registrado ainda. Escreva o primeiro comentário abaixo.</p>
        ) : (
          historico.map(h => (
            <div key={h.id} className="flex gap-2 text-xs">
              <span className="shrink-0">{ICONE[h.tipo] || "•"}</span>
              <div className="min-w-0 flex-1">
                <p className={h.tipo === "comentario" ? "text-slate-700 whitespace-pre-wrap" : "text-slate-500"}>
                  {descrever(h)}
                </p>
                <p className="text-[10px] text-slate-400 mt-0.5">
                  {h.tipo === "comentario" && h.autor ? `${h.autor} · ` : ""}
                  {quando(h.criado_em)}
                </p>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="space-y-1.5">
        {anexos.map(anexo => (
          <div key={anexo.id} className="flex items-center gap-2 text-xs bg-slate-50 rounded-md px-2 py-1.5">
            <span>{iconeArquivo(anexo.mime)}</span>
            <button
              type="button"
              onClick={() => abrirAnexo(anexo, false)}
              className="flex-1 text-left text-indigo-600 hover:underline truncate"
              title={ABRE_NA_TELA.includes(anexo.mime || "") ? "Abrir no WhoDados" : "Baixar"}
            >
              {anexo.nome}
            </button>
            <span className="text-slate-400 shrink-0">{tamanhoLegivel(anexo.tamanho)}</span>
            <button type="button" onClick={() => abrirAnexo(anexo, true)} className="text-slate-400 hover:text-indigo-600" title="Baixar">⬇</button>
            <button type="button" onClick={() => removerAnexo(anexo)} className="text-slate-300 hover:text-red-500" title="Remover">✕</button>
          </div>
        ))}

        <label className={`block text-xs text-center border border-dashed rounded-md py-2 cursor-pointer transition ${
          enviandoArquivo ? "border-slate-200 text-slate-400" : "border-slate-300 text-slate-500 hover:border-indigo-400 hover:text-indigo-600"
        }`}>
          {enviandoArquivo ? "Enviando..." : "📎 Anexar arquivo (PDF, imagem, Word, Excel — até 15 MB)"}
          <input
            type="file"
            className="hidden"
            disabled={enviandoArquivo}
            onChange={e => {
              enviarArquivo(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </label>
        {erroArquivo && <p className="text-xs text-red-600">{erroArquivo}</p>}
      </div>

      <form onSubmit={comentar} className="flex gap-2">
        <input
          type="text"
          value={texto}
          onChange={e => setTexto(e.target.value)}
          placeholder="Escrever um comentário..."
          className="flex-1 rounded-md border border-slate-200 px-2 py-1.5 text-xs outline-none focus:border-indigo-500"
        />
        <button
          type="submit"
          disabled={salvando || !texto.trim()}
          className="text-xs bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white px-3 rounded-md"
        >
          {salvando ? "..." : "Enviar"}
        </button>
      </form>
    </div>
  );
}
