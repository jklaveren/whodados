const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

export function setToken(token: string): void {
  localStorage.setItem("token", token);
}

export function removeToken(): void {
  localStorage.removeItem("token");
}

// Empresa (organizacao) ativa -- enviada no header X-Org-Id em toda chamada, e' o
// que isola CRM/campanhas/templates/monitor por empresa (Alfa / Beta).
export function getActiveOrgId(): number | null {
  if (typeof window === "undefined") return null;
  const v = localStorage.getItem("org_id");
  return v ? Number(v) : null;
}

export function setActiveOrgId(id: number): void {
  localStorage.setItem("org_id", String(id));
}

export function clearActiveOrgId(): void {
  localStorage.removeItem("org_id");
}

/**
 * Rotas que legitimamente nao tem empresa: o login e a propria listagem de
 * empresas (que e' o que DEFINE a empresa ativa). Todo o resto e' dado de
 * uma empresa e nao pode sair daqui sem dizer qual.
 */
const ROTAS_SEM_EMPRESA = ["/api/v1/auth/", "/api/v1/organizacoes", "/api/v1/descadastro"];

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string> || {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const orgId = getActiveOrgId();
  if (orgId) headers["X-Org-Id"] = String(orgId);
  else if (token && !ROTAS_SEM_EMPRESA.some(r => path.startsWith(r))) {
    // Sem isto, a requisicao ia sem X-Org-Id e o backend caia na primeira
    // empresa do usuario -- uma tarefa criada "na Beta" nascia na Alfa.
    throw new ApiError(400, "Empresa ativa ainda não carregou. Recarregue a página.");
  }
  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: "Erro desconhecido" }));
    if (res.status === 401 && typeof window !== "undefined") {
      removeToken();
      if (window.location.pathname !== "/login") {
        window.location.href = "/login?expirado=1";
      }
    }
    throw new ApiError(res.status, body.detail || "Erro na API");
  }
  return res.json();
}

// Auth
export async function login(username: string, password: string, rememberMe = false) {
  const form = new URLSearchParams();
  form.append("username", username);
  form.append("password", password);
  form.append("remember_me", rememberMe ? "true" : "false");
  const res = await fetch(`${API_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: "Erro de login" }));
    throw new ApiError(res.status, body.detail || "Credenciais invalidas");
  }
  return res.json();
}

export interface MeInfo {
  username: string;
  is_admin: boolean;
  email: string | null;
}

export async function getMe(): Promise<MeInfo> {
  return request("/api/v1/auth/me");
}

// ==================== ORGANIZACOES (MULTI-EMPRESA) ====================

export interface Organizacao {
  id: number;
  nome: string;
  slug: string;
  ativo: boolean;
  papel?: "admin" | "membro" | "visitante";
  /** De onde vem a base de prospecção: "receita" (base pública) ou "carteira" (lista própria). */
  /** A) De onde vem a base de pesquisa. Não diz se há lista de trabalho. */
  escopo_base?: "receita" | "carteira";
  /** B) Tem lista de trabalho (Carteira/Disparar). Independente de escopo_base. */
  tem_carteira?: boolean;
  /** Teto diário de e-mail desta empresa. null = só o teto da conta vale. */
  email_limite_diario?: number | null;
}

/** Empresas que o usuario logado pode operar (para o seletor de empresa ativa). */
export async function listarOrganizacoes(): Promise<Organizacao[]> {
  return request("/api/v1/organizacoes");
}

// Password Reset
export async function forgotPassword(identifier: string) {
  return request("/api/v1/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ username: identifier }),
  });
}

export async function validateResetToken(token: string) {
  return request(`/api/v1/auth/validate-reset-token/${token}`);
}

export async function resetPassword(token: string, novaSenha: string) {
  return request("/api/v1/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, nova_senha: novaSenha }),
  });
}

// Empresas
export type PotencialTier = "alto" | "medio" | "baixo";

export interface EmpresaItem {
  cnpj_completo: string;
  razao_social: string;
  nome_fantasia: string | null;
  municipio: string | null;
  cnae_principal: string | null;
  cnae_descricao?: string | null;
  capital_social: number;
  divida_total: number;
  porte_nome: string | null;
  data_fundacao?: string | null;
  potencial_score: number;
  potencial_tier: PotencialTier;
}

/** Filtros do funil de empresas (aplicados no servidor). */
export interface EmpresaFiltros {
  cidade?: string[];
  cnae?: string[];
  porte?: string[];
  busca?: string;
  divida_min?: number;
  divida_max?: number;
  capital_min?: number;
  capital_max?: number;
  fundacao_de?: string;   // YYYY-MM-DD
  fundacao_ate?: string;  // YYYY-MM-DD
  incluir_inativas?: boolean;
  potencial?: PotencialTier[];
  ordenar_por?: "razao_social" | "potencial";
}

function empresaFiltrosToQuery(f: EmpresaFiltros = {}): URLSearchParams {
  const p = new URLSearchParams();
  (f.cidade ?? []).forEach(v => p.append("cidade", v));
  (f.cnae ?? []).forEach(v => p.append("cnae", v));
  (f.porte ?? []).forEach(v => p.append("porte", v));
  if (f.busca) p.append("busca", f.busca);
  if (f.divida_min != null) p.append("divida_min", String(f.divida_min));
  if (f.divida_max != null) p.append("divida_max", String(f.divida_max));
  if (f.capital_min != null) p.append("capital_min", String(f.capital_min));
  if (f.capital_max != null) p.append("capital_max", String(f.capital_max));
  if (f.fundacao_de) p.append("fundacao_de", f.fundacao_de);
  if (f.fundacao_ate) p.append("fundacao_ate", f.fundacao_ate);
  if (f.incluir_inativas === false) p.append("incluir_inativas", "false");
  // potencial removido (tabela empresas_potencial dropada em 2026-09);
  // o campo segue no tipo pra nao quebrar filtros salvos antigos.
  if (f.ordenar_por && f.ordenar_por !== "potencial") p.append("ordenar_por", f.ordenar_por);
  return p;
}

/** Uma pagina de empresas para o filtro atual (funil server-side). */
export async function listarEmpresas(filtros: EmpresaFiltros = {}, limit = 100, offset = 0): Promise<EmpresaItem[]> {
  const p = empresaFiltrosToQuery(filtros);
  p.append("limit", String(limit));
  p.append("offset", String(offset));
  return request(`/api/v1/empresas?${p}`);
}

/** Total de empresas que batem no filtro atual (contador do funil). */
// Filtro fixado no banco (ponto de retorno). Um slot por usuario/empresa:
// gravar sobrescreve o anterior. Diferente do cache local do navegador, que
// guarda a ultima busca e e' sobrescrito a cada mexida num filtro.
// O que vai gravado e' o estado dos CAMPOS do painel (texto cru que a
// pessoa digitou), nao o EmpresaFiltros ja' convertido -- so' assim o
// formulario volta exatamente como estava. Quem define o formato e' a tela;
// aqui trafega solto de proposito.
export type FiltrosPainel = Record<string, unknown>;

export interface FiltroSalvoResposta {
  filtros: FiltrosPainel | null;
  atualizado_em: string | null;
}

export async function getFiltroSalvo(): Promise<FiltroSalvoResposta> {
  return request("/api/v1/empresas/filtro-salvo");
}

export async function salvarFiltroSalvo(filtros: FiltrosPainel): Promise<FiltroSalvoResposta> {
  return request("/api/v1/empresas/filtro-salvo", {
    method: "PUT",
    body: JSON.stringify({ filtros }),
  });
}

export async function apagarFiltroSalvo(): Promise<{ removido: boolean }> {
  return request("/api/v1/empresas/filtro-salvo", { method: "DELETE" });
}

export async function contarEmpresas(filtros: EmpresaFiltros = {}): Promise<{ total: number }> {
  return request(`/api/v1/empresas/count?${empresaFiltrosToQuery(filtros)}`);
}

export interface Socio {
  nome_socio: string;
  cpf_cnpj_socio: string | null;
  qualif_socio: string | null;
}

export interface CRMRecord {
  id: number;
  cnpj: string;
  status: string | null;
  notas: string | null;
}

/** Um e-mail que o lead ja' recebeu: qual modelo, qual toque e o que aconteceu. */
export interface Abordagem {
  modelo: string | null;
  assunto: string | null;
  enviado_em: string | null;
  aberto_em: string | null;
  clicado_em: string | null;
  followup: boolean;
}

export interface EmpresaDetalhe extends EmpresaItem {
  abordagens?: Abordagem[];
  situacao_contato?: string | null;
  data_fundacao: string | null;
  contato_fone: string | null;
  email: string | null;
  socios: Socio[];
  crm: CRMRecord | null;
}

/** Envia um e-mail avulso para uma empresa (fora de campanha). Passa pela
 *  mesma montagem das campanhas: assinatura, descadastro e rastreamento. */
export async function enviarEmailParaEmpresa(
  cnpj: string, templateId: number, email?: string,
): Promise<{ ok: boolean; para: string; assunto: string; simulado?: boolean }> {
  return request(`/api/v1/empresas/${encodeURIComponent(cnpj)}/enviar-email`, {
    method: "POST",
    body: JSON.stringify({ template_id: templateId, ...(email ? { email } : {}) }),
  });
}

export async function getEmpresaDetalhe(cnpj: string): Promise<EmpresaDetalhe> {
  return request(`/api/v1/empresas/${encodeURIComponent(cnpj)}`);
}

export async function atualizarCrm(cnpj: string, data: { status?: string; notas?: string; classificacao?: string; motivo?: string; parceiro?: boolean }) {
  return request(`/api/v1/crm/${encodeURIComponent(cnpj)}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

// ==================== CRM (KANBAN) ====================

export type CrmStatus = "novo" | "em_contato" | "negociando" | "convertido" | "descartado";
export type CrmClassificacao = "perfil_ideal" | "perfil_possivel" | "fora_perfil" | "parceiro" | "";

export interface CrmKanbanRecord {
  id: number;
  cnpj: string;
  status: CrmStatus;
  notas: string | null;
  criado_por?: string | null;
  data_atualizacao?: string | null;
  classificacao?: string | null;
  motivo?: string | null;
  parceiro?: boolean;
  atividades_pendentes?: number;
}

export type CrmKanban = Record<CrmStatus, CrmKanbanRecord[]>;

export async function listarCrmKanban(): Promise<CrmKanban> {
  return request("/api/v1/crm");
}

// ==================== CRM: ATIVIDADES/TAREFAS ====================

export interface UsuarioOrg {
  id: number;
  username: string;
}

export type StatusAtividade = "pendente" | "em_andamento" | "concluida";

export interface PreviewEmail {
  assunto: string;
  corpo_html: string;
  corpo_texto: string;
  template_usado: string;
  categoria_cnae: string;
  variaveis: Record<string, string>;
  destinatario: string;
  empresa: string;
  cnpj: string;
}

/**
 * E-mail montado exatamente como vai ser enviado (variaveis substituidas,
 * assinatura e rodape de descadastro incluidos). Sem cnpj, o backend usa uma
 * empresa da base como amostra.
 */
export async function previewTemplate(templateId: number, cnpj?: string): Promise<PreviewEmail> {
  return request(`/api/v1/templates/${templateId}/preview`, {
    method: "POST",
    body: JSON.stringify({ cnpj: cnpj || "" }),
  });
}

/** Só o número de não lidas, para o badge do menu. */
export async function contarNotificacoesNaoLidas(): Promise<{ total: number }> {
  return request("/api/v1/notificacoes/nao-lidas");
}

// ==================== E-MAIL INDIVIDUAL ====================

export interface MeuEmail {
  email_from: string | null;
  email_from_name: string | null;
  assinatura_html: string | null;
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_username: string | null;
  smtp_use_tls: boolean | null;
  tem_servidor_proprio: boolean;
  /** Conta do Gmail que a pessoa conectou nesta empresa, se houver. */
  gmail_conta: string | null;
  gmail_conectado: boolean;
  /** O que a empresa oferece quando você não define o seu. */
  padrao_da_empresa: {
    email_from: string | null;
    email_from_name: string | null;
    smtp_host: string | null;
    configurado: boolean;
  };
}

/** Remetente/assinatura da pessoa logada na empresa ativa. */
export async function getMeuEmail(): Promise<MeuEmail> {
  return request("/api/v1/meu-email");
}

export async function salvarMeuEmail(dados: Partial<{
  email_from: string; email_from_name: string; assinatura_html: string;
  smtp_host: string; smtp_port: number; smtp_username: string;
  smtp_password: string; smtp_use_tls: boolean;
}>): Promise<MeuEmail> {
  return request("/api/v1/meu-email", { method: "PUT", body: JSON.stringify(dados) });
}

// ==================== PROPOSTAS ====================

export interface CampoProposta { chave: string; rotulo: string }

export interface EtapaPlano { etapa: string; entrega?: string; prazo?: string }

export interface ConteudoProposta {
  titulo?: string;
  apresentacao?: string;
  plano?: EtapaPlano[];
  fora_do_escopo?: string[];
  recursos?: string;
  investimento?: string;
  disponibilidade?: string;
  proximo_passo?: string;
  /** Explicação da IA sobre as escolhas — não vai para o cliente. */
  porque?: string;
}

export interface Proposta {
  id: number;
  cliente: string;
  titulo: string | null;
  status: "rascunho" | "enviada" | "aceita" | "recusada";
  criado_por: string | null;
  criado_em: string;
  atualizado_em: string;
  campos?: Record<string, string>;
  conteudo?: ConteudoProposta;
  html?: string;
  texto?: string;
}

export interface IdentidadeEmpresa {
  cor_principal: string;
  cor_texto: string;
  cor_fundo: string;
  fonte: string;
  selo: string;
  tem_logo: boolean;
}

export async function camposDaProposta(): Promise<CampoProposta[]> {
  return request("/api/v1/proposta/campos");
}

export async function identidadeDaEmpresa(): Promise<IdentidadeEmpresa> {
  return request("/api/v1/proposta/identidade");
}

export async function listarPropostas(): Promise<Proposta[]> {
  return request("/api/v1/propostas");
}

export async function abrirProposta(id: number): Promise<Proposta> {
  return request(`/api/v1/propostas/${id}`);
}

/** Pede à IA. Devolve 503 quando o servidor não tem chave configurada. */
export async function gerarProposta(campos: Record<string, string>): Promise<{
  conteudo: ConteudoProposta; html: string; texto: string;
}> {
  return request("/api/v1/proposta/gerar", { method: "POST", body: JSON.stringify(campos) });
}

/** Mostra como fica, sem IA — para quem escreveu a proposta à mão. */
export async function previaProposta(conteudo: ConteudoProposta): Promise<{
  html: string; texto: string;
}> {
  return request("/api/v1/proposta/previa", {
    method: "POST", body: JSON.stringify({ conteudo }),
  });
}

export async function salvarProposta(dados: {
  cliente: string; titulo?: string;
  campos: Record<string, string>; conteudo: ConteudoProposta;
}): Promise<Proposta> {
  return request("/api/v1/propostas", { method: "POST", body: JSON.stringify(dados) });
}

export async function atualizarProposta(id: number, dados: Partial<{
  cliente: string; titulo: string; status: Proposta["status"];
  campos: Record<string, string>; conteudo: ConteudoProposta;
}>): Promise<Proposta> {
  return request(`/api/v1/propostas/${id}`, { method: "PUT", body: JSON.stringify(dados) });
}

export async function removerProposta(id: number) {
  return request(`/api/v1/propostas/${id}`, { method: "DELETE" });
}

// ==================== GASTOS ====================

export interface Gasto {
  id: number;
  organizacao_id: number;
  descricao: string;
  valor: number;
  data: string;
  categoria: string;
  forma_pagamento: string | null;
  observacao: string | null;
  criado_por: string | null;
  criado_em: string;
  /** Preenchido = excluído (fica fora da lista e do total, mas não some). */
  removido_em: string | null;
  removido_por: string | null;
}

export interface ResumoGastos {
  total: number;
  quantidade: number;
  por_categoria: { categoria: string; total: number; quantidade: number }[];
}

export interface NovoGasto {
  descricao: string;
  valor: number;
  data?: string;
  categoria?: string;
  forma_pagamento?: string;
  observacao?: string;
}

export async function listarGastos(params?: {
  de?: string; ate?: string; categoria?: string; incluir_removidos?: boolean;
}): Promise<Gasto[]> {
  const q = new URLSearchParams();
  if (params?.de) q.set("de", params.de);
  if (params?.ate) q.set("ate", params.ate);
  if (params?.categoria) q.set("categoria", params.categoria);
  if (params?.incluir_removidos) q.set("incluir_removidos", "true");
  const qs = q.toString();
  return request(`/api/v1/gastos${qs ? `?${qs}` : ""}`);
}

export async function resumoGastos(de?: string, ate?: string): Promise<ResumoGastos> {
  const q = new URLSearchParams();
  if (de) q.set("de", de);
  if (ate) q.set("ate", ate);
  const qs = q.toString();
  return request(`/api/v1/gastos/resumo${qs ? `?${qs}` : ""}`);
}

export async function listarCategoriasGasto(): Promise<string[]> {
  return request("/api/v1/gastos/categorias");
}

export async function criarGasto(gasto: NovoGasto): Promise<Gasto> {
  return request("/api/v1/gastos", { method: "POST", body: JSON.stringify(gasto) });
}

/** Exclusão lógica: sai da lista e do total, mas o registro fica. */
export async function removerGasto(id: number) {
  return request(`/api/v1/gastos/${id}`, { method: "DELETE" });
}

export async function restaurarGasto(id: number) {
  return request(`/api/v1/gastos/${id}/restaurar`, { method: "POST" });
}

export interface AnexoAtividade {
  id: number;
  atividade_id: number;
  nome: string;
  mime: string | null;
  tamanho: number | null;
  enviado_por: string | null;
  criado_em: string;
}

/** Passa a tarefa pra outra pessoa (notifica quem recebe). null tira o responsável. */
export async function atribuirAtividade(id: number, responsavelUserId: number | null, titulo?: string) {
  return request(`/api/v1/crm/atividades/${id}/responsavel`, {
    method: "POST",
    body: JSON.stringify({ responsavel_user_id: responsavelUserId, titulo }),
  });
}

export async function listarAnexosAtividade(atividadeId: number): Promise<AnexoAtividade[]> {
  return request(`/api/v1/crm/atividades/${atividadeId}/anexos`);
}

export async function anexarArquivoAtividade(atividadeId: number, file: File): Promise<AnexoAtividade> {
  const form = new FormData();
  form.append("arquivo", file);
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const orgId = getActiveOrgId();
  if (orgId) headers["X-Org-Id"] = String(orgId);
  const res = await fetch(`${API_URL}/api/v1/crm/atividades/${atividadeId}/anexos`, {
    method: "POST", headers, body: form,
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({ detail: "Erro" }));
    throw new ApiError(res.status, b.detail || "Erro ao anexar arquivo");
  }
  return res.json();
}

export async function removerAnexoAtividade(anexoId: number) {
  return request(`/api/v1/crm/anexos/${anexoId}`, { method: "DELETE" });
}

/**
 * Baixa o anexo como blob e devolve uma URL local pra abrir ou salvar.
 * Anexo nao e' publico -- so' sai do backend com token, entao nao da' pra
 * apontar um <a href> direto pra API. Quem chamar precisa dar
 * URL.revokeObjectURL depois pra nao segurar o arquivo em memoria.
 */
export async function baixarAnexoAtividade(anexoId: number): Promise<{ url: string; tipo: string }> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const orgId = getActiveOrgId();
  if (orgId) headers["X-Org-Id"] = String(orgId);
  const res = await fetch(`${API_URL}/api/v1/crm/anexos/${anexoId}`, { headers });
  if (!res.ok) throw new ApiError(res.status, "Não consegui abrir o anexo");
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), tipo: blob.type };
}

export interface HistoricoAtividade {
  id: number;
  atividade_id: number;
  /** comentario = escrito pelo usuario; status/prazo = registrado automaticamente. */
  tipo: "comentario" | "status" | "prazo" | "anexo" | "anexo_removido" | "responsavel";
  texto: string | null;
  de: string | null;
  para: string | null;
  autor: string | null;
  criado_em: string;
}

export async function listarHistoricoAtividade(id: number): Promise<HistoricoAtividade[]> {
  return request(`/api/v1/crm/atividades/${id}/historico`);
}

export async function comentarAtividade(id: number, texto: string): Promise<HistoricoAtividade> {
  return request(`/api/v1/crm/atividades/${id}/comentario`, {
    method: "POST",
    body: JSON.stringify({ texto }),
  });
}

/** prazo vazio remove o prazo. A troca fica registrada no historico. */
export async function alterarPrazoAtividade(id: number, prazo: string) {
  return request(`/api/v1/crm/atividades/${id}/prazo`, {
    method: "POST",
    body: JSON.stringify({ prazo }),
  });
}

export type SemaforoAtividade = "verde" | "amarelo" | "vermelho" | "cinza";

export interface AtividadeCrm {
  id: number;
  cnpj: string | null;
  titulo: string;
  tipo: string;
  descricao: string | null;
  responsavel_user_id: number | null;
  responsavel_username?: string | null;
  razao_social?: string;
  prazo: string | null;
  status: StatusAtividade;
  criado_por: string | null;
  criado_em: string;
  concluido_em: string | null;
  /** Cor de acompanhamento (calculada no banco, igual ao monitor de e-mails). */
  semaforo: SemaforoAtividade;
  dias_aberta: number | null;
  /** Negativo = atrasada. null quando a atividade nao tem prazo. */
  dias_para_prazo: number | null;
  /** Quantos eventos de acompanhamento (comentarios + mudancas). */
  n_historico?: number;
  n_anexos?: number;
}

/** Todas as atividades da organizacao (board agregado, tipo Trello). */
export function listarTodasAtividades(): Promise<AtividadeCrm[]> {
  return request("/api/v1/crm/atividades");
}

export function moverAtividadeCrm(id: number, status: StatusAtividade): Promise<{ ok: boolean }> {
  return request(`/api/v1/crm/atividades/${id}/mover`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
}

export function listarUsuariosOrg(): Promise<UsuarioOrg[]> {
  return request("/api/v1/crm/usuarios");
}

export function listarAtividadesCrm(cnpj: string): Promise<AtividadeCrm[]> {
  return request(`/api/v1/crm/${encodeURIComponent(cnpj)}/atividades`);
}

export function criarAtividadeCrm(cnpj: string, data: {
  titulo: string; tipo?: string; descricao?: string; responsavel_user_id?: number; prazo?: string;
}): Promise<AtividadeCrm> {
  return request(`/api/v1/crm/${encodeURIComponent(cnpj)}/atividades`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export interface EmpresaBusca {
  cnpj_completo: string;
  razao_social: string;
  municipio: string;
}

/** Busca rapida por nome/CNPJ, pra vincular atividade a uma empresa. */
export function buscarEmpresaRapido(q: string): Promise<EmpresaBusca[]> {
  return request(`/api/v1/crm/buscar-empresa?q=${encodeURIComponent(q)}`);
}

/** Cria atividade direto do board. Empresa (cnpj) e' opcional. */
export function criarAtividadeAvulsa(data: {
  titulo: string; tipo?: string; descricao?: string;
  responsavel_user_id?: number; prazo?: string; cnpj?: string;
}): Promise<AtividadeCrm> {
  return request("/api/v1/crm/atividades", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function concluirAtividadeCrm(id: number): Promise<{ ok: boolean }> {
  return request(`/api/v1/crm/atividades/${id}/concluir`, { method: "POST" });
}

export function deletarAtividadeCrm(id: number): Promise<{ ok: boolean }> {
  return request(`/api/v1/crm/atividades/${id}`, { method: "DELETE" });
}

// ==================== CLASSIFICACAO DE PERFIL ====================

export interface CrmClassificado {
  cnpj: string;
  classificacao: string | null;
  motivo: string | null;
  status: string | null;
  parceiro: boolean;
  data_atualizacao: string | null;
  notas: string | null;
  razao_social: string;
  capital_social: number;
  email: string;
  contato_fone: string;
  municipio: string;
}

export interface ClassificacaoEstatisticas {
  perfil_ideal: number;
  perfil_possivel: number;
  fora_perfil: number;
  parceiro: number;
  sem_classificacao: number;
  total_crm: number;
}

/** Roda a regra de perfil na base inteira (lote). Retorna contadores. */
export async function classificarBase(limite?: number): Promise<{ ok: boolean; processadas: number; totais: Record<string, number>; erro?: string }> {
  const q = limite ? `?limite=${limite}` : "";
  return request(`/api/v1/crm/classificar${q}`, { method: "POST" });
}

export async function listarCrmClassificados(filtro?: CrmClassificacao | "sem_classificacao"): Promise<CrmClassificado[]> {
  const q = filtro ? `?filtro=${filtro}` : "";
  return request(`/api/v1/crm/classificacao${q}`);
}

export async function getCrmClassificacaoEstatisticas(): Promise<ClassificacaoEstatisticas> {
  return request("/api/v1/crm/classificacao/estatisticas");
}

export async function getMetricas() {
  return request("/api/v1/dashboard/metricas");
}

// ==================== MONITOR DE EMAILS (FOLLOW-UP COM SEMAFORO) ====================

export interface MonitorEmail {
  id: number;
  campaign_id: number | null;
  cnpj: string;
  email_destino: string;
  assunto: string | null;
  status: string;
  erro: string | null;
  sequencia_passo: number;
  enviado_em: string | null;
  aberto_em: string | null;
  criado_em: string;
  campanha_nome: string | null;
  dias_desde_envio: number;
  semaforo_status: "verde" | "amarelo" | "vermelho" | "cinza";
  razao_social: string | null;
  nome_fantasia: string | null;
}

export interface MonitorStats {
  total_enviados: number;
  verde: number;
  amarelo: number;
  vermelho: number;
  cinza: number;
  total: number;
}

export async function listarEmailsMonitor(
  campaignId?: number,
  semaforo?: string,
  diasSla = 7,
  limit = 200,
  offset = 0,
): Promise<MonitorEmail[]> {
  const params = new URLSearchParams();
  if (campaignId) params.append("campaign_id", String(campaignId));
  if (semaforo) params.append("semaforo", semaforo);
  params.append("dias_sla", String(diasSla));
  params.append("limit", String(limit));
  params.append("offset", String(offset));
  return request(`/api/v1/emails-enviados/monitor?${params}`);
}

export async function getMonitorStats(diasSla = 7): Promise<MonitorStats> {
  return request(`/api/v1/emails-enviados/monitor/stats?dias_sla=${diasSla}`);
}

export async function getEmailsVermelhos(limite = 50): Promise<MonitorEmail[]> {
  return request(`/api/v1/emails-enviados/monitor/vermelhos?limite=${limite}`);
}

// ==================== CAMPANHAS / TEMPLATES ====================

export interface Template {
  id?: number;
  nome: string;
  assunto: string;
  corpo_html: string;
  corpo_texto?: string | null;
  categoria_cnae?: string;
  imagem_url?: string | null;
  tem_imagem?: boolean;
  created_at?: string;
  updated_at?: string;
  criado_por?: string;
}

export interface Campanha {
  id?: number;
  nome: string;
  template_id: number | null;
  filtros: Record<string, any>;
  status?: string;
  total_destinatarios?: number;
  enviados?: number;
  erros?: number;
  eh_sequencia?: boolean;
  created_at?: string;
  created_by?: string;
  canal?: "email" | "whatsapp";
  mensagem?: string | null;
  tamanho_lote?: number | null;
  repetir_ate?: string | null;
  ultimo_lote_em?: string | null;
  ja_contatados?: number;
  lote_id?: number | null;
}

export async function listarTemplates(): Promise<Template[]> {
  return request("/api/v1/templates");
}

export async function criarTemplate(data: Template): Promise<Template> {
  return request("/api/v1/templates", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function atualizarTemplate(id: number, data: Partial<Template>): Promise<Template> {
  return request(`/api/v1/templates/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deletarTemplate(id: number): Promise<{ ok: boolean }> {
  return request(`/api/v1/templates/${id}`, { method: "DELETE" });
}

/** Envia um e-mail de teste deste template para 1 endereco. Se `cnpj` for
 *  informado, a personalizacao usa os dados REAIS daquela empresa. */
export async function enviarTesteTemplate(id: number, para: string, cnpj?: string): Promise<{ sucesso: boolean; simulado?: boolean; erro?: string }> {
  return request(`/api/v1/templates/${id}/test-send`, {
    method: "POST",
    body: JSON.stringify({ para, cnpj }),
  });
}

/** Envia/atualiza a imagem (card) de um template. Referenciada no corpo via {{imagem}}. */
export async function uploadTemplateImagem(id: number, file: File): Promise<Template> {
  const form = new FormData();
  form.append("arquivo", file);
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const orgId = getActiveOrgId();
  if (orgId) headers["X-Org-Id"] = String(orgId);
  const res = await fetch(`${API_URL}/api/v1/templates/${id}/imagem`, { method: "POST", headers, body: form });
  if (!res.ok) {
    const b = await res.json().catch(() => ({ detail: "Erro" }));
    throw new ApiError(res.status, b.detail || "Erro ao enviar imagem");
  }
  return res.json();
}

/** Aponta uma campanha existente para outro lote. null volta ao filtro salvo. */
// ==================== PAINEL DE ENVIOS ====================

export interface ItemFila {
  lote_id: number;
  lote: string;
  canal: CanalLote;
  bloco: number;
  status: string;
  template_id: number | null;
  template: string | null;
  total: number;
  pendentes: number;
  campanha_id: number | null;
  campanha: string | null;
  campanha_status: string | null;
}

export interface PainelEnvios {
  fila: ItemFila[];
  resumo: { blocos_pendentes: number; empresas_na_fila: number; dias_para_esvaziar: number };
  engajamento: {
    enviados?: number; entregues?: number; abertos?: number;
    clicados?: number; bounces?: number; bloqueados?: number;
  };
  por_dia: { dia: string; n: number }[];
  hoje: {
    enviados: number; limite: number; restante: number | null;
    por_rodada: number; janela: string;
  };
}

export async function getPainelEnvios(dias = 30): Promise<PainelEnvios> {
  return request(`/api/v1/envios/painel?dias=${dias}`);
}

/** Refaz a composição do lote a partir do filtro salvo. */
export async function recalcularLote(
  loteId: number, tamanhoBloco = 300,
): Promise<{ ok: boolean; composicao: Record<string, number>; total: number }> {
  return request(`/api/v1/lotes/${loteId}/recalcular`, {
    method: "POST",
    body: JSON.stringify({ tamanho_bloco: tamanhoBloco }),
  });
}

export async function redirecionarCampanha(
  campanhaId: number, loteId: number | null,
): Promise<{ ok: boolean; lote_id: number | null; lote?: string }> {
  return request(`/api/v1/campanhas/${campanhaId}/lote`, {
    method: "PUT",
    body: JSON.stringify({ lote_id: loteId }),
  });
}

export async function listarCampanhas(): Promise<Campanha[]> {
  return request("/api/v1/campanhas");
}

export async function criarCampanha(data: Partial<Campanha>): Promise<Campanha> {
  return request("/api/v1/campanhas", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function executarCampanha(id: number): Promise<{ sucessos: number; erros: number; restantes?: number; status?: string }> {
  return request(`/api/v1/campanhas/${id}/executar`, { method: "POST" });
}

export async function deletarCampanha(id: number): Promise<{ ok: boolean }> {
  return request(`/api/v1/campanhas/${id}`, { method: "DELETE" });
}

// ==================== LOTES DE LEADS ====================

export type CanalLote = "email" | "whatsapp" | "sem_contato";

export interface BlocoLote {
  canal: CanalLote;
  bloco: number;
  template_id: number | null;
  status: string;
  campanha_id: number | null;
  empresas: number;
}

/** Composição fixada na criação do lote — quem está nele e por qual canal. */
export interface ComposicaoLote {
  canais: Partial<Record<CanalLote, { total: number; enviados: number }>>;
  blocos: BlocoLote[];
}

export interface LoteLeads {
  id: number;
  organizacao_id: number;
  nome: string;
  filtros: any;
  total_encontrado: number;
  criado_por: string | null;
  created_at: string;
  amostra_empresas?: any[];
  composicao?: ComposicaoLote | Record<CanalLote, number>;
}

/** Define o modelo de e-mail de um bloco. Blocos do mesmo lote podem levar
 *  mensagens diferentes. */
export async function definirTemplateBloco(
  loteId: number, canal: CanalLote, bloco: number, templateId: number | null,
): Promise<{ ok: boolean }> {
  return request(`/api/v1/lotes/${loteId}/blocos/${canal}/${bloco}/template`, {
    method: "PUT",
    body: JSON.stringify({ template_id: templateId }),
  });
}

/** Descreve os filtros do lote em português, para a tela não mostrar JSON. */
export function descreverFiltros(f: Record<string, any> | null | undefined): string[] {
  if (!f) return [];
  const partes: string[] = [];
  const lista = (v: any) => (Array.isArray(v) ? v : [v]).filter(Boolean);
  const moeda = (v: any) => Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });

  if (f.busca) partes.push(`busca "${f.busca}"`);
  if (lista(f.cidade).length) partes.push(lista(f.cidade).join(", "));
  if (lista(f.cnae).length) partes.push(`${lista(f.cnae).length} setor(es) CNAE`);
  if (lista(f.porte).length) partes.push(`porte ${lista(f.porte).join(", ")}`);
  if (f.capital_min != null || f.capital_max != null) {
    partes.push(`capital ${f.capital_min != null ? `de ${moeda(f.capital_min)}` : ""}${f.capital_max != null ? ` até ${moeda(f.capital_max)}` : ""}`.trim());
  }
  if (f.divida_min != null || f.divida_max != null) {
    partes.push(`passivo ${f.divida_min != null ? `de ${moeda(f.divida_min)}` : ""}${f.divida_max != null ? ` até ${moeda(f.divida_max)}` : ""}`.trim());
  }
  if (f.fundacao_de || f.fundacao_ate) {
    partes.push(`fundação ${f.fundacao_de || "…"} a ${f.fundacao_ate || "…"}`);
  }
  if (f.incluir_inativas === false || f.incluir_inativas == null) partes.push("sem falência/RJ");
  return partes;
}

export async function listarLotes(): Promise<LoteLeads[]> {
  return request("/api/v1/lotes");
}

export async function criarLote(data: { nome: string; filtros: any }): Promise<LoteLeads> {
  return request("/api/v1/lotes", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function getLote(id: number): Promise<LoteLeads> {
  return request(`/api/v1/lotes/${id}`);
}

export async function deletarLote(id: number): Promise<{ ok: boolean }> {
  return request(`/api/v1/lotes/${id}`, { method: "DELETE" });
}

export async function criarCampanhaDoLote(id: number, data: { nome_campanha?: string; template_id?: number; canal?: string; mensagem?: string; tamanho_lote?: number }): Promise<any> {
  return request(`/api/v1/lotes/${id}/criar-campanha`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// ==================== NOTIFICACOES ====================

export interface Notificacao {
  id: number;
  tipo: string;
  titulo: string;
  mensagem: string | null;
  cnpj: string | null;
  user_id: string | null;
  lida: boolean;
  created_at: string;
  organizacao_id: number | null;
  /** Empresa onde a notificação nasceu — sem isso não dá pra ver que caiu no lugar errado. */
  organizacao_nome: string | null;
}

export async function listarNotificacoes(lidas?: boolean): Promise<Notificacao[]> {
  const params = new URLSearchParams();
  if (lidas !== undefined) params.append("lidas", String(lidas));
  const qs = params.toString();
  return request(`/api/v1/notificacoes${qs ? "?" + qs : ""}`);
}

export async function marcarNotificacaoLida(id: number): Promise<{ ok: boolean }> {
  return request(`/api/v1/notificacoes/${id}/ler`, { method: "POST" });
}

// ==================== PUSH (PWA) + BROADCAST ====================

export interface VapidInfo {
  publicKey: string | null;
  enabled: boolean;
}

export async function getVapidPublicKey(): Promise<VapidInfo> {
  return request("/api/v1/push/vapid-public-key");
}

export async function subscribePush(sub: { endpoint: string; keys: { p256dh: string; auth: string } }): Promise<{ ok: boolean }> {
  return request("/api/v1/push/subscribe", { method: "POST", body: JSON.stringify(sub) });
}

export async function unsubscribePush(endpoint: string): Promise<{ ok: boolean }> {
  return request("/api/v1/push/unsubscribe", { method: "POST", body: JSON.stringify({ endpoint }) });
}

export interface BroadcastResult {
  ok: boolean;
  organizacoes: number;
  avisos_sino: number;
  push: { enviados: number; falhos: number };
  push_configurado: boolean;
}

export async function broadcastPush(titulo: string, mensagem: string, alvo: "minha_empresa" | "todas"): Promise<BroadcastResult> {
  return request("/api/v1/push/broadcast", {
    method: "POST",
    body: JSON.stringify({ titulo, mensagem, alvo }),
  });
}

// Sobre / status do sistema (aba "Sobre" em Configuracoes)
export interface SistemaStatus {
  mes_referencia_rf: string | null;
  trimestre_pgfn: string | null;
  gerado_em: string | null;
  ultima_sincronizacao: string | null;
  total_matrizes: string | null;
  total_empresas_sincronizadas: string | null;
  total_socios_sincronizados: string | null;
  pipeline_ja_rodou: boolean;
}

export async function getSistemaStatus(): Promise<SistemaStatus> {
  return request<SistemaStatus>("/api/v1/admin/sistema/status");
}

// ==================== CONFIGURACOES: SLA (REGRAS DO MONITOR) ====================

export interface SlaConfig {
  sla_verde_dias: number;
  sla_amarelo_dias: number;
}

export async function getSlaConfig(): Promise<SlaConfig> {
  return request("/api/v1/admin/sla");
}

export async function updateSlaConfig(data: SlaConfig): Promise<SlaConfig> {
  return request("/api/v1/admin/sla", {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

// ==================== CONFIGURACOES: PERFIL/CONTA ====================

export async function trocarMinhaSenha(senhaAtual: string, novaSenha: string): Promise<{ sucesso: boolean; message: string }> {
  return request("/api/v1/auth/me/senha", {
    method: "PUT",
    body: JSON.stringify({ senha_atual: senhaAtual, nova_senha: novaSenha }),
  });
}

// ==================== CONFIGURACOES: USUARIOS ====================

export interface UsuarioAdmin {
  id: number;
  username: string;
  email: string | null;
  is_admin: boolean;
  is_active: boolean;
  created_at: string | null;
  organizacao_ids: number[];
}

export async function listarUsuarios(): Promise<UsuarioAdmin[]> {
  return request("/api/v1/admin/usuarios");
}

export async function criarUsuarioAdmin(data: { username: string; password: string; email?: string; is_admin?: boolean; organizacao_ids?: number[] }): Promise<{ username: string }> {
  return request("/api/v1/admin/usuarios", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function definirEmpresasUsuario(userId: number, organizacaoIds: number[]): Promise<{ sucesso: boolean; organizacao_ids: number[] }> {
  return request(`/api/v1/admin/usuarios/${userId}/organizacoes`, {
    method: "PUT",
    body: JSON.stringify({ organizacao_ids: organizacaoIds }),
  });
}

// ==================== ADMIN: EMPRESAS (config de e-mail por empresa) ====================

export interface OrgEmailConfig {
  organizacao_id?: number;
  smtp_host?: string | null;
  smtp_port?: number | null;
  smtp_username?: string | null;
  smtp_use_tls?: boolean;
  email_from?: string | null;
  email_from_name?: string | null;
  assinatura_html?: string | null;
  configurado: boolean;
  tem_logo: boolean;
  gmail_conta?: string | null;
  gmail_conectado?: boolean;
}

/** "eu" = a conta da pessoa logada na empresa ativa; "empresa" = o padrao da
 *  empresa (so' admin). */
export type AlvoGmail = "eu" | "empresa";

function consultaGmail(alvo: AlvoGmail, orgId?: number | null): string {
  const q = new URLSearchParams({ alvo });
  if (alvo === "empresa" && orgId != null) q.set("organizacao_id", String(orgId));
  return q.toString();
}

/** Endereco da tela de autorizacao do Google. Quem chama redireciona. */
export async function iniciarConexaoGmail(alvo: AlvoGmail, orgId?: number | null): Promise<{ url: string }> {
  return request(`/api/v1/gmail/conectar?${consultaGmail(alvo, orgId)}`);
}

export async function desconectarGmail(alvo: AlvoGmail, orgId?: number | null): Promise<{ ok: boolean }> {
  return request(`/api/v1/gmail/conexao?${consultaGmail(alvo, orgId)}`, { method: "DELETE" });
}

export async function listarOrganizacoesAdmin(): Promise<Organizacao[]> {
  return request("/api/v1/admin/organizacoes");
}

/** Muda a FONTE de prospeccao da empresa: "receita" (base publica da Receita
 *  Federal) ou "carteira" (lista propria). So' admin global -- e' decisao de
 *  contrato, nao preferencia de uso. */
export async function definirEscopoBaseOrg(
  orgId: number, escopo: "receita" | "carteira",
): Promise<{ ok: boolean }> {
  return request(`/api/v1/admin/organizacoes/${orgId}`, {
    method: "PUT",
    body: JSON.stringify({ escopo_base: escopo }),
  });
}

/** Teto diário de e-mail da empresa. `null` remove o teto próprio.
 *
 *  `EMAIL_LIMITE_DIARIO` vale para a conta inteira, que é compartilhada entre
 *  as empresas. O teto próprio deixa um domínio em warm-up enviar pouco sem
 *  frear os outros; o limite efetivo é o menor dos dois. */
export async function definirLimiteDiarioOrg(
  orgId: number, limite: number | null,
): Promise<{ ok: boolean }> {
  return request(`/api/v1/admin/organizacoes/${orgId}`, {
    method: "PUT",
    body: JSON.stringify({ email_limite_diario: limite }),
  });
}

export async function getOrgEmailConfig(orgId: number): Promise<OrgEmailConfig> {
  return request(`/api/v1/admin/organizacoes/${orgId}/smtp`);
}

export async function setOrgEmailConfig(orgId: number, data: Partial<OrgEmailConfig> & { smtp_password?: string }): Promise<OrgEmailConfig> {
  return request(`/api/v1/admin/organizacoes/${orgId}/smtp`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function uploadOrgLogo(orgId: number, file: File): Promise<{ sucesso: boolean; tem_logo: boolean }> {
  const form = new FormData();
  form.append("arquivo", file);
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const orgActive = getActiveOrgId();
  if (orgActive) headers["X-Org-Id"] = String(orgActive);
  const res = await fetch(`${API_URL}/api/v1/admin/organizacoes/${orgId}/logo`, {
    method: "POST", headers, body: form,
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({ detail: "Erro" }));
    throw new ApiError(res.status, b.detail || "Erro ao enviar logo");
  }
  return res.json();
}

export async function atualizarUsuarioAdmin(userId: number, data: { is_admin?: boolean; is_active?: boolean; email?: string | null }): Promise<UsuarioAdmin> {
  return request(`/api/v1/admin/usuarios/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function excluirUsuarioAdmin(userId: number): Promise<{ sucesso: boolean; message: string }> {
  return request(`/api/v1/admin/usuarios/${userId}`, { method: "DELETE" });
}

export async function redefinirSenhaUsuarioAdmin(userId: number, novaSenha: string): Promise<{ sucesso: boolean; message: string }> {
  return request(`/api/v1/admin/usuarios/${userId}/redefinir-senha`, {
    method: "POST",
    body: JSON.stringify({ nova_senha: novaSenha }),
  });
}

// ==================== ANALYTICS (telas de analise) ====================

/** Filtros compartilhados por todos os endpoints de analytics. */
export interface AnalyticsFiltros {
  cidade?: string[];
  cnae?: string[];
  porte?: string[];
  divida_min?: number;
  divida_max?: number;
  capital_min?: number;
  capital_max?: number;
  incluir_inativas?: boolean;
}

function filtrosToQuery(f: AnalyticsFiltros = {}): URLSearchParams {
  const p = new URLSearchParams();
  (f.cidade ?? []).forEach(v => p.append("cidade", v));
  (f.cnae ?? []).forEach(v => p.append("cnae", v));
  (f.porte ?? []).forEach(v => p.append("porte", v));
  if (f.divida_min != null) p.append("divida_min", String(f.divida_min));
  if (f.divida_max != null) p.append("divida_max", String(f.divida_max));
  if (f.capital_min != null) p.append("capital_min", String(f.capital_min));
  if (f.capital_max != null) p.append("capital_max", String(f.capital_max));
  if (f.incluir_inativas) p.append("incluir_inativas", "true");
  return p;
}

export interface AnalyticsResumo {
  total_empresas: number;
  divida_total: number;
  capital_total: number;
  divida_media: number;
  capital_medio: number;
  qtd_cidades: number;
  qtd_setores: number;
  qtd_com_divida: number;
  qtd_inativas: number;
  /** false quando o banco ainda nao tem coluna de passivo (ETL legado). */
  tem_dados_divida?: boolean;
}

export interface CidadeAgg {
  cidade: string;
  qtd: number;
  capital_total: number;
  divida_total: number;
}

export interface SetorAgg {
  cnae: string;
  descricao: string;
  qtd: number;
  capital_total: number;
  divida_total: number;
  divida_media: number;
}

export interface PorteAgg {
  porte: string;
  qtd: number;
}

export interface TopEmpresa {
  cnpj_completo: string;
  razao_social: string;
  municipio: string;
  cnae_principal: string;
  cnae_descricao: string;
  porte_nome: string | null;
  capital_social: number;
  divida_total: number;
  /** true quando o banco ainda nao tem passivo (ranking degradou p/ capital). */
  sem_divida?: boolean;
  ordenado_por?: "divida" | "capital";
}

export interface SocioAgg {
  nome_socio: string;
  qtd_empresas: number;
  divida_total: number;
  capital_total: number;
}

export interface SocioEmpresa {
  cnpj_completo: string;
  razao_social: string;
  municipio: string;
  cnae_principal: string;
  cnae_descricao: string;
  capital_social: number;
  divida_total: number;
}

export interface OpcoesFiltro {
  cidades: string[];
  portes: string[];
  cnaes: { codigo: string; descricao: string; qtd: number }[];
}

export function getAnalyticsResumo(f?: AnalyticsFiltros): Promise<AnalyticsResumo> {
  return request(`/api/v1/analytics/resumo?${filtrosToQuery(f)}`);
}

export function getAnalyticsPorCidade(f?: AnalyticsFiltros, limite = 20): Promise<CidadeAgg[]> {
  const p = filtrosToQuery(f); p.append("limite", String(limite));
  return request(`/api/v1/analytics/por-cidade?${p}`);
}

export function getAnalyticsPorSetor(f?: AnalyticsFiltros, limite = 20): Promise<SetorAgg[]> {
  const p = filtrosToQuery(f); p.append("limite", String(limite));
  return request(`/api/v1/analytics/por-setor?${p}`);
}

export function getAnalyticsPorPorte(f?: AnalyticsFiltros): Promise<PorteAgg[]> {
  return request(`/api/v1/analytics/por-porte?${filtrosToQuery(f)}`);
}

export function getAnalyticsTopEmpresas(
  ordenarPor: "divida" | "capital" = "divida", limite = 10, f?: AnalyticsFiltros,
): Promise<TopEmpresa[]> {
  const p = filtrosToQuery(f);
  p.append("ordenar_por", ordenarPor);
  p.append("limite", String(limite));
  return request(`/api/v1/analytics/top-empresas?${p}`);
}

export function getSociosRanking(f?: AnalyticsFiltros, limite = 50): Promise<SocioAgg[]> {
  const p = filtrosToQuery(f); p.append("limite", String(limite));
  return request(`/api/v1/analytics/socios/ranking?${p}`);
}

export function getSocioDetalhe(nome: string): Promise<SocioEmpresa[]> {
  return request(`/api/v1/analytics/socios/detalhe?nome=${encodeURIComponent(nome)}`);
}

export function getOpcoesFiltro(): Promise<OpcoesFiltro> {
  return request("/api/v1/analytics/opcoes-filtro");
}

// ==================== CONSULTA EM LINGUAGEM NATURAL ====================

export interface FiltroInterpretado {
  cidade: string | null;
  cnae: string | null;
  busca: string | null;
  ordenar_por: "capital_social" | "divida_total" | "nenhum";
  ordem: "asc" | "desc";
  limite: number;
}

export interface EmpresaConsultaNatural {
  cnpj_completo: string;
  razao_social: string;
  nome_fantasia?: string;
  municipio?: string;
  cnae_principal?: string;
  capital_social?: number;
  divida_total?: number;
  porte_nome?: string;
}

export interface ConsultaNaturalResposta {
  pergunta_original: string;
  filtro_interpretado: FiltroInterpretado;
  total_encontrado: number;
  empresas: EmpresaConsultaNatural[];
  resumo_em_texto: string;
}

/** Pergunta em portugues livre -> filtro estruturado (via Claude) -> resultado.
 * O modelo nunca toca o banco: so preenche um filtro validado por Pydantic,
 * que roda pelo mesmo caminho do /empresas normal. */
export async function consultaNatural(pergunta: string): Promise<ConsultaNaturalResposta> {
  return request("/api/v1/empresas/consulta-natural", {
    method: "POST",
    body: JSON.stringify({ pergunta }),
  });
}

// ==================== ENRIQUECIMENTO DE CONTATO (IA, so admin) ====================

export interface ItemEnriquecimento {
  id: number;
  cnpj: string;
  tipo_alvo: string;
  nome_alvo: string | null;
  campo: string;
  valor: string | null;
  fonte_url: string | null;
  fonte_titulo: string | null;
  coletado_por: string;
  coletado_em: string;
  removido_em: string | null;
}

/** Dispara o agente (Claude + busca na web) pra achar contato publico da
 * empresa/socios. Restrito a admin no backend (require_admin) -- dispara
 * custo de LLM por uso, entao nunca chame automaticamente. */
export async function enriquecerEmpresa(cnpj: string): Promise<{ cnpj: string; itens_encontrados: number; itens: ItemEnriquecimento[] }> {
  return request(`/api/v1/empresas/${encodeURIComponent(cnpj)}/enriquecer`, { method: "POST" });
}

export async function listarEnriquecimento(cnpj: string): Promise<ItemEnriquecimento[]> {
  return request(`/api/v1/empresas/${encodeURIComponent(cnpj)}/enriquecimento`);
}

/** Direito de exclusao (LGPD): apaga o valor/fonte coletados, mantendo so o
 * registro de auditoria de que a remocao aconteceu. */
export async function removerEnriquecimento(cnpj: string): Promise<{ cnpj: string; itens_removidos: number }> {
  return request(`/api/v1/empresas/${encodeURIComponent(cnpj)}/enriquecimento`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Carteira propria (empresa com escopo_base = "carteira")
// ---------------------------------------------------------------------------

export interface CategoriaCarteira { categoria: string; total: number }

export interface ResumoCarteira {
  escopo_base: "receita" | "carteira";
  tem_carteira?: boolean;
  total: number;
  categorias: CategoriaCarteira[];
}

export interface ResultadoImportacao {
  salvos: number;
  ignorados: { linha: number; motivo: string }[];
  total_ignorados: number;
  total_na_carteira: number;
  categorias: CategoriaCarteira[];
}

export async function getResumoCarteira(): Promise<ResumoCarteira> {
  return request("/api/v1/carteira/resumo");
}

/** Sobe a planilha. Recarregar o mesmo arquivo ATUALIZA em vez de duplicar
 *  (a chave e' empresa + CNPJ), e coluna vazia na recarga nao apaga o que ja'
 *  estava preenchido -- quem completou um e-mail a mao nao perde o trabalho. */
export async function importarCarteira(file: File): Promise<ResultadoImportacao> {
  const form = new FormData();
  form.append("arquivo", file);
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const orgActive = getActiveOrgId();
  if (orgActive) headers["X-Org-Id"] = String(orgActive);
  const res = await fetch(`${API_URL}/api/v1/carteira/importar`, {
    method: "POST", headers, body: form,
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({ detail: "Erro" }));
    throw new ApiError(res.status, b.detail || "Erro ao importar a carteira");
  }
  return res.json();
}

export async function removerDaCarteira(cnpj: string): Promise<{ ok: boolean }> {
  return request(`/api/v1/carteira/${encodeURIComponent(cnpj)}`, { method: "DELETE" });
}

// ==================== PAINEL INICIAL ====================

export interface PainelInicio {
  escopo_base: "receita" | "carteira";
  tem_carteira?: boolean;
  base: {
    total: number | null;
    /** true quando o total veio de estimativa do planner, nao de contagem. */
    estimado: boolean;
    /** null na base da Receita: saber isso exigiria varrer 1,68M de linhas. */
    com_email: number | null;
    cidades: number | null;
  };
  alcance: { contatados: number; penetracao_pct: number | null };
  crm: Record<string, number>;
  crm_total: number;
  envios: {
    hoje_org: number;
    /** null fora de admin global: desse numero se deduz o volume da OUTRA empresa. */
    hoje_conta: number | null;
    limite: number;
    /** null fora de admin global, pelo mesmo motivo de hoje_conta. */
    restante: number | null;
    /** Teto da conta esgotado hoje -- o unico sinal da conta que todos veem. */
    teto_atingido: boolean;
    fila_pendente: number;
    por_dia: { dia: string; n: number }[];
  };
  engajamento: { enviados?: number; entregues?: number; abertos?: number; clicados?: number };
  atividades: { pendentes: number; atrasadas: number };
  atualizado_em: string | null;
}

export async function getPainelInicio(dias = 14): Promise<PainelInicio> {
  return request(`/api/v1/painel/inicio?dias=${dias}`);
}

// ---- Disparar: mandar os proximos N da lista propria ----

export interface ResumoDisparo {
  na_lista: number;
  sem_email: number;
  /** E-mails de escritorio de contabilidade: fora do envio. */
  contabilidade: number;
  /** Mapeados como sem perfil comercial: fora do envio. */
  desinteresse: number;
  /** E-mail usado por mais de um contato (contador, servico de abertura): fora do envio. */
  compartilhado: number;
  disponiveis: number;
  /** Ja' receberam o 1o e-mail; e' daqui que sai o publico do follow-up. */
  em_trabalho: number;
  fora: number;
  /** Quantos ainda cabem hoje no teto de envios; null = sem teto. */
  pode_enviar_hoje: number | null;
  /** Em trabalho ha' `dias_followup` dias ou mais, sem resposta. */
  followup_devidos: number;
  /** Fila com ritmo: `por_rodada` contatos a cada `intervalo_min` minutos. */
  fila: { na_fila: number; proxima_rodada_em: string | null };
  por_rodada: number;
  intervalo_min: [number, number];
  dias_followup: number;
  max_por_clique: number;
  remetentes: { username: string; email_from: string; email_from_name: string | null; gmail_proprio: boolean }[];
}

export interface ResultadoDisparo {
  enviados: number;
  /** Quantos contatos deste pedido foram para cada modelo (id do modelo -> quantidade). */
  distribuicao?: Record<string, number>;
  /** Entraram na fila neste pedido (a 1a rodada sai na hora, o resto no ritmo). */
  enfileirados?: number;
  na_fila?: number;
  janela_fechada?: boolean;
  erro_rodada?: string | null;
  erros: number;
  pedidos: number;
  barrados_na_conferencia?: number;
  remetente?: string;
  erros_detalhe?: { cnpj: string; erro: string }[];
  mensagem?: string | null;
}

export interface EnvioDoDia {
  email_destino: string;
  assunto: string | null;
  status: string;
  erro: string | null;
  quando: string | null;
}

export async function getResumoDisparo(): Promise<ResumoDisparo> {
  return request("/api/v1/disparo/resumo");
}

export async function getHistoricoDisparo(): Promise<EnvioDoDia[]> {
  return request("/api/v1/disparo/historico");
}

export async function enviarDisparo(dados: {
  quantidade: number; template_id?: number; template_ids?: number[]; remetente?: string;
}): Promise<ResultadoDisparo> {
  return request("/api/v1/disparo/enviar", { method: "POST", body: JSON.stringify(dados) });
}

export interface FollowupDevido {
  cnpj_completo: string;
  razao_social: string | null;
  nome_fantasia: string | null;
  email: string;
  municipio: string | null;
  dias: number;
}

export async function getFollowupLista(): Promise<FollowupDevido[]> {
  return request("/api/v1/disparo/followup/lista");
}

export async function enviarFollowup(dados: {
  quantidade: number; template_id: number; remetente?: string;
}): Promise<ResultadoDisparo> {
  return request("/api/v1/disparo/followup", { method: "POST", body: JSON.stringify(dados) });
}

/** respondeu / sem_interesse tiram o contato do follow-up; null desfaz. */
export async function marcarSituacaoContato(cnpj: string, situacao: "respondeu" | "sem_interesse" | null): Promise<{ ok: boolean }> {
  return request("/api/v1/disparo/situacao", { method: "POST", body: JSON.stringify({ cnpj, situacao }) });
}

export interface WhatsappContato {
  cnpj_completo: string;
  nome: string;
  empresa: string;
  cidade: string;
  numero: string;
  grupo: "abriu" | "email" | "sem_email" | "novo";
  /** E-mail de dominio da empresa (provavel site). */
  tem_site: boolean;
  site_url: string;
  texto: string;
}
export type WhatsappFaltam = Record<WhatsappContato["grupo"], number>;

/** WhatsApp manual: quem chamar, por prioridade, com numero e texto prontos. */
export type FiltroSite = "todos" | "com" | "sem";

export async function getWhatsappLista(limite: number, eu: string, site: FiltroSite = "todos"):
  Promise<{ faltam: WhatsappFaltam; sites: { com: number; sem: number; outros: number }; contatos: WhatsappContato[] }> {
  return request(`/api/v1/disparo/whatsapp?limite=${limite}&eu=${encodeURIComponent(eu)}&site=${site}`);
}

export interface ContatoBusca {
  cnpj_completo: string;
  nome: string;
  empresa: string;
  cidade: string;
  fone: string;
  email: string;
  situacao: "respondeu" | "sem_interesse" | "desinteresse_comercial" | null;
  whatsapp: "chamado" | "sem_whatsapp" | null;
}

/** Acha um contato por telefone, CNPJ, nome ou e-mail (para registrar a resposta dele). */
export async function buscarContato(q: string): Promise<ContatoBusca[]> {
  return request(`/api/v1/disparo/contato/buscar?q=${encodeURIComponent(q)}`);
}

/** chamado / sem_whatsapp tiram o contato da lista; null desfaz. */
export async function marcarWhatsapp(cnpj: string, status: "chamado" | "sem_whatsapp" | null): Promise<{ ok: boolean }> {
  return request("/api/v1/disparo/whatsapp/marcar", { method: "POST", body: JSON.stringify({ cnpj, status }) });
}

export async function cancelarFila(): Promise<{ canceladas: number }> {
  return request("/api/v1/disparo/fila/cancelar", { method: "POST" });
}

/** Relogio da tela aberta: pede a proxima rodada se ja' estiver na hora. */
export async function avancarFila(): Promise<{ na_fila: number; proxima_rodada_em: string | null }> {
  return request("/api/v1/disparo/fila/avancar", { method: "POST" });
}

export interface ModeloMetrica {
  id: number;
  nome: string;
  enviados: number;
  entregues: number;
  abertos: number;
  clicados: number;
  respondeu: number;
  sem_interesse: number;
}

/** Resultado por modelo de primeiro contato (o teste de abordagens). */
export async function getMetricasModelos(): Promise<{ desde: string | null; modelos: ModeloMetrica[] }> {
  return request("/api/v1/disparo/modelos");
}
