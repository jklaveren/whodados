# 🚀 Guia de Deploy — WhoDados em Cloud

Este guia mostra como colocar o app inteiro na nuvem. Todo o código deste stack está em `whodados/`.

O resultado final é:
- **Frontend** rodando na Vercel (`whodados/frontend/`)
- **API** rodando na Render (`whodados/backend/`)
- **Banco** rodando no Supabase
- **Dados** atualizados via pipeline local (`whodados/pipeline/`)

---

## 1️⃣ Provisionar o Supabase (PostgreSQL)

1. Acesse [supabase.com](https://supabase.com) e crie uma conta (grátis)
2. Clique em **"New Project"**
3. Preencha:
   - **Name**: `whodados`
   - **Region**: `South America (São Paulo)`
4. Vá em **Settings → Database** e copie a **Connection String** (URI).

### Tabelas necessárias
As tabelas serão criadas automaticamente na primeira execução do ETL via:
```bash
DATABASE_URL="<sua-connection-string>" python whodados/scripts/sync_data_to_db.py
```

---

## 2️⃣ Deploy da API no Render.com

1. Acesse [render.com](https://render.com) → conecte GitHub
2. **"New" → "Blueprint"** → selecione o repositório
3. O Render detecta `whodados/render.yaml` automaticamente.
4. Configure as variáveis de ambiente:
   - `DATABASE_URL`: Connection string do Supabase
   - `CORS_ORIGINS`: URL do seu app Vercel (ex: `https://whodados.vercel.app`)
5. Aguarde o deploy e anote a URL da API (ex: `https://whodados-api.onrender.com`).

---

## 3️⃣ Deploy do Frontend na Vercel

1. Acesse [vercel.com](https://vercel.com) → conecte GitHub
2. **"Add New" → "Project"** → selecione o repositório
3. Configure:
   - **Root Directory**: `whodados/frontend` ← **IMPORTANTE**
   - **Framework Preset**: Next.js
4. **Environment Variables**:
   - `NEXT_PUBLIC_API_URL` = URL da API no Render
5. Clique em **Deploy**.

---

## 📄 Guia Completo

Para instruções detalhadas, consulte [`whodados/DEPLOY.md`](./whodados/DEPLOY.md).
