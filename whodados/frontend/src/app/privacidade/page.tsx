import type { Metadata } from "next";
import Link from "next/link";

// Publica e sem login: o Google exige o link desta pagina para publicar o
// app de envio pelo Gmail, e quem autoriza a conta precisa conseguir le-la
// antes de entrar.
export const metadata: Metadata = {
  title: "Política de Privacidade — WhoDados",
};

const CONTATO = "contato@exemplo.com.br";
const ATUALIZADA_EM = "14 de outubro de 2026";

function Secao({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold text-slate-800">{titulo}</h2>
      <div className="space-y-2 text-sm leading-relaxed text-slate-600">{children}</div>
    </section>
  );
}

export default function PrivacidadePage() {
  return (
    <main className="min-h-screen bg-slate-50 px-4 py-10">
      <article className="mx-auto max-w-3xl space-y-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm md:p-10">
        <header className="space-y-1">
          <p className="text-sm font-semibold text-indigo-600">WhoDados</p>
          <h1 className="text-2xl font-bold text-slate-900">Política de Privacidade</h1>
          <p className="text-xs text-slate-400">Atualizada em {ATUALIZADA_EM}</p>
        </header>

        <Secao titulo="O que é o WhoDados">
          <p>
            O WhoDados é uma plataforma de inteligência comercial usada por empresas para
            organizar prospecção, CRM e campanhas de e-mail. Esta política explica quais dados
            a plataforma trata, para quê, e como você pode pedir acesso, correção ou exclusão.
          </p>
        </Secao>

        <Secao titulo="Conexão com a sua conta do Google (Gmail)">
          <p>
            Quando você clica em <strong>Conectar Gmail</strong>, o WhoDados pede ao Google
            apenas duas permissões:
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li>
              <strong>Enviar e-mail em seu nome</strong> (<code>gmail.send</code>): usada só para
              enviar as mensagens que você ou a sua empresa dispararem pela plataforma.
            </li>
            <li>
              <strong>Ver o endereço de e-mail da conta</strong>: usada só para mostrar na tela
              qual conta está conectada.
            </li>
          </ul>
          <p>
            O WhoDados <strong>não lê, não lista e não apaga</strong> mensagens da sua caixa, não
            acessa seus contatos, sua agenda nem seus arquivos. A permissão pedida não dá esse
            acesso.
          </p>
          <p>
            A autorização concedida pelo Google é guardada <strong>cifrada</strong> no nosso
            banco de dados e usada apenas para os envios acima. Ela não é compartilhada, vendida
            nem usada para publicidade ou para treinar modelos de inteligência artificial.
          </p>
          <p>
            O uso e a transferência, pelo WhoDados, de informações recebidas das APIs do Google
            seguem a{" "}
            <a
              href="https://developers.google.com/terms/api-services-user-data-policy"
              className="text-indigo-600 underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              Política de Dados do Usuário dos Serviços de API do Google
            </a>
            , incluindo os requisitos de Uso Limitado.
          </p>
          <p>
            Você pode revogar o acesso a qualquer momento, pelo botão{" "}
            <strong>Desconectar</strong> em Configurações → E-mail, ou diretamente na sua conta
            Google, em{" "}
            <a
              href="https://myaccount.google.com/permissions"
              className="text-indigo-600 underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              myaccount.google.com/permissions
            </a>
            . Ao desconectar, a autorização é apagada do nosso banco.
          </p>
        </Secao>

        <Secao titulo="Dados de quem usa a plataforma">
          <p>
            Guardamos nome de usuário, e-mail, senha (cifrada, nunca em texto puro), empresas às
            quais você tem acesso e as configurações de e-mail que você preencher (remetente,
            nome de exibição e assinatura). Ações na plataforma ficam registradas para
            auditoria e segurança.
          </p>
        </Secao>

        <Secao titulo="Dados das empresas prospectadas">
          <p>
            As empresas exibidas vêm de dados públicos do Cadastro Nacional da Pessoa Jurídica
            (Receita Federal) ou de listas fornecidas pela própria empresa cliente. São usados
            para contato comercial entre empresas.
          </p>
          <p>
            Todo e-mail de campanha traz um link para deixar de receber mensagens. Quem usa o
            link é retirado das listas de envio de todas as empresas da plataforma.
          </p>
        </Secao>

        <Secao titulo="Seus direitos (LGPD)">
          <p>
            Você pode pedir confirmação de tratamento, acesso, correção, anonimização ou exclusão
            dos seus dados, e informações sobre compartilhamento, escrevendo para{" "}
            <a href={`mailto:${CONTATO}`} className="text-indigo-600 underline">
              {CONTATO}
            </a>
            .
          </p>
        </Secao>

        <Secao titulo="Contato">
          <p>
            Dúvidas sobre esta política:{" "}
            <a href={`mailto:${CONTATO}`} className="text-indigo-600 underline">
              {CONTATO}
            </a>
            .
          </p>
        </Secao>

        <footer className="border-t border-slate-100 pt-4 text-xs text-slate-400">
          <Link href="/" className="text-indigo-600 underline">
            Voltar ao WhoDados
          </Link>
        </footer>
      </article>
    </main>
  );
}
