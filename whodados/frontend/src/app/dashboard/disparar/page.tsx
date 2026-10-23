"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import AbaWhatsapp from "./AbaWhatsapp";
import PainelEnvios from "./PainelEnvios";
import {
  ApiError, avancarFila, cancelarFila, enviarDisparo, enviarFollowup, getFollowupLista, getHistoricoDisparo, getMetricasModelos,
  getResumoDisparo, listarTemplates, marcarSituacaoContato,
  type ModeloMetrica, type EnvioDoDia, type FollowupDevido, type ResultadoDisparo, type ResumoDisparo, type Template,
} from "@/lib/api";

const STATUS_ROTULO: Record<string, { texto: string; cor: string }> = {
  enviado: { texto: "enviado", cor: "bg-emerald-50 text-emerald-700" },
  erro: { texto: "erro", cor: "bg-red-50 text-red-700" },
  pendente: { texto: "pendente", cor: "bg-amber-50 text-amber-700" },
};

function Carteira({ titulo, valor, dica, destaque }: { titulo: string; valor: number; dica: string; destaque?: boolean }) {
  return (
    <div className={`rounded-xl border p-4 ${destaque ? "border-emerald-300 bg-emerald-50/50" : "border-slate-200 bg-white"}`}>
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{titulo}</p>
      <p className="mt-1 text-3xl font-bold text-slate-800">{valor.toLocaleString("pt-BR")}</p>
      <p className="mt-1 text-xs text-slate-500">{dica}</p>
    </div>
  );
}

export default function DispararPage() {
  const [resumo, setResumo] = useState<ResumoDisparo | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [historico, setHistorico] = useState<EnvioDoDia[]>([]);
  const [erroCarga, setErroCarga] = useState("");

  // Modelo de follow-up nao serve de primeiro contato (e vice-versa): ja' saiu
  // um lote de "conseguiu ver meu e-mail?" para quem nunca recebeu o primeiro.
  const ehFollowup = (t: Template) => /follow/i.test(t.nome);
  // "Diagnostico gratuito" e' do outro produto da Beta (resgate de projeto): nao e' texto para salao.
  const ehModeloDeEnvio = (t: Template) => !ehFollowup(t) && !/diagn[oó]stico/i.test(t.nome);
  const [comparar, setComparar] = useState(false);

  const [aba, setAba] = useState<"email" | "followup" | "whatsapp" | "resultado">("email");
  const [quantidade, setQuantidade] = useState(20);
  // Ate' 5 modelos: cada contato recebe UM, sorteado de forma equilibrada.
  const [modelosSel, setModelosSel] = useState<number[]>([]);
  const [metricas, setMetricas] = useState<ModeloMetrica[]>([]);
  const [metricasDesde, setMetricasDesde] = useState<string | null>(null);
  const [remetente, setRemetente] = useState("");

  const [enviando, setEnviando] = useState(false);
  const [resultado, setResultado] = useState<ResultadoDisparo | null>(null);
  const [erroEnvio, setErroEnvio] = useState("");

  const [devidos, setDevidos] = useState<FollowupDevido[]>([]);
  const [templateFollowup, setTemplateFollowup] = useState<number | "">("");
  const [enviandoFollowup, setEnviandoFollowup] = useState(false);
  const [resultadoFollowup, setResultadoFollowup] = useState<ResultadoDisparo | null>(null);
  const [erroFollowup, setErroFollowup] = useState("");

  const carregar = useCallback(async () => {
    try {
      const [r, t, h, d, m] = await Promise.all([
        getResumoDisparo(), listarTemplates(), getHistoricoDisparo(), getFollowupLista(),
        getMetricasModelos().catch(() => ({ desde: null, modelos: [] as ModeloMetrica[] })),
      ]);
      setResumo(r);
      setMetricas(m.modelos);
      setMetricasDesde(m.desde);
      setTemplates(t);
      setHistorico(h);
      setDevidos(d);
      // O modelo de follow-up e' o que tem "follow" no nome; sem ele, o primeiro.
      setTemplateFollowup(atual => atual || (t.find(x => /follow/i.test(x.nome))?.id ?? ""));
      setErroCarga("");
      setModelosSel(atual => {
        if (atual.length) return atual;
        const primeiro = t.find(x => !/follow/i.test(x.nome) && !/diagn[oó]stico/i.test(x.nome));
        return primeiro?.id ? [primeiro.id] : [];
      });
      // O primeiro que ja' conectou o Gmail: quem nao conectou nao tem de onde enviar.
      setRemetente(atual => atual || (r.remetentes.find(x => x.gmail_proprio)?.username ?? r.remetentes[0]?.username ?? ""));
    } catch (e) {
      setErroCarga(e instanceof ApiError ? e.message : "Nao consegui carregar a tela.");
    }
  }, []);

  useEffect(() => { carregar(); }, [carregar]);

  // Relogio da tela: enquanto ha' fila e a pagina esta' aberta, pede a proxima
  // rodada a cada minuto (o servidor so' manda se ja' estiver na hora) e
  // atualiza os numeros. Tambem mantem o servidor acordado.
  const naFila = resumo?.fila.na_fila ?? 0;
  useEffect(() => {
    if (naFila <= 0) return;
    const t = setInterval(() => { avancarFila().catch(() => undefined).finally(carregar); }, 60_000);
    return () => clearInterval(t);
  }, [naFila, carregar]);

  const limite = resumo
    ? Math.min(resumo.max_por_clique, resumo.pode_enviar_hoje ?? resumo.max_por_clique, resumo.disponiveis)
    : 0;
  const quantidadeValida = Number.isInteger(quantidade) && quantidade > 0;
  const aEnviar = quantidadeValida ? Math.min(quantidade, limite) : 0;
  const rem = resumo?.remetentes.find(r => r.username === remetente);

  async function enviar() {
    if (!modelosSel.length || !aEnviar) return;
    const de = rem ? `${rem.email_from_name ? rem.email_from_name + " " : ""}<${rem.email_from}>` : "o remetente padrão";
    const modelo = modelosSel.map(id => templates.find(t => t.id === id)?.nome ?? String(id)).join("\n  · ");
    const ritmo = aEnviar > resumo!.por_rodada
      ? `\n\nSai ${resumo!.por_rodada} agora e o resto na fila: ${resumo!.por_rodada} a cada ${resumo!.intervalo_min[0]}-${resumo!.intervalo_min[1]} min.`
      : "";
    const sorteio = modelosSel.length > 1 ? "Modelos (cada contato recebe UM, sorteado):\n  · " : "Modelo: ";
    if (!confirm(`Enviar ${aEnviar} e-mail(s) REAIS, saindo de ${de}?\n\n${sorteio}${modelo}${ritmo}\n\nEles passam para "Em trabalho" e não serão escolhidos de novo.`)) return;
    setEnviando(true);
    setErroEnvio("");
    setResultado(null);
    try {
      setResultado(await enviarDisparo({ quantidade: aEnviar, template_ids: modelosSel, remetente: remetente || undefined }));
      await carregar();
    } catch (e) {
      setErroEnvio(e instanceof Error ? e.message : "Falha ao enviar.");
      await carregar();
    } finally {
      setEnviando(false);
    }
  }

  async function marcar(cnpj: string, situacao: "respondeu" | "sem_interesse") {
    try {
      await marcarSituacaoContato(cnpj, situacao);
      await carregar();
    } catch (e) {
      setErroFollowup(e instanceof Error ? e.message : "Nao consegui marcar.");
    }
  }

  const followupMax = resumo
    ? Math.min(resumo.max_por_clique, resumo.pode_enviar_hoje ?? resumo.max_por_clique, resumo.followup_devidos)
    : 0;

  async function enviarSeguimento() {
    if (!templateFollowup || !followupMax) return;
    const n = Math.min(Math.max(quantidade, 1), followupMax);
    const de = rem ? `<${rem.email_from}>` : "o remetente padrão";
    const modelo = templates.find(t => t.id === Number(templateFollowup))?.nome ?? "";
    if (!confirm(`Enviar o FOLLOW-UP para ${n} contato(s) que não responderam, saindo de ${de}?\n\nModelo: ${modelo}\n\nÉ o segundo e último toque: depois disso eles não entram mais na fila.`)) return;
    setEnviandoFollowup(true);
    setErroFollowup("");
    setResultadoFollowup(null);
    try {
      setResultadoFollowup(await enviarFollowup({ quantidade: n, template_id: Number(templateFollowup), remetente: remetente || undefined }));
      await carregar();
    } catch (e) {
      setErroFollowup(e instanceof Error ? e.message : "Falha ao enviar.");
      await carregar();
    } finally {
      setEnviandoFollowup(false);
    }
  }

  if (erroCarga) {
    return (
      <div className="max-w-3xl rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">
        {erroCarga}
      </div>
    );
  }
  if (!resumo) return <p className="text-sm text-slate-400">Carregando...</p>;

  const controles = (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-slate-600">Quantos</span>
            <input
              type="number" min={1} max={resumo.max_por_clique} value={Number.isNaN(quantidade) ? "" : quantidade}
              onChange={e => setQuantidade(parseInt(e.target.value, 10))}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-slate-600">Assina como</span>
            <select
              value={remetente} onChange={e => setRemetente(e.target.value)}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 outline-none focus:border-indigo-500"
            >
              {resumo.remetentes.length === 0 && <option value="">(nenhum remetente configurado)</option>}
              {resumo.remetentes.map(r => (
                <option key={r.username} value={r.username} disabled={!r.gmail_proprio}>
                  {r.email_from_name ? `${r.email_from_name} — ` : ""}{r.email_from}{!r.gmail_proprio ? " (ainda não conectou o Gmail)" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>
  );

  return (
    <div className="max-w-4xl space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-800">🚀 Disparar</h1>
        <p className="mt-1 text-sm text-slate-500">
          Escolha quantos, o modelo e quem assina. Quem receber vai para <strong>Em trabalho</strong>
          e não é escolhido de novo.
        </p>
      </header>

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Carteira titulo="Disponíveis" valor={resumo.disponiveis} dica="com e-mail, ainda sem contato" destaque />
        <Carteira titulo="Em trabalho" valor={resumo.em_trabalho} dica="já receberam o 1º e-mail" />
        <Carteira titulo="Fora do envio" valor={resumo.sem_email + resumo.contabilidade + resumo.desinteresse + resumo.compartilhado}
          dica={`${resumo.sem_email.toLocaleString("pt-BR")} sem e-mail · ${resumo.contabilidade.toLocaleString("pt-BR")} contabilidade · ${resumo.compartilhado.toLocaleString("pt-BR")} e-mail compartilhado · ${resumo.desinteresse.toLocaleString("pt-BR")} sem interesse comercial`} />
      </section>

      {resumo.fila.na_fila > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm text-indigo-700">
          <span>
            <strong>{resumo.fila.na_fila}</strong> na fila · saem {resumo.por_rodada} a cada {resumo.intervalo_min[0]}-{resumo.intervalo_min[1]} min
            {resumo.fila.proxima_rodada_em && <> · próxima por volta de {new Date(resumo.fila.proxima_rodada_em).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</>}
            {" "}(só em dia útil, das 7h às 19h30)
          </span>
          <button
            onClick={async () => {
              if (!confirm("Parar a fila? Quem ainda não saiu volta para Disponíveis.")) return;
              await cancelarFila();
              await carregar();
            }}
            className="ml-auto rounded-md border border-indigo-300 bg-white px-2.5 py-1 text-xs font-medium text-indigo-700 hover:bg-indigo-100"
          >Parar a fila</button>
        </div>
      )}

      <nav className="flex flex-wrap gap-1 border-b border-slate-200" aria-label="Tipo de contato">
        {([
          ["email", "E-mail"],
          ["followup", `Follow-up${resumo.followup_devidos ? ` (${resumo.followup_devidos})` : ""}`],
          ["whatsapp", "WhatsApp"],
          ["resultado", "Resultado"],
        ] as const).map(([id, rotulo]) => (
          <button
            key={id} onClick={() => setAba(id)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${aba === id ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-500 hover:text-slate-700"}`}
          >{rotulo}</button>
        ))}
      </nav>

      {aba === "email" && (
      <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        {controles}

        <div className="space-y-2">
          {!comparar ? (
            <label className="block text-sm">
              <span className="mb-1 block text-xs font-medium text-slate-600">Modelo do e-mail</span>
              <select
                value={modelosSel[0] ?? ""} onChange={e => setModelosSel(e.target.value ? [Number(e.target.value)] : [])}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 outline-none focus:border-indigo-500"
              >
                {templates.filter(ehModeloDeEnvio).map(t => <option key={t.id} value={t.id}>{t.nome.replace(/^Beta - /, "")}</option>)}
              </select>
            </label>
          ) : (
            <fieldset>
              <legend className="mb-1 text-xs font-medium text-slate-600">
                Escolha de 2 a 5 modelos <span className="font-normal text-slate-400">· cada contato recebe um, sorteado em partes iguais</span>
              </legend>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {templates.filter(ehModeloDeEnvio).map(t => {
                  const marcado = modelosSel.includes(t.id as number);
                  return (
                    <label key={t.id} className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${marcado ? "border-indigo-400 bg-indigo-50" : "border-slate-200 bg-white"}`}>
                      <input
                        type="checkbox" checked={marcado}
                        onChange={() => setModelosSel(atual =>
                          atual.includes(t.id as number)
                            ? atual.filter(x => x !== t.id)
                            : atual.length >= 5 ? atual : [...atual, t.id as number])}
                      />
                      <span className="truncate">{t.nome.replace(/^Beta - /, "")}</span>
                    </label>
                  );
                })}
              </div>
              {modelosSel.length > 1 && (
                <p className="mt-1.5 text-xs text-indigo-700">
                  Teste de {modelosSel.length} modelos: os contatos são divididos em partes iguais e cada um recebe só um deles.
                </p>
              )}
            </fieldset>
          )}
          <button
            type="button"
            onClick={() => { setComparar(c => !c); setModelosSel(atual => atual.slice(0, 1)); }}
            className="text-xs text-indigo-700 hover:underline"
          >{comparar ? "← voltar a um modelo só" : "Testar mais de um modelo →"}</button>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={enviar}
            disabled={enviando || !modelosSel.length || !aEnviar}
            className="rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {enviando ? "Enviando..." : aEnviar ? `Enviar ${aEnviar} agora` : "Enviar"}
          </button>
          <p className="text-xs text-slate-500">
            {quantidadeValida && quantidade > limite && limite > 0 && `Pedido de ${quantidade}; o máximo agora é ${limite}. `}
            {resumo.pode_enviar_hoje !== null && `Ainda cabem ${resumo.pode_enviar_hoje} hoje. `}
            {resumo.remetentes.length === 0 && (
              <>Cadastre o remetente em <Link href="/dashboard/configuracoes" className="underline">Configurações</Link>.</>
            )}
          </p>
        </div>

        {rem && !rem.gmail_proprio && (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
            ⚠ {rem.email_from} ainda não conectou o Gmail, então não dá para enviar por ela. A pessoa entra e conecta
            em Configurações → Meu e-mail. Sem conta conectada, nada sai.
          </p>
        )}

        {erroEnvio && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{erroEnvio}</p>}
        {resultado && (
          <div className={`rounded-lg px-3 py-2 text-sm ${resultado.enviados ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800"}`}>
            {resultado.mensagem
              ? resultado.mensagem
              : <>
                  <strong>{resultado.enviados}</strong> enviado(s) agora
                  {!!resultado.na_fila && <>, <strong>{resultado.na_fila}</strong> na fila</>}
                  {resultado.janela_fechada && <> (fora do horário de envio: a fila começa no próximo dia útil)</>}
                  {resultado.erros > 0 && <>, <strong>{resultado.erros}</strong> com erro</>}
                  {resultado.erro_rodada && <> — {resultado.erro_rodada}</>}
                  {!!resultado.barrados_na_conferencia && <>, {resultado.barrados_na_conferencia} barrado(s) na conferência do texto</>}
                  {resultado.remetente && <> · de {resultado.remetente}</>}.
                  {resultado.erros_detalhe && resultado.erros_detalhe.length > 0 && (
                    <ul className="mt-1 list-disc pl-5 text-xs">
                      {resultado.erros_detalhe.map((e, i) => <li key={i}>{e.erro}</li>)}
                    </ul>
                  )}
                </>}
          </div>
        )}
      </section>
      )}

      {aba === "followup" && (
      <section className="space-y-3 rounded-xl border border-amber-200 bg-amber-50/40 p-5 shadow-sm">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">
            Follow-up · <span className="text-amber-700">{resumo.followup_devidos}</span> devido(s)
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Quem recebeu o 1º e-mail há {resumo.dias_followup} dias ou mais e não respondeu. É o último toque: depois
            dele o contato sai da fila. Marque quem já respondeu para não incomodar.
          </p>
        </div>

        {resumo.followup_devidos > 0 && (
          <>
            {controles}
            <div className="flex flex-wrap items-end gap-3">
              <label className="block text-sm">
                <span className="mb-1 block text-xs font-medium text-slate-600">Modelo do follow-up</span>
                <select
                  value={templateFollowup} onChange={e => setTemplateFollowup(e.target.value ? Number(e.target.value) : "")}
                  className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500"
                >
                  {templates.filter(ehFollowup).map(t => <option key={t.id} value={t.id}>{t.nome}</option>)}
                </select>
              </label>
              <button
                onClick={enviarSeguimento}
                disabled={enviandoFollowup || !templateFollowup || !followupMax}
                className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-700 disabled:opacity-50"
              >
                {enviandoFollowup ? "Enviando..." : `Enviar follow-up (${Math.min(Math.max(quantidade || 1, 1), followupMax)})`}
              </button>
            </div>

            <ul className="max-h-72 divide-y divide-amber-100 overflow-y-auto rounded-lg border border-amber-100 bg-white">
              {devidos.map(d => (
                <li key={d.cnpj_completo} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
                  <span className="font-medium text-slate-700">{d.nome_fantasia || d.razao_social || d.cnpj_completo}</span>
                  <span className="text-xs text-slate-400">{d.municipio} · {d.email} · há {d.dias} dias</span>
                  <span className="ml-auto flex gap-2">
                    <button onClick={() => marcar(d.cnpj_completo, "respondeu")}
                      className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50">Respondeu</button>
                    <button onClick={() => marcar(d.cnpj_completo, "sem_interesse")}
                      className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50">Sem interesse</button>
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}

        {erroFollowup && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{erroFollowup}</p>}
        {resultadoFollowup && (
          <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            {resultadoFollowup.mensagem || <><strong>{resultadoFollowup.enviados}</strong> follow-up(s) enviado(s)
              {resultadoFollowup.erros > 0 && <>, {resultadoFollowup.erros} com erro</>}.</>}
          </p>
        )}
      </section>
      )}

      {aba === "whatsapp" && <AbaWhatsapp eu={(rem?.email_from_name || rem?.username || "").split(" ")[0]} />}

      {aba === "resultado" && (
        <>
        <PainelEnvios />
      {metricas.length > 0 && (
        <section className="space-y-2 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-800">Resultado por modelo</h2>
          <p className="text-xs text-slate-500">
            Só primeiro contato{metricasDesde ? `, desde ${new Date(metricasDesde).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })} (quando os modelos passaram a rodar juntos)` : ""}. &quot;Respondeu&quot; é o que você marca no follow-up (o sistema não lê a caixa de resposta), e
            &quot;abriu&quot; pode incluir o pré-carregamento de imagem do Gmail: compare as respostas, não só as aberturas.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-slate-400">
                <tr><th className="py-1.5 pr-3">Modelo</th><th className="px-2 text-right">Enviados</th><th className="px-2 text-right">Chegaram</th><th className="px-2 text-right">Abriram</th><th className="px-2 text-right">Clicaram</th><th className="px-2 text-right">Responderam</th><th className="px-2 text-right">Sem interesse</th></tr>
              </thead>
              <tbody>
                {metricas.map(m => {
                  const pct = (v: number) => m.enviados ? ` (${Math.round((100 * v) / m.enviados)}%)` : "";
                  return (
                    <tr key={m.id} className="border-t border-slate-100">
                      <td className="py-2 pr-3 font-medium text-slate-700">{m.nome.replace(/^Beta - Beleza - /, "")}</td>
                      <td className="px-2 text-right">{m.enviados}</td>
                      <td className="px-2 text-right">{m.entregues}</td>
                      <td className="px-2 text-right">{m.abertos}{pct(m.abertos)}</td>
                      <td className="px-2 text-right">{m.clicados}</td>
                      <td className="px-2 text-right font-semibold text-emerald-700">{m.respondeu}{pct(m.respondeu)}</td>
                      <td className="px-2 text-right">{m.sem_interesse}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {metricas.some(m => m.enviados < 100) && (
            <p className="text-xs text-amber-700">
              Ainda há modelos com menos de 100 envios: diferença de poucos pontos nessa fase pode ser sorte. Espere mais envios antes de decidir.
            </p>
          )}
        </section>
      )}

      <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-700">Últimos envios</h2>
          <button onClick={carregar} className="text-xs text-indigo-600 hover:underline">Atualizar</button>
        </div>
        {historico.length === 0 ? (
          <p className="px-5 py-6 text-sm text-slate-400">Nada enviado ainda.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {historico.map((h, i) => {
              const st = STATUS_ROTULO[h.status] || { texto: h.status, cor: "bg-slate-100 text-slate-600" };
              return (
                <li key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-2.5 text-sm">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${st.cor}`}>{st.texto}</span>
                  <span className="font-medium text-slate-700">{h.email_destino}</span>
                  <span className="truncate text-slate-400">{h.assunto}</span>
                  {h.erro && <span className="w-full text-xs text-red-600">{h.erro}</span>}
                  <span className="ml-auto text-xs text-slate-400">
                    {h.quando ? new Date(h.quando).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : ""}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
        </>
      )}
    </div>
  );
}
