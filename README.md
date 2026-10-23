# WhoDados — plataforma B2B de inteligência empresarial

[![CI](https://github.com/jklaveren/whodados/actions/workflows/ci.yml/badge.svg)](https://github.com/jklaveren/whodados/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Plataforma **multiempresa em produção** para prospecção e inteligência comercial sobre
os dados públicos da **Receita Federal**: investigação de sócios e grupos econômicos,
CRM, campanhas de e-mail e WhatsApp com rastreamento, e consulta em linguagem natural.

**FastAPI** + **PostgreSQL** no backend, **Next.js** no frontend, **Supabase** como banco,
ingestao por **BigQuery (GCP)**, deploy em **Render** e **Vercel**.

> **Em 30 segundos:** 151 rotas · 36 tabelas · 19 telas · 204 testes verdes ·
> isolamento multiempresa testado · LGPD com descadastro assinado por HMAC.

---

## O problema

Prospecção B2B no Brasil esbarra sempre nos mesmos três muros: a base pública da Receita
tem milhões de linhas mas nenhum contato utilizável; o contato que existe costuma ser do
contador, não do decisor; e quem dispara e-mail de domínio próprio queima a reputação do
domínio em uma semana se errar o ritmo.

O WhoDados resolve os três na mesma plataforma, e faz isso para **três empresas distintas
que nunca enxergam os dados uma da outra**.

## Arquitetura

```
Receita Federal (dados abertos)
          │  ETL em lote · BigQuery (GCP) ou download direto
          ▼
   ┌──────────────┐        ┌───────────────────────────┐
   │  PostgreSQL  │◀──────▶│  FastAPI (Render)         │
   │  (Supabase)  │        │  JWT · RBAC · rate limit  │
   │  36 tabelas  │        │  151 rotas · auditoria    │
   └──────────────┘        └─────────────┬─────────────┘
          ▲                              │
          │                    ┌─────────┴─────────┐
   Gmail API · Twilio          │  Next.js (Vercel) │
   (envio e WhatsApp)          │  19 telas · SSR   │
                               └───────────────────┘
```

Toda requisição carrega `X-Org-Id`. A resolução da empresa ativa acontece **em um lugar
só** (`auth/dependencies.py`), e qualquer escrita sem empresa declarada é recusada — não
há caminho que "adivinhe" a organização.

## Engenharia que vale olhar

| Tema | Onde | O quê |
|---|---|---|
| **Isolamento multiempresa** | `backend/auth/dependencies.py` | Empresa ativa resolvida num ponto único; escrita sem `X-Org-Id` é erro, não suposição |
| **Guarda de remetente** | `backend/mailer/service.py` | Empresa sem remetente próprio não envia. A checagem vive antes da escolha de transporte, para que transporte novo não escape dela |
| **LGPD** | `backend/endpoints_descadastro.py` | Descadastro em um clique, URL assinada com HMAC, sem sessão |
| **Rastreamento próprio** | `backend/mailer/rastreamento.py` | Pixel de abertura e redirect de clique assinados — sem depender do provedor, e sem virar open redirect |
| **Ritmo de disparo** | `backend/endpoints_campanhas.py` | Orçamento diário por empresa e lotes dimensionados pela janela restante, para proteger a reputação do domínio |
| **Segurança** | `backend/security/` | Auditoria, rate limit, cabeçalhos, modo visitante — documentado em [`SECURITY.md`](whodados/SECURITY.md) |
| **Camada de LLM** | `backend/nlp/`, `backend/agents/` | Pergunta em português vira filtro estruturado; agente de enriquecimento busca contato público; geração de proposta comercial |
| **Ingestao em nuvem** | `pipeline/pipeline_bigquery.py` | Carga via BigQuery publico (`basedosdados.br_me_cnpj`) com service account e cobranca por projeto, em vez de baixar os arquivos da Receita |
| **Testes** | `backend/tests/` | 204 testes, incluindo os de isolamento entre empresas |

## Números

| Métrica | Valor |
|---|---|
| Rotas HTTP | **151** |
| Tabelas | **36** (schema idempotente, criado no boot) |
| Telas | **19** |
| Testes | **204 passando** |
| Backend | ~15,6 mil linhas de Python |
| Empresas em produção | **3**, com dados mutuamente invisíveis |

## Como rodar

```bash
cp whodados/backend/.env.example whodados/backend/.env   # preencha as credenciais
pip install -r whodados/requirements.txt
python -m pytest whodados/backend/tests -q               # 204 testes

cd whodados/frontend && npm install && npm run dev        # http://localhost:3000
uvicorn backend.main:app --reload --app-dir whodados      # http://localhost:8000/docs
```

O schema nasce de `CREATE TABLE IF NOT EXISTS` em `backend/db/config.py`, executado a cada
boot — não há migrations, e tabela nova só existe depois do próximo deploy.

## Mapa do repositório

| Pasta | O quê |
|---|---|
| `whodados/backend/` | FastAPI — um arquivo `endpoints_*.py` por domínio |
| `whodados/backend/db/` | Schema completo e camada de acesso a dados |
| `whodados/backend/security/` | Auditoria, rate limit, cabeçalhos, visitante |
| `whodados/backend/mailer/` | Envio por Gmail API, rastreamento, validação |
| `whodados/backend/agents/`, `nlp/` | Consulta em linguagem natural e enriquecimento |
| `whodados/frontend/` | Next.js App Router, TypeScript, Tailwind |
| `whodados/pipeline/` | Carga da base pública |
| `whodados/infra/` | Terraform |
| `whodados/scripts/` | Administração, sincronização e autorização OAuth |

## Decisões técnicas

- **Sem migrations, schema idempotente.** Três ambientes e um time de uma pessoa: o custo
  de manter migrations superava o de recriar o schema a cada boot. A escolha tem preço —
  está anotada como tal, não como virtude.
- **Gmail API em vez de SMTP.** O Render bloqueia as portas 587 e 465. O caminho SMTP
  continua no código para ambiente local, mas o envio real nunca passa por ele.
- **Rastreamento próprio.** Abertura e clique por rota assinada com HMAC. Sem isso, a
  métrica fica refém do provedor de e-mail — e o redirect viraria open redirect no domínio.
- **Regra por empresa, nunca global.** Limite diário, dias de follow-up e remetente são
  por organização, e a guarda vive num ponto único por onde todo envio passa — repetir a
  checagem por caminho é o que deixa o caminho novo escapar.

## Limitações (e o que eu faria diferente)

- **Sem migrations.** Funciona para este porte; com mais de uma pessoa mexendo no schema,
  Alembic passa a valer o custo.
- **Banco no limite do plano gratuito** (500 MB). A base da Receita cabe raspando, e isso
  já custou lentidão em consulta.
- **Cobertura concentrada no backend.** O frontend é validado por `tsc` e build, não por
  testes de componente.
- **Rastreamento de clique não distingue cliques repetidos do mesmo destinatário** — o
  número é de cliques, não de pessoas.

## Autoria

**Jessica Van Klaveren** — Engenheira de Dados · Lakehouse, crédito e dados regulados.
Python · FastAPI · PostgreSQL · Next.js · Databricks · PySpark · dbt · LGPD.

[klaverenjv@gmail.com](mailto:klaverenjv@gmail.com) · [linkedin.com/in/jessicanolin](https://linkedin.com/in/jessicanolin) · São Leopoldo/RS
