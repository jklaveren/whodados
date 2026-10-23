"use client";

import { useState } from "react";
import Link from "next/link";
import { ApiError, forgotPassword } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [identifier, setIdentifier] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);
  const [devToken, setDevToken] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const result: any = await forgotPassword(identifier);
      setSuccess(true);
      if (result?._dev_token) setDevToken(result._dev_token);
    } catch (err) {
      if (err instanceof ApiError) setError(err.message);
      else setError("Erro ao solicitar recuperacao. Tente novamente.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-lg">
        <div className="text-center mb-6">
          <div className="text-5xl mb-3">🔑</div>
          <h1 className="text-2xl font-bold text-slate-800">Esqueci minha senha</h1>
          <p className="text-slate-500 mt-1">Informe seu usuario ou e-mail</p>
        </div>

        {success ? (
          <div className="space-y-4">
            <div className="rounded-lg bg-green-50 p-4 text-sm text-green-700">
              Se o usuario existir em nossa base, um e-mail de recuperacao foi enviado
              com instrucoes para redefinir sua senha. Verifique sua caixa de entrada.
            </div>
            {devToken && (
              <div className="rounded-lg bg-yellow-50 p-3 text-xs text-yellow-800 break-all">
                <strong>DEV:</strong> Token de teste = {devToken}
                <br />
                <Link href={`/reset-password?token=${devToken}`} className="text-indigo-600 underline">
                  Ir para redefinicao
                </Link>
              </div>
            )}
            <Link href="/login" className="block text-center rounded-lg border border-slate-300 px-4 py-2 text-slate-700 hover:bg-slate-50">
              Voltar para o login
            </Link>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Usuario ou E-mail
              </label>
              <input
                type="text"
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                required
                placeholder="seu-usuario ou email@empresa.com"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200"
              />
            </div>

            {error && (
              <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-lg bg-indigo-600 px-4 py-2.5 font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {loading ? "Enviando..." : "Enviar link de recuperacao"}
            </button>

            <Link href="/login" className="block text-center text-sm text-indigo-600 hover:underline">
              Voltar para o login
            </Link>
          </form>
        )}
      </div>
    </div>
  );
}
