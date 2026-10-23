# Whodados - Estrutura de Seguranca

Documentacao da arquitetura de seguranca implementada no projeto.

## Visao Geral

O Whodados implementa defesa em profundidade com multiplas camadas:

1. CORS Middleware (camada externa)
2. Security Headers (HSTS, CSP, X-Frame-Options)
3. Rate Limiting (60 req/min por IP)
4. Brute Force Protection (login lockout)
5. JWT Authentication (Bearer token)
6. Audit Logging (todas as acoes sensiveis)
7. Supabase Row Level Security - RLS (camada interna)

## Camadas Implementadas

### 1. Security Headers Middleware (backend/security/headers.py)

Adiciona headers HTTP de seguranca em todas as respostas:

- Content-Security-Policy: default-src self (XSS)
- X-Frame-Options: DENY (Clickjacking)
- X-Content-Type-Options: nosniff (MIME sniffing)
- X-XSS-Protection: 1 mode=block (XSS legacy)
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy: camera=(), microphone=()
- Strict-Transport-Security: max-age=31536000 (HTTPS em prod)

### 2. Rate Limiting (backend/security/rate_limiter.py)

Limite de requisicoes por IP:
- Padrao: 60 req/min por IP
- Endpoints generosos: 120 req/min (empresas)
- Janela: 60 segundos
- Storage: Redis (se REDIS_URL configurado) ou in-memory
- Resposta: HTTP 429 com Retry-After

### 3. Brute Force Protection (backend/db/service.py)

Bloqueio de conta apos multiplas tentativas:
- Tentativas maximas: 5 falhas
- Janela de bloqueio: 15 minutos
- Tabela: login_attempts
- Configuravel via LOGIN_MAX_ATTEMPTS e LOGIN_LOCKOUT_MINUTES

### 4. JWT Authentication (backend/auth/)

- Algoritmo: HS256
- Access Token: 60 min (configuravel)
- Refresh Token: 7 dias (preparado)
- Hash: bcrypt com 12 rounds
- Issuer: whodados

### 5. Audit Logging (backend/security/audit.py)

Log de auditoria de todas as acoes sensiveis:

- LOGIN_SUCCESS: Login bem-sucedido
- LOGIN_FAILED: Tentativa de login falha
- RATE_LIMIT_HIT: Rate limit atingido
- AUTH_DENIED: Token invalido/expirado
- FORBIDDEN_ACCESS: Tentativa de acesso negado
- EMPRESA_VIEW: Visualizacao de empresa
- CRM_CREATE: Criacao de CRM
- CAMPANHA_EXECUTE: Execucao de campanha


---

## Tabelas do Banco (Supabase)

```sql
-- Tabela de auditoria
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    action VARCHAR(100) NOT NULL,
    user_id VARCHAR(50),
    ip_address INET,
    user_agent TEXT,
    resource_type VARCHAR(50),
    resource_id VARCHAR(100),
    details JSONB DEFAULT '{}'::jsonb,
    success BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Tentativas de login (brute force protection)
CREATE TABLE login_attempts (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    ip_address INET,
    success BOOLEAN DEFAULT FALSE,
    attempted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indices
CREATE INDEX idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX idx_audit_log_action ON audit_log(action);
CREATE INDEX idx_audit_log_created_at ON audit_log(created_at DESC);
CREATE INDEX idx_login_attempts_username ON login_attempts(username);
CREATE INDEX idx_login_attempts_ip ON login_attempts(ip_address);
CREATE INDEX idx_login_attempts_time ON login_attempts(attempted_at DESC);
```

## Deploy no Supabase - Passo a Passo

1. Configurar Secrets no painel (Vercel/Railway/Fly):
   - SECRET_KEY: gerar com `python -c "import secrets; print(secrets.token_urlsafe(32))"`
   - DATABASE_URL: connection string do Supabase
   - CORS_ORIGINS: URL do frontend em producao

2. Habilitar Row Level Security (RLS):
```sql
ALTER TABLE app_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE campanhas ENABLE ROW LEVEL SECURITY;
```

3. Criar indices adicionais recomendados:
```sql
CREATE INDEX idx_cnpj ON crm(cnpj);
CREATE INDEX idx_user ON crm(criado_por);
CREATE INDEX idx_campaign_status ON campanhas(status);
CREATE INDEX idx_emails_enviados_campaign ON emails_enviados(campaign_id);
```

## Monitoramento - Queries Uteis

```sql
-- Ultimas acoes de um usuario
SELECT * FROM audit_log WHERE user_id = 'joao' ORDER BY created_at DESC LIMIT 50;

-- Tentativas de login falhas (ultimas 24h)
SELECT username, ip_address, COUNT(*) as tentativas
FROM login_attempts
WHERE success = FALSE AND attempted_at > NOW() - INTERVAL '24 hours'
GROUP BY username, ip_address HAVING COUNT(*) >= 3
ORDER BY tentativas DESC;

-- IPs com mais acessos negados
SELECT ip_address, COUNT(*) as total FROM audit_log
WHERE success = FALSE AND action = 'auth_denied'
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY ip_address ORDER BY total DESC LIMIT 20;
```

## Verificacoes Antes de Deploy

- [ ] SECRET_KEY gerada com secrets.token_urlsafe(32)
- [ ] APP_ENV=production configurado
- [ ] CORS_ORIGINS aponta apenas para o frontend oficial
- [ ] HTTPS habilitado (HSTS ativo)
- [ ] Tabelas com RLS no Supabase
- [ ] Senhas fortes no banco (bcrypt 12 rounds)
- [ ] Rate limit testado
- [ ] Logs sendo salvos no banco

## Arquivos Criados/Modificados

### Criados:
- backend/security/__init__.py
- backend/security/rate_limiter.py
- backend/security/headers.py
- backend/security/audit.py
- SECURITY.md

### Modificados:
- backend/main.py (middlewares integrados)
- backend/config.py (variaveis de seguranca)
- backend/db/config.py (tabelas audit_log, login_attempts)
- backend/db/service.py (funcoes de audit/login tracking)
- backend/db/__init__.py (exports)
- backend/endpoints_part1.py (audit em login/empresa)
- backend/.env.example (documentacao)
- backend/requirements.txt (limpo)
- pipeline/pipeline.py (sem scraping)
- pipeline/requirements-dev.txt (sem bs4/lxml)

### Removidos:
- backend/mailer/enrichment.py
- frontend/src/app/dashboard/enriquecimento/ (pagina inteira)
- frontend/src/lib/api.ts (funcoes de enriquecimento)
- frontend/src/app/dashboard/layout.tsx (link do menu)
- backend/schemas.py (EnriquecimentoResponse)
- backend/endpoints_part2.py (endpoints /enriquecer/*)

## Resumo Final

### Historico: webscraping removido em 2026-09
- Webscraping DuckDuckGo (emails/telefones)
- Webscraping PGFN no pipeline (substituido por env var)

### ATENCAO -- enriquecimento voltou (arquitetura diferente)
O enriquecimento de contato existe de novo, agora via Claude + web search
da Anthropic (`backend/agents/enriquecimento_service.py`,
`endpoints_enriquecimento.py`, `api.ts::enriquecerEmpresa`). Nao e' o
scraping antigo:
- restrito a admin (`require_admin`) -- dispara custo de LLM por uso;
- so' coleta contato PUBLICAMENTE disponivel, com `fonte_url` obrigatoria;
- tem direito de eliminacao (LGPD, Art. 18): `DELETE .../enriquecimento`
  apaga valor e fonte, mantendo so' o registro de auditoria da remocao.

### Adicionado (seguranca completa):
- Rate Limiter Middleware (Redis-ready)
- Security Headers (CSP, HSTS, X-Frame-Options, etc.)
- Audit Logging (tabela + middleware)
- Brute Force Protection (5 tentativas / 15 min)
- Variaveis de ambiente documentadas
- Estrutura pronta para RLS no Supabase
