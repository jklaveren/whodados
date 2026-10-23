"use client";

import { useCallback, useEffect, useState } from "react";
import {
  buscarContato, getWhatsappLista, marcarSituacaoContato, marcarWhatsapp,
  type ContatoBusca, type FiltroSite, type WhatsappContato, type WhatsappFaltam,
} from "@/lib/api";

const GRUPO: Record<WhatsappContato["grupo"], { rotulo: string; cor: string }> = {
  abriu: { rotulo: "abriu o e-mail", cor: "bg-emerald-50 text-emerald-700" },
  email: { rotulo: "recebeu e-mail", cor: "bg-indigo-50 text-indigo-700" },
  sem_email: { rotulo: "sem e-mail", cor: "bg-amber-50 text-amber-700" },
  novo: { rotulo: "novo", cor: "bg-slate-100 text-slate-600" },
};

const POR_VEZ = 20;

const SITUACAO: Record<string, string> = {
  respondeu: "respondeu", sem_interesse: "sem interesse", desinteresse_comercial: "sem interesse comercial",
  chamado: "chamado no WhatsApp", sem_whatsapp: "sem WhatsApp",
};

/** Registrar a resposta de quem escreveu por conta propria: acha o contato pelo numero de onde ele
 *  escreveu (ou nome, CNPJ, e-mail) e marca a situacao. Vale para WhatsApp e para e-mail. */
function RegistrarResposta() {
  const [q, setQ] = useState("");
  const [achados, setAchados] = useState<ContatoBusca[] | null>(null);
  const [buscando, setBuscando] = useState(false);
  const [erro, setErro] = useState("");

  async function buscar(termo = q) {
    if (termo.trim().length < 3) { setAchados(null); return; }
    setBuscando(true);
    try { setAchados(await buscarContato(termo.trim())); setErro(""); }
    catch (e) { setErro(e instanceof Error ? e.message : "Nao consegui buscar."); }
    finally { setBuscando(false); }
  }

  async function marcar(c: ContatoBusca, qual: "respondeu" | "sem_interesse" | "chamado" | "sem_whatsapp" | "limpar") {
    try {
      if (qual === "limpar") {
        await marcarSituacaoContato(c.cnpj_completo, null);
        await marcarWhatsapp(c.cnpj_completo, null);
      } else if (qual === "chamado" || qual === "sem_whatsapp") {
        await marcarWhatsapp(c.cnpj_completo, qual);
      } else {
        await marcarSituacaoContato(c.cnpj_completo, qual);
      }
      await buscar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao consegui marcar.");
    }
  }

  const btn = "rounded-md border border-slate-300 px-2.5 py-1.5 text-xs text-slate-700 hover:bg-slate-50";
  return (
    <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
      <h3 className="text-xs font-semibold text-slate-700">Registrar uma resposta</h3>
      <p className="text-xs text-slate-500">
        Alguém respondeu por conta própria? Busque pelo número de onde escreveu, pelo nome, e-mail ou CNPJ e marque.
        Quem responde sai do follow-up e das listas.
      </p>
      <form className="flex gap-2" onSubmit={e => { e.preventDefault(); buscar(); }}>
        <input
          value={q} onChange={e => setQ(e.target.value)} placeholder="(51) 99999-9999, nome, e-mail ou CNPJ"
          className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500"
        />
        <button type="submit" disabled={buscando || q.trim().length < 3}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
          {buscando ? "Buscando..." : "Buscar"}
        </button>
      </form>
      {erro && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{erro}</p>}
      {achados && achados.length === 0 && <p className="text-sm text-slate-500">Nenhum contato encontrado.</p>}
      {achados && achados.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-100">
          {achados.map(c => (
            <li key={c.cnpj_completo} className="space-y-1.5 px-3 py-2.5 text-sm">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                <span className="font-medium text-slate-700">{c.empresa}</span>
                <span className="text-xs text-slate-400">{c.cidade} · {c.fone || "sem telefone"} · {c.email || "sem e-mail"}</span>
              </div>
              {(c.situacao || c.whatsapp) && (
                <p className="text-xs text-emerald-700">
                  Situação: {[c.situacao && SITUACAO[c.situacao], c.whatsapp && SITUACAO[c.whatsapp]].filter(Boolean).join(" · ")}
                </p>
              )}
              <div className="flex flex-wrap gap-2">
                <button onClick={() => marcar(c, "respondeu")} className={btn}>Respondeu</button>
                <button onClick={() => marcar(c, "sem_interesse")} className={btn}>Sem interesse</button>
                <button onClick={() => marcar(c, "chamado")} className={btn}>Chamei</button>
                <button onClick={() => marcar(c, "sem_whatsapp")} className={btn}>Sem WhatsApp</button>
                {(c.situacao || c.whatsapp) && <button onClick={() => marcar(c, "limpar")} className={btn}>Desfazer marcação</button>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** WhatsApp manual: o sistema escolhe quem chamar e deixa a mensagem pronta; a
 *  pessoa abre a conversa, confere e aperta enviar. Nada sai sozinho. */
export default function AbaWhatsapp({ eu }: { eu: string }) {
  const [contatos, setContatos] = useState<WhatsappContato[]>([]);
  const [faltam, setFaltam] = useState<WhatsappFaltam | null>(null);
  const [site, setSite] = useState<FiltroSite>("todos");
  const [sites, setSites] = useState<{ com: number; sem: number; outros: number } | null>(null);
  const [erro, setErro] = useState("");
  const [carregando, setCarregando] = useState(true);

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      const r = await getWhatsappLista(POR_VEZ, eu, site);
      setContatos(r.contatos);
      setFaltam(r.faltam);
      setSites(r.sites);
      setErro("");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao consegui carregar a lista.");
    } finally {
      setCarregando(false);
    }
  }, [eu, site]);

  useEffect(() => { carregar(); }, [carregar]);

  async function acao(c: WhatsappContato, qual: "chamado" | "sem_whatsapp" | "respondeu" | "sem_interesse") {
    try {
      if (qual === "chamado" || qual === "sem_whatsapp") await marcarWhatsapp(c.cnpj_completo, qual);
      else await marcarSituacaoContato(c.cnpj_completo, qual);
      setContatos(atual => atual.filter(x => x.cnpj_completo !== c.cnpj_completo));
      setFaltam(f => f ? { ...f, [c.grupo]: Math.max(0, f[c.grupo] - 1) } : f);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao consegui marcar.");
    }
  }

  const link = (c: WhatsappContato) => `https://wa.me/${c.numero}?text=${encodeURIComponent(c.texto)}`;
  const num = (n: number) => n.toLocaleString("pt-BR");

  return (
    <section className="space-y-3 rounded-xl border border-emerald-200 bg-emerald-50/30 p-5 shadow-sm">
      <div>
        <h2 className="text-sm font-semibold text-slate-800">WhatsApp · chamar à mão</h2>
        <p className="mt-0.5 text-xs text-slate-500">
          A mensagem já vem pronta. Abra a conversa, leia, envie pelo seu aparelho e volte aqui para marcar.
          Nada é enviado sozinho. Vá devagar: uns 20 a 30 por pessoa por dia.
        </p>
      </div>

      <RegistrarResposta />

      {sites && (
        <div className="flex flex-wrap items-center gap-2">
          {([
            ["todos", "Todos", sites.com + sites.sem + sites.outros],
            ["com", "Com site próprio", sites.com],
            ["sem", "Sem site", sites.sem],
          ] as [FiltroSite, string, number][]).map(([id, rotulo, n]) => (
            <button
              key={id} onClick={() => setSite(id)}
              className={`rounded-full border px-3 py-1 text-xs ${site === id
                ? "border-emerald-500 bg-emerald-50 font-semibold text-emerald-700"
                : "border-slate-300 text-slate-600 hover:bg-slate-50"}`}
            >{rotulo} · {n.toLocaleString("pt-BR")}</button>
          ))}
          {site === "com" && (
            <span className="text-xs text-slate-400">
              pelo e-mail de domínio da empresa; parte é de contabilidade ou empregador. Abra o site antes de chamar.
            </span>
          )}
        </div>
      )}

      {faltam && (
        <p className="text-xs text-slate-500">
          Faltam chamar: <strong>{num(faltam.abriu)}</strong> abriram o e-mail ·{" "}
          <strong>{num(faltam.email)}</strong> receberam e-mail · <strong>{num(faltam.sem_email)}</strong> sem e-mail ·{" "}
          <strong>{num(faltam.novo)}</strong> novos
        </p>
      )}

      {erro && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{erro}</p>}
      {carregando && contatos.length === 0 && <p className="text-sm text-slate-400">Carregando...</p>}

      <ul className="divide-y divide-emerald-100 overflow-hidden rounded-lg border border-emerald-100 bg-white">
        {contatos.map(c => (
          <li key={c.cnpj_completo} className="space-y-2 px-3 py-3 text-sm">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GRUPO[c.grupo].cor}`}>{GRUPO[c.grupo].rotulo}</span>
              <span className="font-medium text-slate-700">{c.nome}</span>
              <span className="text-xs text-slate-400">{c.empresa} · {c.cidade}</span>
              {c.tem_site && (
                <a href={c.site_url} target="_blank" rel="noopener noreferrer"
                  className="text-xs text-indigo-700 hover:underline">ver o site ↗</a>
              )}
            </div>
            <details className="text-xs text-slate-500">
              <summary className="cursor-pointer select-none">ver a mensagem</summary>
              <p className="mt-1 rounded-md bg-slate-50 p-2 text-slate-600">{c.texto}</p>
            </details>
            <div className="flex flex-wrap gap-2">
              <a
                href={link(c)} target="_blank" rel="noopener noreferrer"
                className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700"
              >Abrir no WhatsApp</a>
              <button onClick={() => acao(c, "chamado")}
                className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs text-slate-700 hover:bg-slate-50">Chamei</button>
              <button onClick={() => acao(c, "respondeu")}
                className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs text-slate-700 hover:bg-slate-50">Respondeu</button>
              <button onClick={() => acao(c, "sem_interesse")}
                className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs text-slate-700 hover:bg-slate-50">Sem interesse</button>
              <button onClick={() => acao(c, "sem_whatsapp")}
                className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs text-slate-700 hover:bg-slate-50">Sem WhatsApp</button>
            </div>
          </li>
        ))}
      </ul>

      {!carregando && contatos.length === 0 && !erro && (
        <p className="text-sm text-slate-500">Ninguém na lista agora.</p>
      )}

      <button onClick={carregar} disabled={carregando}
        className="text-xs text-emerald-700 hover:underline disabled:opacity-50">
        {carregando ? "Carregando..." : "Atualizar lista"}
      </button>
    </section>
  );
}
