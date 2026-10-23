"use client";
import { useState, useEffect } from "react";
import { getSistemaStatus, SistemaStatus, getSlaConfig, updateSlaConfig, SlaConfig, trocarMinhaSenha, listarUsuarios, criarUsuarioAdmin, atualizarUsuarioAdmin, excluirUsuarioAdmin, redefinirSenhaUsuarioAdmin, UsuarioAdmin, ApiError, listarOrganizacoesAdmin, getOrgEmailConfig, iniciarConexaoGmail, desconectarGmail, AlvoGmail, setOrgEmailConfig, uploadOrgLogo, definirEmpresasUsuario, Organizacao, OrgEmailConfig, definirEscopoBaseOrg, definirLimiteDiarioOrg, getMeuEmail, salvarMeuEmail, MeuEmail } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
async function get<T>(p: string) {
  const r = await fetch(`${API}${p}`, { headers: { Authorization: `Bearer ${localStorage.getItem("token") || ""}` } });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json() as T;
}
async function post<T>(p: string, b: object) {
  const r = await fetch(`${API}${p}`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("token") || ""}` }, body: JSON.stringify(b) });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json() as T;
}
interface Cfg { smtp_host: string; smtp_port: number; smtp_username: string; smtp_use_tls: boolean; email_from: string; email_from_name: string; configurado: boolean; }
interface Pres { presets: Record<string, { name: string; host: string; port: number; tls: boolean }> }

function EmailTab() {
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [pre, setPre] = useState<Record<string, { name: string; host: string; port: number; tls: boolean }>>({});
  const [sel, setSel] = useState("custom");
  const [load, setLoad] = useState(true);
  const [h, setH] = useState("");
  const [p, setP] = useState(587);
  const [u, setU] = useState("");
  const [pw, setPw] = useState("");
  const [tls, setTls] = useState(true);
  const [te, setTe] = useState("");
  const [fb, setFb] = useState<{ t: "s" | "e"; m: string } | null>(null);
  const [tt, setTt] = useState(false);
  const [et, setEt] = useState(false);
  // Falha de leitura NAO pode se passar por "nao configurado": eram
  // estados identicos na tela, e quem visse isso ia cadastrar por cima
  // do que ja' existia sem saber.
  const [erroCarga, setErroCarga] = useState("");
  useEffect(() => { (async () => { setLoad(true); try { const [c, ps] = await Promise.all([get<Cfg>("/api/v1/admin/smtp/config"), get<Pres>("/api/v1/admin/smtp/presets")]); setCfg(c); setPre(ps.presets || {}); setH(c.smtp_host); setP(c.smtp_port); setU(c.smtp_username); setTls(c.smtp_use_tls); setErroCarga(""); }
    catch (e) { setErroCarga(e instanceof Error ? e.message : "Nao consegui ler a configuracao."); }
    setLoad(false); })(); }, []);
  const selP = (k: string) => { setSel(k); const x = pre[k]; if (x?.host) { setH(x.host); setP(x.port); setTls(x.tls); } };
  const tCon = async () => { if (!h || !u || !pw) { setFb({ t: "e", m: "Preencha host, usuario e senha" }); return; } setFb(null); setTt(true); try { const r = await post<{ sucesso: boolean; message: string }>("/api/v1/admin/smtp/test-connection", { host: h, port: p, username: u, password: pw, use_tls: tls }); setFb({ t: r.sucesso ? "s" : "e", m: r.message }); } catch { setFb({ t: "e", m: "Erro" }); } setTt(false); };
  const tSend = async () => { if (!te || !te.includes("@")) { setFb({ t: "e", m: "Email invalido" }); return; } setFb(null); setEt(true); try { const r = await post<{ sucesso: boolean; message: string }>("/api/v1/admin/smtp/test-send", { para: te }); setFb({ t: r.sucesso ? "s" : "e", m: r.message }); } catch { setFb({ t: "e", m: "Erro" }); } setEt(false); };
  if (load) return <div className="p-8 text-slate-500">Carregando...</div>;
  if (erroCarga) return (
    <div className="rounded-xl border-2 border-red-200 bg-red-50 p-5">
      <h2 className="font-semibold text-red-800">Nao consegui carregar a configuracao de e-mail</h2>
      <p className="mt-1 text-sm text-red-700">{erroCarga}</p>
      <p className="mt-2 text-sm text-red-700">
        <strong>Nao cadastre por cima daqui.</strong> Pode existir configuracao salva que esta tela nao conseguiu ler. Recarregue a pagina e tente de novo.
      </p>
    </div>
  );
  return (<div className="space-y-6"><div className={`rounded-xl p-5 border-2 ${cfg?.configurado ? "bg-green-50 border-green-200" : "bg-amber-50 border-amber-200"}`}><div className="flex items-center gap-3"><div>{cfg?.configurado ? "OK" : "!"}</div><div><h2 className={`font-semibold ${cfg?.configurado ? "text-green-800" : "text-amber-800"}`}>{cfg?.configurado ? "SMTP Configurado" : "SMTP Nao Configurado"}</h2>{cfg?.configurado ? <div className="text-sm text-green-700 mt-1"><div>Servidor: <strong>{cfg.smtp_host}:{cfg.smtp_port}</strong></div><div>Usuario: <strong>{cfg.smtp_username}</strong></div></div> : <p className="text-sm text-amber-700 mt-1">Edite o arquivo .env</p>}</div></div></div><div className="rounded-xl bg-white border p-5"><h3 className="font-semibold mb-3">Provedores</h3><div className="grid grid-cols-2 md:grid-cols-4 gap-2">{Object.entries(pre).map(([k, x]) => <button key={k} onClick={() => selP(k)} className={`p-2 rounded border-2 text-sm ${sel === k ? "border-indigo-500 bg-indigo-50" : "border-slate-200"}`}>{x.name}</button>)}</div></div><div className="rounded-xl bg-white border p-5"><h3 className="font-semibold mb-3">Testar Conexao</h3><div className="grid grid-cols-2 gap-3"><input placeholder="Host" value={h} onChange={e => setH(e.target.value)} className="border rounded px-3 py-2" /><input type="number" placeholder="Porta" value={p} onChange={e => setP(Number(e.target.value))} className="border rounded px-3 py-2" /><input placeholder="Usuario" value={u} onChange={e => setU(e.target.value)} className="border rounded px-3 py-2" /><input type="password" placeholder="Senha" value={pw} onChange={e => setPw(e.target.value)} className="border rounded px-3 py-2" /></div><div className="mt-3"><label className="flex items-center gap-2"><input type="checkbox" checked={tls} onChange={e => setTls(e.target.checked)} /><span>Usar TLS</span></label></div><button onClick={tCon} disabled={tt} className="mt-3 bg-indigo-600 text-white px-4 py-2 rounded disabled:opacity-50">{tt ? "Testando..." : "Testar Conexao"}</button></div><div className="rounded-xl bg-white border p-5"><h3 className="font-semibold mb-3">Enviar Email de Teste</h3><div className="flex gap-2"><input type="email" placeholder="seu@email.com" value={te} onChange={e => setTe(e.target.value)} className="flex-1 border rounded px-3 py-2" /><button onClick={tSend} disabled={et || !cfg?.configurado} className="bg-green-600 text-white px-4 py-2 rounded disabled:opacity-50 whitespace-nowrap">{et ? "Enviando..." : "Enviar Teste"}</button></div></div>{fb && <div className={`p-4 rounded ${fb.t === "s" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>{fb.m}</div>}</div>);
}

function formatarData(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", {
      day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function SobreTab() {
  const [status, setStatus] = useState<SistemaStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const s = await getSistemaStatus();
        setStatus(s);
      } catch {
        setErro("Nao foi possivel carregar as informacoes do sistema.");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <div className="p-8 text-slate-500">Carregando...</div>;

  if (erro) {
    return <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{erro}</div>;
  }

  if (!status || !status.pipeline_ja_rodou) {
    return (
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-5">
        <h2 className="font-semibold text-amber-800">Pipeline ainda nao rodou</h2>
        <p className="text-sm text-amber-700 mt-1">
          Assim que o ETL (Receita Federal / PGFN) rodar pela primeira vez e sincronizar com o banco,
          as informacoes de atualizacao aparecem aqui.
        </p>
      </div>
    );
  }

  const cards = [
    { label: "Mes de referencia (Receita Federal)", valor: status.mes_referencia_rf || "—" },
    { label: "Trimestre de referencia (PGFN)", valor: status.trimestre_pgfn || "—" },
    { label: "Ultima extracao do pipeline", valor: formatarData(status.gerado_em) },
    { label: "Ultima sincronizacao com o banco", valor: formatarData(status.ultima_sincronizacao) },
    { label: "Matrizes ativas extraidas", valor: status.total_matrizes || "—" },
    { label: "Empresas sincronizadas no banco", valor: status.total_empresas_sincronizadas || "—" },
    { label: "Socios sincronizados no banco", valor: status.total_socios_sincronizados || "—" },
  ];

  return (
    <div className="space-y-4">
      <div className="rounded-xl bg-white border border-slate-200 divide-y divide-slate-100">
        {cards.map((c) => (
          <div key={c.label} className="flex items-center justify-between px-5 py-3">
            <span className="text-sm text-slate-500">{c.label}</span>
            <span className="text-sm font-medium text-slate-800">{c.valor}</span>
          </div>
        ))}
      </div>
      <p className="text-xs text-slate-400">
        Os dados sao atualizados automaticamente pelo pipeline (GitHub Actions), toda segunda-feira,
        ou manualmente pela aba &quot;Actions&quot; do repositorio.
      </p>
    </div>
  );
}

function PerfilTab() {
  const { username } = useAuth();
  const [senhaAtual, setSenhaAtual] = useState("");
  const [novaSenha, setNovaSenha] = useState("");
  const [confirmSenha, setConfirmSenha] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [fb, setFb] = useState<{ t: "s" | "e"; m: string } | null>(null);

  const salvar = async (e: React.FormEvent) => {
    e.preventDefault();
    setFb(null);
    if (novaSenha.length < 8) {
      setFb({ t: "e", m: "A nova senha precisa ter ao menos 8 caracteres." });
      return;
    }
    if (novaSenha !== confirmSenha) {
      setFb({ t: "e", m: "As senhas nao coincidem." });
      return;
    }
    setSalvando(true);
    try {
      const r = await trocarMinhaSenha(senhaAtual, novaSenha);
      setFb({ t: "s", m: r.message || "Senha atualizada com sucesso." });
      setSenhaAtual("");
      setNovaSenha("");
      setConfirmSenha("");
    } catch (err) {
      setFb({ t: "e", m: err instanceof ApiError ? err.message : "Erro ao atualizar a senha." });
    } finally {
      setSalvando(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="rounded-xl bg-white border p-5">
        <h3 className="font-semibold mb-1">Conta</h3>
        <p className="text-sm text-slate-500">Usuario logado: <strong>{username}</strong></p>
      </div>
      <form onSubmit={salvar} className="rounded-xl bg-white border p-5 space-y-3">
        <h3 className="font-semibold mb-1">Trocar senha</h3>
        <input type="password" placeholder="Senha atual" value={senhaAtual} onChange={e => setSenhaAtual(e.target.value)} required className="w-full border rounded px-3 py-2" />
        <input type="password" placeholder="Nova senha (min. 8 caracteres)" value={novaSenha} onChange={e => setNovaSenha(e.target.value)} required className="w-full border rounded px-3 py-2" />
        <input type="password" placeholder="Confirmar nova senha" value={confirmSenha} onChange={e => setConfirmSenha(e.target.value)} required className="w-full border rounded px-3 py-2" />
        {fb && <div className={`p-3 rounded text-sm ${fb.t === "s" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>{fb.m}</div>}
        <button type="submit" disabled={salvando} className="bg-indigo-600 text-white px-4 py-2 rounded disabled:opacity-50">{salvando ? "Salvando..." : "Salvar nova senha"}</button>
      </form>
    </div>
  );
}

function RegrasTab() {
  const { isAdmin } = useAuth();
  const [cfg, setCfg] = useState<SlaConfig | null>(null);
  const [verde, setVerde] = useState(2);
  const [amarelo, setAmarelo] = useState(5);
  const [loading, setLoading] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [fb, setFb] = useState<{ t: "s" | "e"; m: string } | null>(null);
  const [erroSla, setErroSla] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const c = await getSlaConfig();
        setCfg(c);
        setVerde(c.sla_verde_dias);
        setAmarelo(c.sla_amarelo_dias);
      } catch (e) {
        // Sem isto, os useState(2)/useState(5) ficavam na tela como se
        // fossem a regra salva -- e um Salvar depois gravava o default por
        // cima da configuracao real.
        setErroSla(e instanceof Error ? e.message : "Nao consegui ler as regras salvas.");
      }
      setLoading(false);
    })();
  }, []);

  const salvar = async () => {
    setFb(null);
    setSalvando(true);
    try {
      const c = await updateSlaConfig({ sla_verde_dias: verde, sla_amarelo_dias: amarelo });
      setCfg(c);
      setFb({ t: "s", m: "Regras atualizadas com sucesso." });
    } catch (err) {
      setFb({ t: "e", m: err instanceof ApiError ? err.message : "Erro ao salvar." });
    } finally {
      setSalvando(false);
    }
  };

  if (loading) return <div className="p-8 text-slate-500">Carregando...</div>;
  if (erroSla) return (
    <div className="rounded-xl border-2 border-red-200 bg-red-50 p-5">
      <h3 className="font-semibold text-red-800">Nao consegui carregar as regras salvas</h3>
      <p className="mt-1 text-sm text-red-700">{erroSla}</p>
      <p className="mt-2 text-sm text-red-700">
        Os campos nao sao mostrados de proposito: sem ler o que esta salvo, o formulario exibiria os valores padrao (2 e 5) como se fossem os seus, e <strong>Salvar</strong> gravaria esses padroes por cima da sua regra. Recarregue a pagina.
      </p>
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="rounded-xl bg-white border p-5 space-y-3">
        <h3 className="font-semibold">Semaforo do Monitor de E-mails</h3>
        <p className="text-sm text-slate-500">
          Define quantos dias sem resposta um e-mail pode esperar antes de virar amarelo ou vermelho no Monitor/CRM.
        </p>
        <div className="grid grid-cols-2 gap-4 max-w-md">
          <label className="text-sm text-slate-600">
            🟢 Verde (dias)
            <input type="number" min={1} value={verde} onChange={e => setVerde(Number(e.target.value))} disabled={!isAdmin} className="mt-1 w-full border rounded px-3 py-2 disabled:bg-slate-50" />
          </label>
          <label className="text-sm text-slate-600">
            🟡 Amarelo até (dias)
            <input type="number" min={1} value={amarelo} onChange={e => setAmarelo(Number(e.target.value))} disabled={!isAdmin} className="mt-1 w-full border rounded px-3 py-2 disabled:bg-slate-50" />
          </label>
        </div>
        <p className="text-xs text-slate-400">Acima de {amarelo} dias sem resposta, o status fica vermelho.</p>
        {fb && <div className={`p-3 rounded text-sm ${fb.t === "s" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>{fb.m}</div>}
        {isAdmin ? (
          <button onClick={salvar} disabled={salvando} className="bg-indigo-600 text-white px-4 py-2 rounded disabled:opacity-50">{salvando ? "Salvando..." : "Salvar regras"}</button>
        ) : (
          <p className="text-xs text-slate-400">Somente administradores podem alterar estes valores.</p>
        )}
      </div>
    </div>
  );
}

function UsuariosTab() {
  const { username: meuUsername } = useAuth();
  const [usuarios, setUsuarios] = useState<UsuarioAdmin[]>([]);
  const [orgs, setOrgs] = useState<Organizacao[]>([]);
  const [loading, setLoading] = useState(true);
  const [fb, setFb] = useState<{ t: "s" | "e"; m: string } | null>(null);
  const [mostrarNovo, setMostrarNovo] = useState(false);
  const [novoUser, setNovoUser] = useState("");
  const [novoEmail, setNovoEmail] = useState("");
  const [novaSenha, setNovaSenha] = useState("");
  const [novoAdmin, setNovoAdmin] = useState(false);
  const [novoOrgs, setNovoOrgs] = useState<number[]>([]);
  const [criando, setCriando] = useState(false);

  const carregar = async () => {
    try {
      const [us, os] = await Promise.all([listarUsuarios(), listarOrganizacoesAdmin()]);
      setUsuarios(us);
      setOrgs(os);
    } catch (err) {
      setFb({ t: "e", m: err instanceof ApiError ? err.message : "Erro ao carregar usuarios." });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { carregar(); }, []);

  const toggleOrgUsuario = async (u: UsuarioAdmin, orgId: number) => {
    setFb(null);
    const atual = u.organizacao_ids || [];
    const novos = atual.includes(orgId) ? atual.filter(id => id !== orgId) : [...atual, orgId];
    try {
      await definirEmpresasUsuario(u.id, novos);
      await carregar();
    } catch (err) {
      setFb({ t: "e", m: err instanceof ApiError ? err.message : "Erro ao definir empresas." });
    }
  };

  const toggle = async (u: UsuarioAdmin, campo: "is_admin" | "is_active") => {
    setFb(null);
    try {
      await atualizarUsuarioAdmin(u.id, { [campo]: !u[campo] });
      await carregar();
    } catch (err) {
      setFb({ t: "e", m: err instanceof ApiError ? err.message : "Erro ao atualizar usuario." });
    }
  };

  const resetarSenha = async (u: UsuarioAdmin) => {
    const nova = window.prompt(`Nova senha para ${u.username} (min. 8 caracteres):`);
    if (!nova) return;
    try {
      const r = await redefinirSenhaUsuarioAdmin(u.id, nova);
      setFb({ t: "s", m: r.message || "Senha redefinida." });
    } catch (err) {
      setFb({ t: "e", m: err instanceof ApiError ? err.message : "Erro ao redefinir senha." });
    }
  };

  const editarEmail = async (u: UsuarioAdmin) => {
    const novo = window.prompt(`E-mail de ${u.username}:`, u.email || "");
    if (novo === null) return;
    setFb(null);
    try {
      await atualizarUsuarioAdmin(u.id, { email: novo.trim() || null });
      await carregar();
      setFb({ t: "s", m: "E-mail atualizado." });
    } catch (err) {
      setFb({ t: "e", m: err instanceof ApiError ? err.message : "Erro ao atualizar e-mail." });
    }
  };

  const excluir = async (u: UsuarioAdmin) => {
    if (!window.confirm(`Excluir o usuário '${u.username}'? Esta ação não tem volta.`)) return;
    setFb(null);
    try {
      const r = await excluirUsuarioAdmin(u.id);
      await carregar();
      setFb({ t: "s", m: r.message || "Usuário excluído." });
    } catch (err) {
      setFb({ t: "e", m: err instanceof ApiError ? err.message : "Erro ao excluir usuário." });
    }
  };

  const criar = async (e: React.FormEvent) => {
    e.preventDefault();
    setFb(null);
    setCriando(true);
    try {
      await criarUsuarioAdmin({ username: novoUser, password: novaSenha, email: novoEmail || undefined, is_admin: novoAdmin, organizacao_ids: novoOrgs });
      setFb({ t: "s", m: `Usuario '${novoUser}' criado.` });
      setNovoUser(""); setNovoEmail(""); setNovaSenha(""); setNovoAdmin(false); setNovoOrgs([]); setMostrarNovo(false);
      await carregar();
    } catch (err) {
      setFb({ t: "e", m: err instanceof ApiError ? err.message : "Erro ao criar usuario." });
    } finally {
      setCriando(false);
    }
  };

  if (loading) return <div className="p-8 text-slate-500">Carregando...</div>;

  return (
    <div className="space-y-4">
      {fb && <div className={`p-3 rounded text-sm ${fb.t === "s" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>{fb.m}</div>}

      <div className="rounded-xl bg-white border divide-y divide-slate-100">
        {usuarios.map(u => (
          <div key={u.id} className="flex items-center justify-between px-5 py-3 gap-3 flex-wrap">
            <div>
              <div className="font-medium text-slate-800">{u.username} {u.username === meuUsername && <span className="text-xs text-slate-400">(você)</span>}</div>
              <div className="text-xs text-slate-500">{u.email || "sem e-mail"}</div>
            </div>
            <div className="flex items-center gap-3 text-sm flex-wrap">
              {orgs.length > 0 && (
                <div className="flex items-center gap-2 border-r border-slate-200 pr-3">
                  <span className="text-xs text-slate-400">Empresas:</span>
                  {orgs.map(o => (
                    <label key={o.id} className="flex items-center gap-1 text-slate-600">
                      <input type="checkbox" checked={(u.organizacao_ids || []).includes(o.id)} onChange={() => toggleOrgUsuario(u, o.id)} />
                      {o.nome}
                    </label>
                  ))}
                </div>
              )}
              <label className="flex items-center gap-1 text-slate-600">
                <input type="checkbox" checked={u.is_admin} onChange={() => toggle(u, "is_admin")} />
                Admin
              </label>
              <label className="flex items-center gap-1 text-slate-600">
                <input type="checkbox" checked={u.is_active} onChange={() => toggle(u, "is_active")} />
                Ativo
              </label>
              <button onClick={() => editarEmail(u)} className="text-slate-600 hover:underline text-xs">E-mail</button>
              <button onClick={() => resetarSenha(u)} className="text-indigo-600 hover:underline text-xs">Redefinir senha</button>
              {u.username !== meuUsername && (
                <button onClick={() => excluir(u)} className="text-red-600 hover:underline text-xs">Excluir</button>
              )}
            </div>
          </div>
        ))}
      </div>

      {mostrarNovo ? (
        <form onSubmit={criar} autoComplete="off" className="rounded-xl bg-white border p-5 space-y-3">
          <h3 className="font-semibold">Novo usuario</h3>
          <div className="grid grid-cols-2 gap-3">
            {/* autoComplete distinto do padrao "username"/"current-password" --
                sem isso o navegador oferece autopreencher com QUALQUER credencial
                salva no site (ex.: a senha SMTP da empresa, cadastrada em outra
                tela), porque o par texto+senha aqui parece um login comum. */}
            <input placeholder="Usuario" name="novo-usuario-login" autoComplete="off" value={novoUser} onChange={e => setNovoUser(e.target.value)} required className="border rounded px-3 py-2" />
            <input type="email" placeholder="E-mail (opcional)" name="novo-usuario-email" autoComplete="off" value={novoEmail} onChange={e => setNovoEmail(e.target.value)} className="border rounded px-3 py-2" />
            <input type="password" placeholder="Senha (min. 8 caracteres)" name="novo-usuario-senha" autoComplete="new-password" value={novaSenha} onChange={e => setNovaSenha(e.target.value)} required className="border rounded px-3 py-2" />
            <label className="flex items-center gap-2 text-sm text-slate-600">
              <input type="checkbox" checked={novoAdmin} onChange={e => setNovoAdmin(e.target.checked)} />
              Administrador
            </label>
          </div>
          {orgs.length > 0 && (
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-sm text-slate-500">Empresas que pode acessar:</span>
              {orgs.map(o => (
                <label key={o.id} className="flex items-center gap-1 text-sm text-slate-600">
                  <input type="checkbox" checked={novoOrgs.includes(o.id)} onChange={e => setNovoOrgs(v => e.target.checked ? [...v, o.id] : v.filter(id => id !== o.id))} />
                  {o.nome}
                </label>
              ))}
            </div>
          )}
          <div className="flex gap-2">
            <button type="submit" disabled={criando} className="bg-indigo-600 text-white px-4 py-2 rounded disabled:opacity-50">{criando ? "Criando..." : "Criar usuario"}</button>
            <button type="button" onClick={() => setMostrarNovo(false)} className="px-4 py-2 rounded text-slate-600 hover:bg-slate-100">Cancelar</button>
          </div>
        </form>
      ) : (
        <button onClick={() => setMostrarNovo(true)} className="bg-indigo-600 text-white px-4 py-2 rounded">+ Novo usuario</button>
      )}
    </div>
  );
}

function EmpresasTab() {
  const [orgs, setOrgs] = useState<Organizacao[]>([]);
  const [orgId, setOrgId] = useState<number | null>(null);
  const [cfg, setCfg] = useState<OrgEmailConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [fb, setFb] = useState<{ t: "s" | "e"; m: string } | null>(null);
  const [logoV, setLogoV] = useState(0); // cache-buster do preview do logo
  const [trocandoFonte, setTrocandoFonte] = useState(false);

  // Form
  const [emailFrom, setEmailFrom] = useState("");
  const [emailFromName, setEmailFromName] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState(587);
  const [user, setUser] = useState("");
  const [pw, setPw] = useState("");
  const [tls, setTls] = useState(true);
  const [assinatura, setAssinatura] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const os = await listarOrganizacoesAdmin();
        setOrgs(os);
        if (os[0]) setOrgId(os[0].id);
      } catch (err) {
        setFb({ t: "e", m: err instanceof ApiError ? err.message : "Erro ao carregar empresas." });
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const orgAtual = orgs.find(o => o.id === orgId) ?? null;
  const fonteAtual = orgAtual?.escopo_base ?? "receita";
  const [limiteDiario, setLimiteDiario] = useState("");
  const [salvandoLimite, setSalvandoLimite] = useState(false);

  // O campo segue a empresa selecionada. Vazio = sem teto proprio.
  useEffect(() => {
    setLimiteDiario(
      orgAtual?.email_limite_diario != null ? String(orgAtual.email_limite_diario) : "",
    );
  }, [orgAtual?.id, orgAtual?.email_limite_diario]);

  async function salvarLimiteDiario() {
    if (orgId == null) return;
    const bruto = limiteDiario.trim();
    const valor = bruto === "" ? null : Number(bruto);
    if (valor != null && (!Number.isInteger(valor) || valor < 0)) {
      setFb({ t: "e", m: "O teto diário tem que ser um número inteiro (ou vazio)." });
      return;
    }
    setFb(null);
    setSalvandoLimite(true);
    try {
      await definirLimiteDiarioOrg(orgId, valor);
      setOrgs(prev => prev.map(o => (o.id === orgId ? { ...o, email_limite_diario: valor } : o)));
      setFb({
        t: "s",
        m: valor == null
          ? `${orgAtual?.nome ?? "A empresa"} volta a seguir só o teto da conta.`
          : `${orgAtual?.nome ?? "A empresa"} agora manda no máximo ${valor} e-mails por dia.`,
      });
    } catch (err) {
      setFb({ t: "e", m: err instanceof ApiError ? err.message : "Não consegui salvar o teto." });
    } finally {
      setSalvandoLimite(false);
    }
  }

  async function trocarFonte(novo: "receita" | "carteira") {
    if (orgId == null || novo === fonteAtual) return;
    const alvo = orgAtual?.nome ?? "esta empresa";
    const aviso = novo === "carteira"
      ? `${alvo} passa a prospectar SO' sobre a carteira propria. Enquanto a lista estiver vazia, a tela de Empresas aparece zerada ate' alguem importar a planilha. Confirma?`
      : `${alvo} volta a prospectar sobre a base da Receita Federal. A carteira nao e' apagada, so' deixa de ser a fonte. Confirma?`;
    if (!window.confirm(aviso)) return;
    setFb(null);
    setTrocandoFonte(true);
    try {
      await definirEscopoBaseOrg(orgId, novo);
      setOrgs(prev => prev.map(o => (o.id === orgId ? { ...o, escopo_base: novo } : o)));
      setFb({ t: "s", m: `Fonte de ${alvo} agora e' ${novo === "carteira" ? "a carteira propria" : "a base da Receita Federal"}.` });
    } catch (err) {
      setFb({ t: "e", m: err instanceof ApiError ? err.message : "Nao consegui trocar a fonte." });
    } finally {
      setTrocandoFonte(false);
    }
  }

  useEffect(() => {
    if (orgId == null) return;
    (async () => {
      setFb(null);
      try {
        const c = await getOrgEmailConfig(orgId);
        setCfg(c);
        setEmailFrom(c.email_from || "");
        setEmailFromName(c.email_from_name || "");
        setHost(c.smtp_host || "");
        setPort(c.smtp_port || 587);
        setUser(c.smtp_username || "");
        setPw("");
        setTls(c.smtp_use_tls ?? true);
        setAssinatura(c.assinatura_html || "");
        setLogoV(v => v + 1);
      } catch (err) {
        setFb({ t: "e", m: err instanceof ApiError ? err.message : "Erro ao carregar config." });
      }
    })();
  }, [orgId]);

  const salvar = async () => {
    if (orgId == null) return;
    setFb(null);
    setSalvando(true);
    try {
      const c = await setOrgEmailConfig(orgId, {
        email_from: emailFrom, email_from_name: emailFromName,
        smtp_host: host, smtp_port: port, smtp_username: user,
        smtp_use_tls: tls, assinatura_html: assinatura,
        ...(pw ? { smtp_password: pw } : {}),
      });
      setCfg(c);
      setPw("");
      setFb({ t: "s", m: "Configuração da empresa salva." });
    } catch (err) {
      setFb({ t: "e", m: err instanceof ApiError ? err.message : "Erro ao salvar." });
    } finally {
      setSalvando(false);
    }
  };

  const enviarLogo = async (file: File | null) => {
    if (!file || orgId == null) return;
    setFb(null);
    try {
      await uploadOrgLogo(orgId, file);
      setLogoV(v => v + 1);
      setCfg(c => c ? { ...c, tem_logo: true } : c);
      setFb({ t: "s", m: "Logo atualizado." });
    } catch (err) {
      setFb({ t: "e", m: err instanceof ApiError ? err.message : "Erro ao enviar logo." });
    }
  };

  if (loading) return <div className="p-8 text-slate-500">Carregando...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium text-slate-600">Empresa:</span>
        <select value={orgId ?? ""} onChange={e => setOrgId(Number(e.target.value))} className="border rounded px-3 py-2 text-sm font-semibold">
          {orgs.map(o => <option key={o.id} value={o.id}>{o.nome}</option>)}
        </select>
        {cfg && <span className={`text-xs px-2 py-1 rounded ${cfg.configurado ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>{cfg.configurado ? "Remetente configurado" : "Sem remetente — não envia"}</span>}
      </div>

      <div className="rounded-xl bg-white border p-5 space-y-3">
        <h3 className="font-semibold">Fonte de prospecção</h3>
        <p className="text-sm text-slate-500">
          De onde esta empresa tira as empresas que aparecem na tela de Empresas.
          As telas são as mesmas — o que muda é a origem dos dados.
        </p>
        <div className="flex flex-wrap gap-2">
          {(["receita", "carteira"] as const).map(op => (
            <button
              key={op}
              onClick={() => trocarFonte(op)}
              disabled={trocandoFonte || orgId == null}
              className={`rounded-lg border-2 px-4 py-2 text-sm font-medium disabled:opacity-40 ${
                fonteAtual === op ? "border-indigo-500 bg-indigo-50 text-indigo-700" : "border-slate-200 text-slate-600 hover:border-slate-300"
              }`}
            >
              {op === "receita" ? "Base da Receita Federal" : "Carteira própria"}
              {fonteAtual === op && " ✓"}
            </button>
          ))}
        </div>
        <p className="text-xs text-slate-400">
          Trocar a fonte muda o que a empresa inteira enxerga, então só o administrador geral pode fazer isso.
        </p>
      </div>

      <div className="rounded-xl bg-white border p-5 space-y-3">
        <h3 className="font-semibold">Teto diário de e-mail desta empresa</h3>
        <p className="text-sm text-slate-500">
          Máximo de e-mails que <strong>esta</strong> empresa manda por dia. Deixe
          vazio para ela seguir apenas o teto da conta.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="number"
            min={0}
            step={1}
            inputMode="numeric"
            value={limiteDiario}
            onChange={e => setLimiteDiario(e.target.value)}
            placeholder="sem teto próprio"
            aria-label="Teto diário de e-mail desta empresa"
            className="w-44 rounded-lg border border-slate-300 px-3 py-2 text-sm tabular-nums outline-none focus:border-emerald-500"
          />
          <span className="text-sm text-slate-500">e-mails/dia</span>
          <button
            onClick={salvarLimiteDiario}
            disabled={salvandoLimite || orgId == null}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-40"
          >
            {salvandoLimite ? "Salvando..." : "Salvar teto"}
          </button>
        </div>
        <p className="text-xs text-slate-400">
          O teto da conta continua valendo por cima: sai sempre o <strong>menor</strong> dos
          dois. É o que permite um cliente novo fazer warm-up a 20/dia sem frear
          os outros — antes, baixar o limite geral limitava todas as empresas juntas.
        </p>
      </div>

      <div className="rounded-xl bg-white border p-5 space-y-3">
        <h3 className="font-semibold">Remetente</h3>
        <div className="grid grid-cols-2 gap-3">
          <input placeholder="Nome do remetente (ex: Alfa Consultoria)" value={emailFromName} onChange={e => setEmailFromName(e.target.value)} className="border rounded px-3 py-2" />
          <input type="email" placeholder="E-mail do remetente" value={emailFrom} onChange={e => setEmailFrom(e.target.value)} className="border rounded px-3 py-2" />
        </div>
        {orgId != null && (
          <ConexaoGmail alvo="empresa" orgId={orgId} conta={cfg?.gmail_conta} conectado={Boolean(cfg?.gmail_conectado)}
            onMudou={() => getOrgEmailConfig(orgId).then(setCfg).catch(() => undefined)} />
        )}
      </div>

      <div className="rounded-xl bg-white border p-5 space-y-3">
        <h3 className="font-semibold">Servidor SMTP</h3>
        <div className="grid grid-cols-2 gap-3">
          <input placeholder="Host (ex: smtp.gmail.com)" value={host} onChange={e => setHost(e.target.value)} className="border rounded px-3 py-2" />
          <input type="number" placeholder="Porta" value={port} onChange={e => setPort(Number(e.target.value))} className="border rounded px-3 py-2" />
          <input placeholder="Usuário SMTP" value={user} onChange={e => setUser(e.target.value)} className="border rounded px-3 py-2" />
          <input type="password" placeholder="Senha (deixe em branco p/ manter)" value={pw} onChange={e => setPw(e.target.value)} className="border rounded px-3 py-2" />
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={tls} onChange={e => setTls(e.target.checked)} /> Usar TLS</label>
      </div>

      <div className="rounded-xl bg-white border p-5 space-y-3">
        <h3 className="font-semibold">Assinatura de e-mail</h3>
        <p className="text-xs text-slate-500">HTML livre. Use <code>{"{{logo}}"}</code> onde quiser o logo da empresa. Ex: <code>{'<img src="{{logo}}" height="48"> Alfa Consultoria — (51) 9999-9999'}</code></p>
        <textarea value={assinatura} onChange={e => setAssinatura(e.target.value)} rows={5} className="w-full border rounded px-3 py-2 font-mono text-sm" placeholder="<img src='{{logo}}' height='48'><br>Sua assinatura aqui" />
      </div>

      <div className="rounded-xl bg-white border p-5 space-y-3">
        <h3 className="font-semibold">Logo</h3>
        <div className="flex items-center gap-4">
          {orgId != null && cfg?.tem_logo && (
            <img src={`${API_BASE}/api/v1/organizacoes/${orgId}/logo?v=${logoV}`} alt="Logo" className="h-14 border rounded bg-slate-50 p-1" />
          )}
          <input type="file" accept="image/*" onChange={e => enviarLogo(e.target.files?.[0] ?? null)} className="text-sm" />
        </div>
      </div>

      {fb && <div className={`p-3 rounded text-sm ${fb.t === "s" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>{fb.m}</div>}
      <button onClick={salvar} disabled={salvando} className="bg-indigo-600 text-white px-4 py-2 rounded disabled:opacity-50">{salvando ? "Salvando..." : "Salvar configuração"}</button>
    </div>
  );
}

function RegraItem({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <div className="border-b border-slate-100 pb-4 last:border-0">
      <h3 className="font-semibold text-slate-800 mb-1">{titulo}</h3>
      <div className="text-sm text-slate-600 leading-relaxed space-y-1">{children}</div>
    </div>
  );
}

function RegrasNegocioTab() {
  return (
    <div className="space-y-6">
      <div className="rounded-lg bg-indigo-50 border border-indigo-200 p-4 text-sm text-indigo-800">
        Isto documenta regras que já estão implementadas no sistema — não são sugestões, são o que o código realmente faz hoje.
      </div>

      <RegraItem titulo="📜 LGPD — descadastro de e-mail (opt-out)">
        <p>Toda campanha de e-mail, de qualquer empresa (Alfa ou Beta), inclui automaticamente um link de descadastro no rodapé — quem escreve o template não precisa lembrar de incluir isso, o sistema injeta sozinho na hora de enviar.</p>
        <p>Quem clica é descadastrado <strong>globalmente</strong>: para de receber e-mail de qualquer empresa do sistema, não só da que mandou. O sistema também pula automaticamente quem já pediu descadastro antes de enviar qualquer campanha nova.</p>
      </RegraItem>

      <RegraItem titulo="🏆 Score de potencial das empresas">
        <p>Removido em 2026-09: o score (0-100) nunca foi calibrado ao perfil de cliente ideal e quase toda a base caía em "médio". A tabela <strong>empresas_potencial</strong> (209 MB) foi eliminada do banco; filtros, ordenação e selo de potencial saíram das telas.</p>
      </RegraItem>

      <RegraItem titulo="👁️ Hierarquia de acesso">
        <p><strong>Operador Global</strong> — acesso total, todas as empresas. <strong>Admin</strong> — acesso total, só na empresa dele. <strong>Membro</strong> — acesso normal de trabalho. <strong>Visitante</strong> — só vê a tela de Empresas, com CNPJ parcial, sem e-mail/telefone, e valores financeiros em faixa (não exato); sem acesso a CRM, Campanhas, WhatsApp ou Configurações.</p>
        <p>Pensado pra dar acesso a alguém de fora (ex.: um recrutador avaliando o produto) sem expor dado real de cliente.</p>
      </RegraItem>

      <RegraItem titulo="📧 Envio em lotes diários">
        <p>O envio sai em rodadas pequenas, no ritmo de uma pessoa trabalhando, em vez de tudo de uma vez. Existe pra respeitar o limite diário do provedor de e-mail (300/dia é o padrão configurado em EMAIL_LIMITE_DIARIO).</p>
        <p>Um workflow automático (GitHub Actions, uma vez por dia) avança sozinho as campanhas que já foram iniciadas — não mexe em campanhas ainda em rascunho.</p>
      </RegraItem>

      <RegraItem titulo="✉️ Credibilidade do e-mail — pendências">
        <p>Recomendado (ainda não configurado): autenticar DKIM e SPF para o domínio próprio na conta Google que envia — reduz chance de cair em spam e passa mais confiança pro destinatário.</p>
        <p><strong>Sem detecção de bounce.</strong> Hoje ninguém registra e-mail devolvido: a abertura e o clique vêm do rastreamento próprio (pixel e redirect), que não enxerga devolução. Continuar disparando para endereço morto é o caminho mais rápido de queimar o domínio.</p>
      </RegraItem>
    </div>
  );
}


/**
 * E-mail individual: o disparo sai do endereço e da assinatura de quem
 * está logado, usando o servidor da empresa. Campo em branco continua
 * herdando o padrão da empresa.
 */
/** Conecta (ou desconecta) a conta do Gmail que faz o envio.
 *
 *  A autorizacao e' por empresa, e nao uma conta unica para todas, porque o
 *  Gmail so' respeita remetente que pertenca a' conta conectada. */
function ConexaoGmail({ alvo, orgId, conta, conectado, onMudou }: {
  alvo: AlvoGmail; orgId?: number | null; conta?: string | null; conectado: boolean; onMudou: () => void;
}) {
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");

  async function conectar() {
    setOcupado(true);
    setErro("");
    try {
      const { url } = await iniciarConexaoGmail(alvo, orgId);
      window.location.href = url;
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Não consegui abrir a tela do Google.");
      setOcupado(false);
    }
  }

  async function desconectar() {
    if (!confirm("Desconectar esta conta do Gmail? Os envios deixam de sair por ela.")) return;
    setOcupado(true);
    setErro("");
    try {
      await desconectarGmail(alvo, orgId);
      onMudou();
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Não consegui desconectar.");
    } finally {
      setOcupado(false);
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm">
          <p className="font-medium text-slate-700">Conta do Gmail que envia</p>
          {conectado ? (
            <p className="text-xs text-green-700 mt-0.5">Conectada: {conta || "conta Google"}</p>
          ) : (
            <p className="text-xs text-slate-500 mt-0.5">
              {alvo === "eu"
                ? "Nenhuma conta sua conectada. Os envios usam a conta da empresa."
                : "Nenhuma conta conectada para esta empresa."}
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={conectar} disabled={ocupado}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
            {conectado ? "Trocar conta" : "Conectar Gmail"}
          </button>
          {conectado && (
            <button type="button" onClick={desconectar} disabled={ocupado}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-white disabled:opacity-50">
              Desconectar
            </button>
          )}
        </div>
      </div>
      <p className="text-[11px] text-slate-400 mt-2">
        O endereço do remetente precisa ser o desta conta, ou um endereço cadastrado nela em
        &quot;Enviar e-mail como&quot;. Fora disso o Gmail troca o remetente pelo da conta.
      </p>
      {erro && <p className="text-xs text-red-600 mt-2">{erro}</p>}
    </div>
  );
}

function MeuEmailTab() {
  const [cfg, setCfg] = useState<MeuEmail | null>(null);
  const [form, setForm] = useState({ email_from: "", email_from_name: "", assinatura_html: "" });
  const [smtp, setSmtp] = useState({ host: "", port: 587, username: "", use_tls: true });
  const [smtpPass, setSmtpPass] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [fb, setFb] = useState<{ t: "s" | "e"; m: string } | null>(null);

  useEffect(() => {
    getMeuEmail()
      .then(c => {
        setCfg(c);
        setForm({
          email_from: c.email_from || "",
          email_from_name: c.email_from_name || "",
          assinatura_html: c.assinatura_html || "",
        });
        setSmtp({
          host: c.smtp_host || "",
          port: c.smtp_port || 587,
          username: c.smtp_username || "",
          use_tls: c.smtp_use_tls ?? true,
        });
      })
      .catch(() => setFb({ t: "e", m: "Não consegui carregar sua configuração de e-mail." }));
  }, []);

  async function salvar(e: React.FormEvent) {
    e.preventDefault();
    const proprio = Boolean(smtp.host.trim());
    if (proprio && !smtp.username.trim()) {
      setFb({ t: "e", m: "Informe o usuário do servidor." });
      return;
    }
    if (proprio && !cfg?.tem_servidor_proprio && !smtpPass) {
      setFb({ t: "e", m: "Informe a senha do servidor." });
      return;
    }
    setSalvando(true);
    setFb(null);
    try {
      setCfg(await salvarMeuEmail({
        ...form,
        ...(proprio ? {
          smtp_host: smtp.host.trim(),
          smtp_port: Number(smtp.port) || 587,
          smtp_username: smtp.username.trim(),
          smtp_use_tls: smtp.use_tls,
          ...(smtpPass ? { smtp_password: smtpPass } : {}),
        } : {}),
      }));
      setSmtpPass("");
      setFb({ t: "s", m: "Salvo. Seus próximos envios saem por esta configuração." });
    } catch (err) {
      setFb({ t: "e", m: err instanceof Error ? err.message : "Erro ao salvar" });
    } finally {
      setSalvando(false);
    }
  }

  if (!cfg) return <p className="text-sm text-slate-400">Carregando...</p>;

  const padrao = cfg.padrao_da_empresa;

  return (
    <form onSubmit={salvar} className="space-y-4">
      <div className="rounded-xl bg-white border border-slate-200 p-5 space-y-4 shadow-sm">
        <div>
          <h2 className="font-semibold text-slate-800">Meu e-mail</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Campanhas e avisos que você dispara saem deste endereço, pelo servidor da empresa.
            Em branco, usa o padrão da empresa.
          </p>
        </div>

        <ConexaoGmail alvo="eu" conta={cfg.gmail_conta} conectado={cfg.gmail_conectado}
          onMudou={() => getMeuEmail().then(setCfg).catch(() => undefined)} />

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Endereço do remetente</label>
            <input
              type="email"
              value={form.email_from}
              onChange={e => setForm({ ...form, email_from: e.target.value })}
              placeholder={padrao.email_from || "voce@empresa.com.br"}
              autoComplete="off"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
            />
            {!form.email_from && padrao.email_from && (
              <p className="text-[11px] text-slate-400 mt-1">Herdando da empresa: {padrao.email_from}</p>
            )}
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Nome que aparece</label>
            <input
              type="text"
              value={form.email_from_name}
              onChange={e => setForm({ ...form, email_from_name: e.target.value })}
              placeholder={padrao.email_from_name || "Seu Nome | Empresa"}
              autoComplete="off"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">
            Minha assinatura (HTML) — <span className="font-normal text-slate-400">{"{{logo}}"} vira o logo da empresa</span>
          </label>
          <textarea
            value={form.assinatura_html}
            onChange={e => setForm({ ...form, assinatura_html: e.target.value })}
            rows={5}
            placeholder="<p>Seu Nome<br>Cargo · Empresa</p>"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono outline-none focus:border-indigo-500"
          />
        </div>

        <div className="border-t border-slate-200 pt-4 space-y-3">
          <div>
            <h3 className="font-semibold text-slate-800 text-sm">Meu servidor de envio</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Opcional. Em branco, usa o servidor da empresa
              {padrao.smtp_host ? ` (${padrao.smtp_host})` : ""}. Preencha para enviar pelo
              seu próprio — ex.: Gmail em <code>smtp.gmail.com</code> porta 587, com senha de app.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div className="md:col-span-2">
              <label className="block text-xs font-medium text-slate-600 mb-1">Servidor (host)</label>
              <input
                type="text" value={smtp.host}
                onChange={e => setSmtp({ ...smtp, host: e.target.value })}
                placeholder={padrao.smtp_host || "smtp.gmail.com"}
                autoComplete="off"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Porta</label>
              <input
                type="number" value={smtp.port}
                onChange={e => setSmtp({ ...smtp, port: Number(e.target.value) })}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
            </div>
            <label className="flex items-end gap-2 pb-2 text-sm text-slate-600">
              <input
                type="checkbox" checked={smtp.use_tls}
                onChange={e => setSmtp({ ...smtp, use_tls: e.target.checked })}
              />
              Usar TLS
            </label>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Usuário</label>
              <input
                type="text" value={smtp.username}
                onChange={e => setSmtp({ ...smtp, username: e.target.value })}
                placeholder="voce@empresa.com.br"
                autoComplete="off"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                Senha {cfg.tem_servidor_proprio && (
                  <span className="font-normal text-slate-400">— em branco mantém a atual</span>
                )}
              </label>
              <input
                type="password" value={smtpPass}
                onChange={e => setSmtpPass(e.target.value)}
                placeholder={cfg.tem_servidor_proprio ? "••••••••" : "senha de app (16 caracteres)"}
                autoComplete="new-password"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
            </div>
          </div>
        </div>

        {!padrao.configurado && !smtp.host && (
          <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
            Nem a empresa nem você têm servidor de e-mail configurado, então nada é enviado de
            verdade — os disparos ficam como simulados.
          </div>
        )}

        {fb && (
          <div className={`rounded-lg px-3 py-2 text-sm ${fb.t === "s" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
            {fb.m}
          </div>
        )}

        <button
          type="submit"
          disabled={salvando}
          className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-lg px-5 py-2 text-sm font-medium"
        >
          {salvando ? "Salvando..." : "Salvar meu e-mail"}
        </button>
      </div>
    </form>
  );
}

type Aba = "perfil" | "meu-email" | "regras" | "lgpd" | "usuarios" | "empresas" | "email" | "sobre";

export default function ConfiguracoesPage() {
  const { isAdmin } = useAuth();
  const [aba, setAba] = useState<Aba>("perfil");
  const [retornoGmail, setRetornoGmail] = useState<{ ok: boolean; m: string } | null>(null);

  // Volta da tela de autorizacao do Google: abre a aba de onde a pessoa saiu
  // e diz o que aconteceu. A URL e' limpa pra um F5 nao repetir o aviso.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const resultado = q.get("gmail");
    if (!resultado) return;
    const detalhe = q.get("detalhe") || "";
    setAba(q.get("aba") === "empresas" ? "empresas" : "meu-email");
    setRetornoGmail(resultado === "ok"
      ? { ok: true, m: `Gmail conectado${detalhe ? `: ${detalhe}` : ""}. Os próximos envios saem por esta conta.` }
      : { ok: false, m: detalhe || "Não foi possível conectar o Gmail." });
    window.history.replaceState(null, "", window.location.pathname);
  }, []);

  const abas: { id: Aba; label: string; icone: string; somenteAdmin?: boolean }[] = [
    { id: "perfil", label: "Perfil", icone: "👤" },
    { id: "meu-email", label: "Meu e-mail", icone: "✉️" },
    { id: "regras", label: "Regras do CRM/Monitor", icone: "🎯" },
    { id: "lgpd", label: "Regras & LGPD", icone: "📜" },
    { id: "usuarios", label: "Usuários", icone: "👥", somenteAdmin: true },
    { id: "empresas", label: "Empresas", icone: "🏢", somenteAdmin: true },
    { id: "email", label: "Email (global)", icone: "✉️", somenteAdmin: true },
    { id: "sobre", label: "Sobre", icone: "ℹ️" },
  ];

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-800">Configurações</h1>
        <p className="text-sm text-slate-500">Sua conta, regras do sistema, usuários e status dos dados.</p>
      </div>

      {retornoGmail && (
        <div className={`mb-4 rounded-lg border px-4 py-3 text-sm ${retornoGmail.ok ? "border-green-200 bg-green-50 text-green-800" : "border-red-200 bg-red-50 text-red-700"}`}>
          {retornoGmail.m}
        </div>
      )}

      <div className="mb-6 flex gap-1 border-b border-slate-200 overflow-x-auto">
        {abas.filter(a => !a.somenteAdmin || isAdmin).map(a => (
          <button
            key={a.id}
            onClick={() => setAba(a.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
              aba === a.id ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-500 hover:text-slate-700"
            }`}
          >
            {a.icone} {a.label}
          </button>
        ))}
      </div>

      {aba === "perfil" && <PerfilTab />}
      {aba === "meu-email" && <MeuEmailTab />}
      {aba === "regras" && <RegrasTab />}
      {aba === "lgpd" && <RegrasNegocioTab />}
      {aba === "usuarios" && isAdmin && <UsuariosTab />}
      {aba === "empresas" && isAdmin && <EmpresasTab />}
      {aba === "email" && isAdmin && <EmailTab />}
      {aba === "sobre" && <SobreTab />}
    </div>
  );
}
