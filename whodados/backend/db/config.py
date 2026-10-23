"""DB Config - WhoDados."""
from __future__ import annotations
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
try:
    from ..config import settings
except ImportError:
    import os as _os
    class _S:
        DATABASE_URL = _os.getenv("DATABASE_URL", "")
        DB_POOL_SIZE = int(_os.getenv("DB_POOL_SIZE", "5"))
        DB_POOL_TIMEOUT = int(_os.getenv("DB_POOL_TIMEOUT", "30"))
    settings = _S()
try:
    from ..logger import get_logger
except ImportError:
    import logging
    get_logger = lambda x: logging.getLogger(x)
log = get_logger(__name__)
_pool = None

def init_pool():
    global _pool
    if _pool: return _pool
    if not settings.DATABASE_URL: return None
    try:
        _pool = pool.ThreadedConnectionPool(1, settings.DB_POOL_SIZE, dsn=settings.DATABASE_URL, connect_timeout=settings.DB_POOL_TIMEOUT)
        return _pool
    except Exception as e: raise

@contextmanager
def get_conn():
    if _pool is None: init_pool()
    if _pool is None: raise RuntimeError("DB unavailable")
    c = _pool.getconn()
    try:
        yield c; c.commit()
    except:
        c.rollback(); raise
    finally:
        _pool.putconn(c)

@contextmanager
def get_cur(d=True):
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor if d else None)
        try: yield cur
        finally: cur.close()

def ensure_tables():
    if not settings.DATABASE_URL: return
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS app_users (id SERIAL PRIMARY KEY, username VARCHAR(50) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL, email VARCHAR(255), is_admin BOOLEAN DEFAULT FALSE, is_active BOOLEAN DEFAULT TRUE, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW())")
        cur.execute("CREATE TABLE IF NOT EXISTS password_reset_tokens (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, token_hash VARCHAR(255) NOT NULL, expires_at TIMESTAMP WITH TIME ZONE NOT NULL, used BOOLEAN DEFAULT FALSE, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW())")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user ON password_reset_tokens(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_hash ON password_reset_tokens(token_hash)")
        # organizacoes nasce aqui, e nao junto do resto do multiempresa, porque
        # varias tabelas abaixo declaram REFERENCES organizacoes(id): num banco
        # vazio a FK nao teria a que apontar. Idempotente, entao a criacao
        # repetida em _run_ensure_multiempresa e' inofensiva.
        cur.execute("""CREATE TABLE IF NOT EXISTS organizacoes (
            id SERIAL PRIMARY KEY,
            nome VARCHAR(120) NOT NULL,
            slug VARCHAR(60) UNIQUE NOT NULL,
            ativo BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""")
        cur.execute("CREATE TABLE IF NOT EXISTS crm (id SERIAL PRIMARY KEY, cnpj VARCHAR(18) UNIQUE NOT NULL, status VARCHAR(50), notas TEXT, data_atualizacao TIMESTAMP WITH TIME ZONE DEFAULT NOW(), criado_por VARCHAR(50))")
        cur.execute("CREATE TABLE IF NOT EXISTS email_templates (id SERIAL PRIMARY KEY, nome VARCHAR(100) NOT NULL, assunto VARCHAR(200) NOT NULL, corpo_html TEXT NOT NULL, corpo_texto TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), criado_por VARCHAR(50))")
        # Adiciona coluna categoria_cnae se nao existir (suporte a templates por CNAE)
        cur.execute("ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS categoria_cnae VARCHAR(50) DEFAULT 'todos'")
        # Card/imagem do template (enviada no corpo do email via {{imagem}})
        cur.execute("ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS imagem_data BYTEA")
        cur.execute("ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS imagem_mime VARCHAR(50)")
        cur.execute("ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS tem_imagem BOOLEAN DEFAULT FALSE")
        cur.execute("CREATE TABLE IF NOT EXISTS campanhas (id SERIAL PRIMARY KEY, nome VARCHAR(200) NOT NULL, template_id INTEGER, filtros JSONB, status VARCHAR(50) DEFAULT 'rascunho', total_destinatarios INTEGER DEFAULT 0, enviados INTEGER DEFAULT 0, erros INTEGER DEFAULT 0, eh_sequencia BOOLEAN DEFAULT FALSE, dias_sequencia JSONB, agendada_para TIMESTAMP WITH TIME ZONE, iniciada_em TIMESTAMP WITH TIME ZONE, concluida_em TIMESTAMP WITH TIME ZONE, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), created_by VARCHAR(50))")
        # Canal (email/whatsapp) + envio em lotes diarios (o limite de
        # mensagens/dia do WhatsApp e' do Twilio, nao nosso -- tamanho_lote
        # deixa a campanha respeitar isso e ir mandando aos poucos em vez de
        # estourar o limite tentando mandar tudo de uma vez).
        cur.execute("ALTER TABLE campanhas ADD COLUMN IF NOT EXISTS canal VARCHAR(20) DEFAULT 'email'")
        cur.execute("ALTER TABLE campanhas ADD COLUMN IF NOT EXISTS mensagem TEXT")
        cur.execute("ALTER TABLE campanhas ADD COLUMN IF NOT EXISTS tamanho_lote INTEGER")
        cur.execute("ALTER TABLE campanhas ADD COLUMN IF NOT EXISTS repetir_ate DATE")
        cur.execute("ALTER TABLE campanhas ADD COLUMN IF NOT EXISTS ultimo_lote_em TIMESTAMP WITH TIME ZONE")
        # Campanha nascida de um lote: o publico vem de lote_empresas (lista
        # fixa) em vez do filtro reavaliado, e o modelo vem do bloco.
        cur.execute("ALTER TABLE campanhas ADD COLUMN IF NOT EXISTS lote_id INTEGER")
        # De qual PESSOA sai o e-mail desta campanha: username, nao
        # endereco -- o endereco vem de usuario_smtp_config dela.
        #
        # O remetente e' da campanha, e nao de quem a executa, porque no
        # disparo automatico quem executa e' o cron ({"sub": "cron"}), que
        # nao tem configuracao propria. Assim a campanha de cada operador
        # sai do endereco dele mesmo sem ninguem logado.
        # NULL: cai em quem disparou, ou na empresa.
        cur.execute("ALTER TABLE campanhas ADD COLUMN IF NOT EXISTS remetente_username VARCHAR(50)")
        # Ledger generico de quem ja foi contatado por qual campanha -- usado
        # pra calcular o "proximo lote" (quem do filtro ainda nao foi
        # contatado), independente do canal.
        cur.execute("""CREATE TABLE IF NOT EXISTS campanha_envios (
            id SERIAL PRIMARY KEY,
            campanha_id INTEGER NOT NULL REFERENCES campanhas(id) ON DELETE CASCADE,
            cnpj VARCHAR(18) NOT NULL,
            canal VARCHAR(20) NOT NULL,
            status VARCHAR(30) DEFAULT 'enviado',
            criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            UNIQUE (campanha_id, cnpj)
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_campanha_envios_campanha ON campanha_envios(campanha_id)")
        # Ritmo do Disparar: quando a campanha de apoio pode soltar a proxima
        # rodada (10 por vez, com folga aleatoria de 11 a 12 minutos).
        cur.execute("ALTER TABLE campanhas ADD COLUMN IF NOT EXISTS proximo_lote_em TIMESTAMP WITH TIME ZONE")
        # Situacao de um contato que tira ele do follow-up: respondeu, ou nao
        # tem interesse. Por empresa -- o mesmo CNPJ pode estar em duas carteiras.
        cur.execute("""CREATE TABLE IF NOT EXISTS contato_situacao (
            organizacao_id INTEGER NOT NULL REFERENCES organizacoes(id) ON DELETE CASCADE,
            cnpj VARCHAR(18) NOT NULL,
            situacao VARCHAR(30) NOT NULL,
            por VARCHAR(50),
            atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (organizacao_id, cnpj)
        )""")
        # Quem a equipe ja' chamou no WhatsApp (manual) ou descobriu que nao tem WhatsApp.
        cur.execute("""CREATE TABLE IF NOT EXISTS contato_whatsapp (
            organizacao_id INTEGER NOT NULL REFERENCES organizacoes(id) ON DELETE CASCADE,
            cnpj VARCHAR(18) NOT NULL,
            status VARCHAR(20) NOT NULL,
            por VARCHAR(50),
            atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (organizacao_id, cnpj)
        )""")
        cur.execute("CREATE TABLE IF NOT EXISTS emails_enviados (id SERIAL PRIMARY KEY, campaign_id INTEGER, cnpj VARCHAR(18) NOT NULL, email_destino VARCHAR(255) NOT NULL, assunto VARCHAR(200), status VARCHAR(50) DEFAULT 'pendente', erro TEXT, sequencia_passo INTEGER DEFAULT 0, enviado_em TIMESTAMP WITH TIME ZONE, aberto_em TIMESTAMP WITH TIME ZONE, criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW())")
        # Eventos do provedor: status='enviado' so diz que o SMTP aceitou.
        cur.execute("ALTER TABLE emails_enviados ADD COLUMN IF NOT EXISTS message_id VARCHAR(255)")
        cur.execute("ALTER TABLE emails_enviados ADD COLUMN IF NOT EXISTS entregue_em TIMESTAMP WITH TIME ZONE")
        cur.execute("ALTER TABLE emails_enviados ADD COLUMN IF NOT EXISTS clicado_em TIMESTAMP WITH TIME ZONE")
        cur.execute("ALTER TABLE emails_enviados ADD COLUMN IF NOT EXISTS cliques INTEGER DEFAULT 0")
        cur.execute("ALTER TABLE emails_enviados ADD COLUMN IF NOT EXISTS ultimo_link TEXT")
        # Qual MODELO de e-mail cada lead recebeu: base do teste de abordagens.
        # Em campanha_envios fica o modelo SORTEADO na hora de entrar na fila.
        cur.execute("ALTER TABLE emails_enviados ADD COLUMN IF NOT EXISTS template_id INTEGER")
        cur.execute("ALTER TABLE campanha_envios ADD COLUMN IF NOT EXISTS template_id INTEGER")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_emails_enviados_message_id ON emails_enviados (message_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_emails_enviados_destino ON emails_enviados (email_destino, criado_em DESC)")
        cur.execute("CREATE TABLE IF NOT EXISTS notificacoes (id SERIAL PRIMARY KEY, tipo VARCHAR(50) NOT NULL, titulo VARCHAR(200) NOT NULL, mensagem TEXT, cnpj VARCHAR(18), user_id VARCHAR(50), lida BOOLEAN DEFAULT FALSE, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW())")        
        cur.execute("CREATE TABLE IF NOT EXISTS audit_log (id BIGSERIAL PRIMARY KEY, action VARCHAR(100) NOT NULL, user_id VARCHAR(50), ip_address INET, user_agent TEXT, resource_type VARCHAR(50), resource_id VARCHAR(100), details JSONB DEFAULT '{}'::jsonb, success BOOLEAN DEFAULT TRUE, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW())")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at DESC)")
        cur.execute("CREATE TABLE IF NOT EXISTS login_attempts (id BIGSERIAL PRIMARY KEY, username VARCHAR(50) NOT NULL, ip_address INET, success BOOLEAN DEFAULT FALSE, attempted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW())")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_username ON login_attempts(username)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts(ip_address)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_time ON login_attempts(attempted_at DESC)")
        # Metadata do pipeline de ETL (mes RF, trimestre PGFN, ultima sincronizacao,
        # contagens) -- tambem criada por database_config.py::ensure_app_tables no
        # lado do script de sincronizacao; criada aqui tambem pra API sempre
        # conseguir ler (retornando vazio) mesmo que o pipeline nunca tenha rodado.
        cur.execute("CREATE TABLE IF NOT EXISTS pipeline_metadata (chave VARCHAR(100) PRIMARY KEY, valor TEXT, atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW())")
        # Configuracoes gerais da aplicacao (regras do CRM/Monitor, etc.) --
        # mesmo esquema de chave-valor do pipeline_metadata, mas para
        # ajustes feitos pelo usuario pela tela de Configuracoes.
        cur.execute("CREATE TABLE IF NOT EXISTS app_config (chave VARCHAR(100) PRIMARY KEY, valor TEXT, atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW())")
        # Push subscriptions (PWA / Web Push): um registro por navegador/
        # celular que ativou avisos. Sem FK pra organizacoes de proposito:
        # esta funcao roda ANTES de _ensure_multiempresa no primeiro boot
        # (tabela ainda nao existe), e FK quebraria a criacao.
        ensure_push_tables()
        # Tabelas de lookup dos dados do ETL (municipios: cod->nome; cnaes:
        # codigo->descricao da atividade). Criadas aqui (vazias) pra os JOINs
        # dos endpoints de empresas/analytics nunca quebrarem, mesmo antes do
        # primeiro sync. O scripts/sync_data_to_db.py recria com os dados
        # reais (to_sql if_exists="replace") quando o pipeline roda.
        cur.execute("CREATE TABLE IF NOT EXISTS municipios (cod_municipio VARCHAR(10) PRIMARY KEY, nome_municipio VARCHAR(200))")
        cur.execute("CREATE TABLE IF NOT EXISTS cnaes (codigo_cnae VARCHAR(10) PRIMARY KEY, descricao_cnae VARCHAR(300))")
        # empresas_potencial: REMOVIDA em 2026-09 (DROP TABLE em prod; ver
        # CHECKPOINT). Nao recriar aqui -- o boot nao deve ressuscitar a tabela.
        # Tabela de lotes de leads (criacao de lotes com filtros, etc.)
        cur.execute("""CREATE TABLE IF NOT EXISTS lotes_leads (
            id SERIAL PRIMARY KEY,
            organizacao_id INTEGER NOT NULL REFERENCES organizacoes(id) ON DELETE CASCADE,
            nome VARCHAR(200) NOT NULL,
            filtros JSONB NOT NULL DEFAULT '{}'::jsonb,
            total_encontrado INTEGER DEFAULT 0,
            criado_por VARCHAR(50),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lotes_leads_org ON lotes_leads(organizacao_id)")
        # Composicao do lote, fixada na criacao. Sem isto "quem esta neste
        # lote" so existia como filtro reavaliado a cada envio -- o conteudo
        # mudava a cada recarga da base.
        cur.execute("""CREATE TABLE IF NOT EXISTS lote_empresas (
            id BIGSERIAL PRIMARY KEY,
            lote_id INTEGER NOT NULL REFERENCES lotes_leads(id) ON DELETE CASCADE,
            cnpj VARCHAR(18) NOT NULL,
            email VARCHAR(255),
            telefone VARCHAR(30),
            razao_social VARCHAR(300),
            -- email | whatsapp (sem e-mail, com fone) | sem_contato
            canal VARCHAR(20) NOT NULL DEFAULT 'email',
            bloco INTEGER NOT NULL DEFAULT 1,
            status VARCHAR(30) NOT NULL DEFAULT 'pendente',
            enviado_em TIMESTAMP WITH TIME ZONE,
            UNIQUE (lote_id, cnpj)
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lote_empresas_lote ON lote_empresas(lote_id, canal, bloco)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lote_empresas_status ON lote_empresas(lote_id, status)")
        # Template por bloco: permite mensagem diferente em cada fatia do
        # mesmo lote e comparar resposta.
        cur.execute("""CREATE TABLE IF NOT EXISTS lote_blocos (
            id BIGSERIAL PRIMARY KEY,
            lote_id INTEGER NOT NULL REFERENCES lotes_leads(id) ON DELETE CASCADE,
            canal VARCHAR(20) NOT NULL DEFAULT 'email',
            bloco INTEGER NOT NULL,
            template_id INTEGER,
            status VARCHAR(30) NOT NULL DEFAULT 'pendente',
            campanha_id INTEGER,
            UNIQUE (lote_id, canal, bloco)
        )""")
        conn.commit(); cur.close()
    _ensure_enriquecimento_table()
    _ensure_multiempresa()


def ensure_push_tables():
    """Cria a tabela de inscricoes push (idempotente). Separada do
    ensure_tables pra dar pra chamar isolada nos testes."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS push_subscriptions (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) NOT NULL,
            organizacao_id INTEGER,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            user_agent VARCHAR(255),
            criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_push_subs_org ON push_subscriptions(organizacao_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_push_subs_user ON push_subscriptions(username)")
        conn.commit(); cur.close()


def _ensure_multiempresa():
    """Multi-tenant (empresas Alfa / Beta). Fase aditiva: cria as tabelas de
    organizacao, o vinculo usuario<->empresa e a config SMTP por empresa,
    adiciona a coluna organizacao_id (nullable) nas tabelas de controle e faz
    a migracao (tudo que ja existe vira Alfa). NAO mexe no UNIQUE do CRM nem no
    scoping das queries -- isso vem junto com o codigo que depende, para esta
    etapa nao quebrar nada. Idempotente: roda a cada boot sem efeito colateral.
    Ver plano multi-empresa.

    Envolvido em try/except: se algo falhar, apenas loga e segue (o app nao
    cai por causa da migracao) -- como e idempotente, re-tenta no proximo boot."""
    import os
    try:
        _run_ensure_multiempresa(os)
    except Exception as e:
        log.error(f"Falha na migracao multi-empresa (sera retentada no proximo boot): {e}")


def _run_ensure_multiempresa(os):
    with get_conn() as conn:
        cur = conn.cursor()

        # Tabelas de organizacao
        cur.execute("""CREATE TABLE IF NOT EXISTS organizacoes (
            id SERIAL PRIMARY KEY,
            nome VARCHAR(120) NOT NULL,
            slug VARCHAR(60) UNIQUE NOT NULL,
            ativo BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS usuario_organizacoes (
            user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
            organizacao_id INTEGER NOT NULL REFERENCES organizacoes(id) ON DELETE CASCADE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (user_id, organizacao_id)
        )""")
        # Papel do usuario DENTRO dessa empresa (hierarquia: Operador Global
        # [app_users.is_admin] > admin [por empresa] > membro > visitante).
        # 'admin' aqui e' escopado a ESSA organizacao -- diferente do
        # is_admin global, que da acesso a todas. 'visitante' e' bloqueado
        # em quase tudo pelo VisitanteMiddleware (main.py) e ve dados
        # mascarados nas Empresas -- pensado pra dar acesso a alguem de
        # fora (ex.: recrutador) sem expor dado real de cliente.
        cur.execute("ALTER TABLE usuario_organizacoes ADD COLUMN IF NOT EXISTS papel VARCHAR(20) DEFAULT 'membro'")
        cur.execute("""CREATE TABLE IF NOT EXISTS org_smtp_config (
            organizacao_id INTEGER PRIMARY KEY REFERENCES organizacoes(id) ON DELETE CASCADE,
            smtp_host VARCHAR(200),
            smtp_port INTEGER DEFAULT 587,
            smtp_username VARCHAR(200),
            smtp_password VARCHAR(255),
            smtp_use_tls BOOLEAN DEFAULT TRUE,
            email_from VARCHAR(255),
            email_from_name VARCHAR(120),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""")
        # Assinatura de e-mail por empresa: HTML livre (com {{logo}}) + logo.
        cur.execute("ALTER TABLE org_smtp_config ADD COLUMN IF NOT EXISTS assinatura_html TEXT")
        cur.execute("ALTER TABLE org_smtp_config ADD COLUMN IF NOT EXISTS logo_data BYTEA")
        cur.execute("ALTER TABLE org_smtp_config ADD COLUMN IF NOT EXISTS logo_mime VARCHAR(50)")

        # Identidade visual da empresa
        # Estava so' dentro do HTML de alguns templates, o que obrigava a
        # copiar cor na mao para cada modelo novo (e a errar a cor).
        for coluna, tipo in (("cor_principal", "VARCHAR(9)"), ("cor_texto", "VARCHAR(9)"),
                             ("cor_fundo", "VARCHAR(9)"), ("fonte", "VARCHAR(120)"),
                             ("selo", "VARCHAR(8)")):
            cur.execute(f"ALTER TABLE org_smtp_config ADD COLUMN IF NOT EXISTS {coluna} {tipo}")

        # Seed com o que cada empresa ja' usava nos modelos dela. Com
        # parametro, nao literal: o nome da fonte da Beta tem aspas dentro.
        cur.execute("""INSERT INTO org_smtp_config (organizacao_id) SELECT id FROM organizacoes
                       ON CONFLICT (organizacao_id) DO NOTHING""")
        for slug, ident in (
            ("alfa", ("#112A52", "#3A4556", "#F1F3F6", "Arial,Helvetica,sans-serif", "Alfa")),
            ("beta", ("#C5FF3D", "#E8E8E8", "#0A0A0A", "'Space Grotesk',Helvetica,sans-serif", "{ }")),
        ):
            cur.execute(
                """UPDATE org_smtp_config c SET
                     cor_principal = COALESCE(c.cor_principal, %s),
                     cor_texto     = COALESCE(c.cor_texto, %s),
                     cor_fundo     = COALESCE(c.cor_fundo, %s),
                     fonte         = COALESCE(c.fonte, %s),
                     selo          = COALESCE(c.selo, %s)
                   FROM organizacoes o
                  WHERE o.id = c.organizacao_id AND o.slug = %s""",
                (*ident, slug),
            )
        # Conta do Gmail conectada pelo sistema (botao "Conectar Gmail"): a
        # autorizacao fica junto do remetente que ela autoriza. Cifrada.
        cur.execute("ALTER TABLE org_smtp_config ADD COLUMN IF NOT EXISTS gmail_conta VARCHAR(255)")
        cur.execute("ALTER TABLE org_smtp_config ADD COLUMN IF NOT EXISTS gmail_refresh_token TEXT")

        # E-mail e' INDIVIDUAL: quem dispara assina com o proprio endereco.
        # A config da empresa (org_smtp_config) continua sendo o padrao -- o
        # usuario so' precisa preencher o que for dele. Na pratica quase
        # sempre e' so' o remetente e a assinatura, aproveitando o servidor
        # da empresa; por isso servidor/usuario/senha sao opcionais aqui.
        cur.execute("""CREATE TABLE IF NOT EXISTS usuario_smtp_config (
            user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
            organizacao_id INTEGER NOT NULL REFERENCES organizacoes(id) ON DELETE CASCADE,
            smtp_host VARCHAR(200),
            smtp_port INTEGER,
            smtp_username VARCHAR(200),
            smtp_password VARCHAR(255),
            smtp_use_tls BOOLEAN,
            email_from VARCHAR(255),
            email_from_name VARCHAR(120),
            assinatura_html TEXT,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (user_id, organizacao_id)
        )""")
        cur.execute("ALTER TABLE usuario_smtp_config ADD COLUMN IF NOT EXISTS gmail_conta VARCHAR(255)")
        cur.execute("ALTER TABLE usuario_smtp_config ADD COLUMN IF NOT EXISTS gmail_refresh_token TEXT")

        # Filtro do painel de Empresas fixado pela pessoa: UM por usuario em
        # cada empresa -- salvar de novo sobrescreve o anterior (upsert no
        # PRIMARY KEY), nao acumula historico. Serve de ponto de retorno: a
        # tela restaura de la' em qualquer maquina, diferente do cache de
        # "ultima busca" do navegador, que o proprio ato de mexer num filtro
        # ja sobrescreve. atualizado_em e' mostrado no topo do painel.
        cur.execute("""CREATE TABLE IF NOT EXISTS filtro_salvo (
            username VARCHAR(50) NOT NULL,
            organizacao_id INTEGER NOT NULL REFERENCES organizacoes(id) ON DELETE CASCADE,
            filtros JSONB NOT NULL DEFAULT '{}'::jsonb,
            atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (username, organizacao_id)
        )""")

        # Seed das empresas (idempotente por slug)
        cur.execute("INSERT INTO organizacoes (nome, slug) VALUES ('Alfa Consultoria', 'alfa') ON CONFLICT (slug) DO NOTHING")
        cur.execute("INSERT INTO organizacoes (nome, slug) VALUES ('Beta Software', 'beta') ON CONFLICT (slug) DO NOTHING")
        cur.execute("INSERT INTO organizacoes (nome, slug) VALUES ('Gama Servicos', 'gama') ON CONFLICT (slug) DO NOTHING")

        # o admin da instalacao tem acesso a todas
        cur.execute("""INSERT INTO usuario_organizacoes (user_id, organizacao_id)
            SELECT u.id, o.id FROM app_users u CROSS JOIN organizacoes o
            WHERE u.username = 'admin'
            ON CONFLICT DO NOTHING""")

        # O operador atende somente a Gama (admin de la' dentro).
        cur.execute("""INSERT INTO usuario_organizacoes (user_id, organizacao_id, papel)
            SELECT u.id, o.id, 'admin' FROM app_users u CROSS JOIN organizacoes o
            WHERE u.username = 'operador' AND o.slug = 'gama'
            ON CONFLICT DO NOTHING""")

        # Coluna organizacao_id (nullable) + indice nas tabelas de controle
        for tabela in ("crm", "email_templates", "campanhas", "emails_enviados", "notificacoes"):
            cur.execute(f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS organizacao_id INTEGER")
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{tabela}_org ON {tabela}(organizacao_id)")

        # Migracao: tudo que ja existe vira Alfa
        for tabela in ("crm", "email_templates", "campanhas", "emails_enviados", "notificacoes"):
            cur.execute(
                f"UPDATE {tabela} SET organizacao_id = "
                f"(SELECT id FROM organizacoes WHERE slug = 'alfa') "
                f"WHERE organizacao_id IS NULL"
            )

        # CRM com UNIQUE(empresa, cnpj): o mesmo CNPJ pode estar no CRM de
        # mais de uma empresa, cada uma com o seu acompanhamento. Idempotente,
        # e o ON CONFLICT de create_or_update_crm depende deste indice.
        cur.execute("ALTER TABLE crm DROP CONSTRAINT IF EXISTS crm_cnpj_key")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_org_cnpj ON crm(organizacao_id, cnpj)")

        # CRM: classificacao de perfil (ideal / possivel / fora do perfil)
        # Criado automaticamente no boot; nao perde dados nem quebra nada.
        cur.execute("ALTER TABLE crm ADD COLUMN IF NOT EXISTS classificacao VARCHAR(30)")
        cur.execute("ALTER TABLE crm ADD COLUMN IF NOT EXISTS motivo VARCHAR(255)")
        cur.execute("ALTER TABLE crm ADD COLUMN IF NOT EXISTS parceiro BOOLEAN DEFAULT FALSE")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_classificacao ON crm(classificacao)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_parceiro ON crm(parceiro)")

        # Migra o SMTP global (.env) para a Alfa como valor inicial
        smtp_host = os.getenv("SMTP_HOST", "").strip()
        if smtp_host:
            cur.execute(
                """INSERT INTO org_smtp_config
                     (organizacao_id, smtp_host, smtp_port, smtp_username,
                      smtp_password, smtp_use_tls, email_from, email_from_name)
                   SELECT o.id, %s, %s, %s, %s, %s, %s, %s
                     FROM organizacoes o WHERE o.slug = 'alfa'
                   ON CONFLICT (organizacao_id) DO NOTHING""",
                (
                    smtp_host,
                    int(os.getenv("SMTP_PORT", "587") or "587"),
                    os.getenv("SMTP_USERNAME", "").strip(),
                    os.getenv("SMTP_PASSWORD", "").strip(),
                    os.getenv("SMTP_USE_TLS", "true").lower() == "true",
                    os.getenv("EMAIL_FROM", "").strip(),
                    os.getenv("EMAIL_FROM_NAME", "").strip(),
                ),
            )

        # Tabela de integracoes externas (Twilio)
        cur.execute(
            """CREATE TABLE IF NOT EXISTS integracao_configs (
                id SERIAL PRIMARY KEY,
                key VARCHAR(100) UNIQUE NOT NULL,
                value TEXT,
                descricao VARCHAR(255),
                ativo BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )"""
        )

        # --- WhatsApp (Twilio): historico de mensagens enviadas/recebidas.
        # organizacao_id fica nullable pra nao quebrar mensagens antigas sem
        # org resolvida; cnpj e' um best-effort match pelo telefone (pode ficar
        # NULL se nao achar nenhuma empresa com esse numero).
        cur.execute(
            """CREATE TABLE IF NOT EXISTS whatsapp_mensagens (
                id SERIAL PRIMARY KEY,
                organizacao_id INTEGER REFERENCES organizacoes(id) ON DELETE SET NULL,
                cnpj VARCHAR(18),
                telefone VARCHAR(20) NOT NULL,
                direcao VARCHAR(10) NOT NULL,
                corpo TEXT,
                status VARCHAR(30) DEFAULT 'recebida',
                twilio_sid VARCHAR(64),
                lida BOOLEAN DEFAULT FALSE,
                criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )"""
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_whatsapp_msg_telefone ON whatsapp_mensagens(telefone)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_whatsapp_msg_criado ON whatsapp_mensagens(criado_em DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_whatsapp_msg_org ON whatsapp_mensagens(organizacao_id)")

        # Credencial de integracao por EMPRESA. Cada uma tem o proprio numero
        # de WhatsApp (e o proprio Twilio), entao a chave passa a ser
        # (empresa, key) em vez de key global. As linhas antigas ficam com
        # organizacao_id NULL e servem de fallback pra quem ainda nao
        # configurou -- por isso o UNIQUE antigo em key precisa sair.
        cur.execute("ALTER TABLE integracao_configs ADD COLUMN IF NOT EXISTS organizacao_id INTEGER REFERENCES organizacoes(id) ON DELETE CASCADE")
        cur.execute("""DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'integracao_configs_key_key') THEN
                    ALTER TABLE integracao_configs DROP CONSTRAINT integracao_configs_key_key;
                END IF;
            END $$;""")
        cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_integracao_org_key
                       ON integracao_configs (COALESCE(organizacao_id, 0), key)""")

        # Atividades/tarefas do CRM -- atribuiveis a um usuario da mesma
        # organizacao (ex.: os socios da SVYP dividindo follow-ups entre si).
        # cnpj e' OPCIONAL: boa parte das tarefas entre socios nao tem empresa
        # nenhuma envolvida ("revisar proposta", "ligar pro contador"), e
        # exigir empresa obrigava a entrar num cliente antes de criar tarefa.
        cur.execute("""CREATE TABLE IF NOT EXISTS crm_atividades (
            id SERIAL PRIMARY KEY,
            organizacao_id INTEGER REFERENCES organizacoes(id) ON DELETE CASCADE,
            cnpj VARCHAR(18),
            titulo VARCHAR(200) NOT NULL,
            tipo VARCHAR(30) DEFAULT 'tarefa',
            descricao TEXT,
            responsavel_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
            prazo DATE,
            status VARCHAR(20) DEFAULT 'pendente',
            criado_por VARCHAR(50),
            criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            concluido_em TIMESTAMP WITH TIME ZONE
        )""")
        # A tabela pode ja existir com cnpj NOT NULL (versao anterior).
        cur.execute("ALTER TABLE crm_atividades ALTER COLUMN cnpj DROP NOT NULL")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_atividades_cnpj ON crm_atividades(cnpj)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_atividades_responsavel ON crm_atividades(responsavel_user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_atividades_org ON crm_atividades(organizacao_id)")

        # Historico da atividade: comentario escrito pelo usuario E registro
        # automatico de mudanca de status/prazo ("Operador moveu para Em
        # andamento", "Operador mudou o prazo para 20/09"). Uma linha por
        # evento -- e' o acompanhamento da tarefa, nao da empresa.
        cur.execute("""CREATE TABLE IF NOT EXISTS crm_atividade_historico (
            id SERIAL PRIMARY KEY,
            atividade_id INTEGER NOT NULL REFERENCES crm_atividades(id) ON DELETE CASCADE,
            tipo VARCHAR(20) NOT NULL DEFAULT 'comentario',
            texto TEXT,
            de VARCHAR(50),
            para VARCHAR(50),
            autor VARCHAR(50),
            criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_atv_hist_atividade ON crm_atividade_historico(atividade_id)")

        # Anexos da atividade (proposta em PDF, print, contrato em docx...).
        # Bytes no proprio banco, mesmo caminho da imagem de template: evita
        # depender de storage externo e mantem o anexo sob a mesma regra de
        # isolamento por empresa da atividade que o carrega.
        cur.execute("""CREATE TABLE IF NOT EXISTS crm_atividade_anexos (
            id SERIAL PRIMARY KEY,
            atividade_id INTEGER NOT NULL REFERENCES crm_atividades(id) ON DELETE CASCADE,
            nome VARCHAR(255) NOT NULL,
            mime VARCHAR(120),
            tamanho INTEGER,
            conteudo BYTEA NOT NULL,
            enviado_por VARCHAR(50),
            criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_atv_anexo_atividade ON crm_atividade_anexos(atividade_id)")

        # Gastos por empresa. Registro simples de despesa ja' realizada.
        # Nada e' apagado de verdade: excluir marca removido_em, entao o
        # historico continua inteiro e da' pra restaurar -- "nada pode se
        # perder" e' requisito, nao detalhe de implementacao.
        cur.execute("""CREATE TABLE IF NOT EXISTS gastos (
            id SERIAL PRIMARY KEY,
            organizacao_id INTEGER NOT NULL REFERENCES organizacoes(id) ON DELETE CASCADE,
            descricao VARCHAR(255) NOT NULL,
            valor NUMERIC(12,2) NOT NULL,
            data DATE NOT NULL DEFAULT CURRENT_DATE,
            categoria VARCHAR(40) DEFAULT 'outros',
            forma_pagamento VARCHAR(30),
            observacao TEXT,
            criado_por VARCHAR(50),
            criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            removido_em TIMESTAMP WITH TIME ZONE,
            removido_por VARCHAR(50)
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_gastos_org_data ON gastos(organizacao_id, data DESC)")

        # Propostas comerciais, por empresa. `campos` guarda o que a pessoa
        # preencheu e `conteudo` o que saiu -- separados de proposito: com os
        # campos originais da' pra regerar ou ajustar sem redigitar tudo.
        cur.execute("""CREATE TABLE IF NOT EXISTS propostas (
            id SERIAL PRIMARY KEY,
            organizacao_id INTEGER NOT NULL REFERENCES organizacoes(id) ON DELETE CASCADE,
            cliente VARCHAR(200) NOT NULL,
            titulo VARCHAR(255),
            campos JSONB NOT NULL DEFAULT '{}'::jsonb,
            conteudo JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(20) DEFAULT 'rascunho',
            criado_por VARCHAR(50),
            criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_propostas_org ON propostas(organizacao_id, criado_em DESC)")

        # De onde a empresa le' a base de prospeccao:
        #   'receita'  -> dados_empresas (a base publica da Receita Federal)
        #   'carteira' -> empresas_carteira, a lista propria daquela empresa
        # Nao e' bloqueio de tela: as telas sao as mesmas, muda a FONTE.
        cur.execute("ALTER TABLE organizacoes ADD COLUMN IF NOT EXISTS escopo_base VARCHAR(20) DEFAULT 'receita'")
        # Dias ate' o follow-up, por empresa. NULL = o padrao do codigo (5).
        # E' por empresa porque a cadencia que um dominio suporta depende da
        # reputacao dele: dominio com Workspace aguenta o que outro nao
        # aguenta.
        cur.execute("ALTER TABLE organizacoes ADD COLUMN IF NOT EXISTS dias_followup INTEGER")
        # Teto por clique, por empresa. NULL = o padrao do ambiente.
        cur.execute("ALTER TABLE organizacoes ADD COLUMN IF NOT EXISTS max_por_clique INTEGER")
        # Teto diario de e-mail DESTA empresa. NULL = so' o teto da conta.
        #
        # EMAIL_LIMITE_DIARIO vale para a caixa inteira, que e' compartilhada.
        # O teto por empresa permite que um dominio em warm-up envie pouco sem
        # frear os outros, e que um dominio maduro use a folga. O limite
        # efetivo e' o menor dos dois.
        cur.execute("ALTER TABLE organizacoes ADD COLUMN IF NOT EXISTS email_limite_diario INTEGER")
        # Seed de uma vez so': a marca em app_config registra que ja'
        # aconteceu. Sem ela o UPDATE rodaria a cada boot e desfaria, no
        # deploy seguinte, o que o admin tivesse mudado pela tela. Depois do
        # seed quem manda e' o banco (PUT /organizacoes/{id}).
        cur.execute("INSERT INTO app_config (chave, valor) VALUES ('seed_escopo_gama', NOW()::text) "
                    "ON CONFLICT (chave) DO NOTHING")
        if cur.rowcount:
            cur.execute("UPDATE organizacoes SET escopo_base = 'carteira' WHERE slug = 'gama'")

        # Carteira propria da empresa. Guarda os campos por conta propria (nao
        # e' so' uma lista de CNPJs apontando pra dados_empresas) porque o
        # cliente carregado pode nem existir na base da Receita que temos --
        # e porque o ETL recria dados_empresas do zero a cada carga, entao
        # qualquer coisa gravada la' seria perdida.
        cur.execute("""CREATE TABLE IF NOT EXISTS empresas_carteira (
            id SERIAL PRIMARY KEY,
            organizacao_id INTEGER NOT NULL REFERENCES organizacoes(id) ON DELETE CASCADE,
            cnpj_completo VARCHAR(14) NOT NULL,
            razao_social VARCHAR(255),
            nome_fantasia VARCHAR(255),
            municipio VARCHAR(120),
            uf VARCHAR(2),
            email VARCHAR(255),
            contato_fone VARCHAR(60),
            cnae_principal VARCHAR(10),
            cnae_descricao VARCHAR(255),
            porte_nome VARCHAR(40),
            capital_social NUMERIC(16,2),
            divida_total NUMERIC(16,2),
            categoria VARCHAR(60),
            situacao VARCHAR(30),
            origem VARCHAR(40),
            observacao TEXT,
            criado_por VARCHAR(50),
            criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            UNIQUE (organizacao_id, cnpj_completo)
        )""")
        # E-mail usado por MAIS DE UM contato da carteira: quase sempre e' do contador
        # ou de um servico de abertura de empresa, nao do dono. Fica fora do envio.
        cur.execute("ALTER TABLE empresas_carteira ADD COLUMN IF NOT EXISTS email_compartilhado BOOLEAN DEFAULT FALSE")
        # Data de abertura do CNPJ. A fila de primeiro contato sai dos mais recentes para
        # os mais antigos: quem acabou de formalizar o negocio e' quem mais precisa de site.
        cur.execute("ALTER TABLE empresas_carteira ADD COLUMN IF NOT EXISTS data_fundacao DATE")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_carteira_org ON empresas_carteira(organizacao_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_carteira_categoria ON empresas_carteira(organizacao_id, categoria)")

        # Lista de envio montada a mao: planilha, selecao na tela ou digitada.
        # A campanha parte de um filtro sobre a base ou desta lista, quando e'
        # preciso escolher destinatario a destinatario.
        cur.execute("""CREATE TABLE IF NOT EXISTS campanha_destinatarios (
            id SERIAL PRIMARY KEY,
            campanha_id INTEGER NOT NULL REFERENCES campanhas(id) ON DELETE CASCADE,
            email VARCHAR(255) NOT NULL,
            cnpj VARCHAR(14),
            razao_social VARCHAR(255),
            municipio VARCHAR(120),
            nome_socio VARCHAR(255),
            origem VARCHAR(30) DEFAULT 'manual',
            criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            UNIQUE (campanha_id, email)
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_camp_dest ON campanha_destinatarios(campanha_id)")
        # 'filtro' (padrao, comportamento antigo) ou 'lista'
        cur.execute("ALTER TABLE campanhas ADD COLUMN IF NOT EXISTS origem_destinatarios VARCHAR(10) DEFAULT 'filtro'")

        # Descadastro de e-mail (LGPD/opt-out) -- GLOBAL, nao por empresa: se
        # alguem pede pra nao receber mais, isso vale pra Alfa e Beta, nao so'
        # pra quem mandou o e-mail que ela descadastrou. Toda campanha de
        # e-mail tem que respeitar isso (ver mailer/service.py) -- e' regra
        # do negocio, nao op'cao de template.
        cur.execute("""CREATE TABLE IF NOT EXISTS emails_descadastrados (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL UNIQUE,
            cnpj VARCHAR(18),
            motivo TEXT,
            criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )""")

        conn.commit(); cur.close()


def _ensure_enriquecimento_table():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS enriquecimento_contatos (
            id SERIAL PRIMARY KEY,
            cnpj VARCHAR(18) NOT NULL,
            tipo_alvo VARCHAR(20) NOT NULL,
            nome_alvo VARCHAR(255),
            campo VARCHAR(30) NOT NULL,
            valor TEXT,
            fonte_url TEXT,
            fonte_titulo TEXT,
            base_legal VARCHAR(50) NOT NULL DEFAULT \'legitimo_interesse_dados_publicos\',
            coletado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            coletado_por VARCHAR(100),
            removido_em TIMESTAMP WITH TIME ZONE
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_enriquecimento_cnpj ON enriquecimento_contatos(cnpj)")
        # Contato enriquecido e' trabalho de prospeccao de UMA empresa (quem
        # pesquisou e achou o telefone). Sem esta coluna, o que a Alfa
        # levantou aparecia pra Beta no mesmo CNPJ.
        cur.execute("ALTER TABLE enriquecimento_contatos ADD COLUMN IF NOT EXISTS organizacao_id INTEGER")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_enriquecimento_org ON enriquecimento_contatos(cnpj, organizacao_id)")
        # Contato enriquecido e' trabalho de prospeccao de UMA empresa (quem
        # pesquisou e achou o telefone). Sem esta coluna, o que a Alfa
        # levantou aparecia pra Beta no mesmo CNPJ.
        cur.execute("ALTER TABLE enriquecimento_contatos ADD COLUMN IF NOT EXISTS organizacao_id INTEGER")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_enriquecimento_org ON enriquecimento_contatos(cnpj, organizacao_id)")
        conn.commit(); cur.close()

def check_health():
    try:
        with get_conn() as conn:
            cur = conn.cursor(); cur.execute("SELECT 1"); cur.close(); return True
    except: return False

ensure_tables_exist = ensure_tables
check_database_health = check_health
get_db_cursor = get_cur


# TIPOS DE COLUNA (CACHE)
#
# A expressao certa para filtrar uma coluna depende do tipo real dela. Com
# NUMERIC, `COALESCE(col,0)` usa o indice; com texto, `NULLIF(col::text,
# '')::numeric` forca o planner a converter linha a linha e o indice e'
# ignorado -- a diferenca aparece nas consultas por faixa de valor.
#
# Uma consulta ao information_schema por processo/hora. Sem banco ou sem
# tabela retorna {}, e o chamador usa a expressao generica.
import time as _time
import threading as _threading

_TIPOS_CACHE: dict = {}
_TIPOS_TS: float = 0.0
_TIPOS_LOCK = _threading.Lock()
_TIPOS_TTL = 3600.0


def get_tipos_dados_empresas() -> dict:
    """{COLUNA: data_type} de dados_empresas (ex.: {'DIVIDA_TOTAL': 'numeric'})."""
    global _TIPOS_CACHE, _TIPOS_TS
    agora = _time.monotonic()
    with _TIPOS_LOCK:
        if _TIPOS_CACHE and agora - _TIPOS_TS < _TIPOS_TTL:
            return _TIPOS_CACHE
    try:
        with get_cur() as cur:
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'dados_empresas'"
            )
            tipos = {r["column_name"]: r["data_type"] for r in cur.fetchall()}
    except Exception as e:
        log.warning(f"get_tipos_dados_empresas falhou (usa expressao legada): {e}")
        return {}
    with _TIPOS_LOCK:
        _TIPOS_CACHE = tipos
        _TIPOS_TS = agora
    return tipos


def expr_numerica(coluna: str, tipos: dict | None = None) -> str:
    """Expressao SQL que zera nulos de uma coluna numerica-ou-texto.
    NUMERIC (prod atual) -> COALESCE direto, amigavel a indice.
    Qualquer outra coisa (TEXT legado, tabela ausente) -> cast defensivo."""
    if tipos is None:
        tipos = get_tipos_dados_empresas()
    if tipos.get(coluna) == "numeric":
        return f'COALESCE(e."{coluna}", 0)'
    return f'COALESCE(NULLIF(e."{coluna}"::text, \'\')::numeric, 0)'


def data_fundacao_is_date(tipos: dict | None = None) -> bool:
    if tipos is None:
        tipos = get_tipos_dados_empresas()
    return tipos.get("DATA_FUNDACAO") == "date"


def normalizar_data_param(valor: str) -> str:
    """YYYY-MM-DD ou YYYYMMDD -> YYYY-MM-DD (pro comparador ::date)."""
    digitos = "".join(c for c in str(valor) if c.isdigit())
    if len(digitos) == 8:
        return f"{digitos[:4]}-{digitos[4:6]}-{digitos[6:]}"
    return str(valor)[:10]
