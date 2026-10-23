"use client";

import { useState, useEffect, Suspense } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { ApiError, validateResetToken, resetPassword } from "@/lib/api";

function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("token") || "";

  const [novaSenha, setNovaSenha] = useState("");
  const [confirmSenha, setConfirmSenha] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);
  const [tokenValid, setTokenValid] = useState<boolean | null>(null);

  useEffect(() => {
    if (!token) {
      setTokenValid(false);
      return;
    }
    validateResetToken(token)
      .then(() => setTokenValid(true))
      .catch(() => setTokenValid(false));
  }, [token]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (novaSenha !== confirmSenha) {
      setError("As senhas nao coincidem");
      return;
    }
    if (novaSenha.length < 8) {
      setError("Senha deve ter no minimo 8 caracteres");
      return;
    }
    setLoading(true);
    try {
      await resetPassword(token, novaSenha);
      setSuccess(true);
    } catch (err) {
      if (err instanceof ApiError) setError(err.message);
      else setError("Erro ao redefinir senha");
    } finally {
      setLoading(false);
    }
  };

  if (tokenValid === null) {
    return (
      <div className="text-center py-8 text-slate-500">
        Validando token...
      </div>
    );
  }

  if (tokenValid === false) {
    return (
      <div className="space-y-4">
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700">
          Token invalido ou expirado. Solicite uma nova recuperacao de senha.
        </div>
        <Link href="/forgot-password" className="block text-center rounded-lg bg-indigo-600 px-4 py-2 font-semibold text-white hover:bg-indigo-700">
          Solicitar nova recuperacao
        </Link>
        <Link href="/login" className="block text-center text-sm text-indigo-600 hover:underline">
          Voltar para login
        </Link>
      </div>
    );
  }

  if (success) {
    return (
      <div className="space-y-4">
        <div className="rounded-lg bg-green-50 p-4 text-sm text-green-700">
          Senha redefinida com sucesso! Agora voce pode fazer login com sua nova senha.
        </div>
        <Link href="/login" className="block text-center rounded-lg bg-indigo-600 px-4 py-2 font-semibold text-white hover:bg-indigo-700">
          Ir para login
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-slate-700 mb-1">
          Nova Senha
        </label>
        <input
          type="password"
          value={novaSenha}
          onChange={(e) => setNovaSenha(e.target.value)}
          required
          minLength={8}
          placeholder="Minimo 8 caracteres"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-700 mb-1">
          Confirmar Senha
        </label>
        <input
          type="password"
          value={confirmSenha}
          onChange={(e) => setConfirmSenha(e.target.value)}
          required
          minLength={8}
          placeholder="Repita a senha"
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
        {loading ? "Redefinindo..." : "Redefinir senha"}
      </button>

      <Link href="/login" className="block text-center text-sm text-indigo-600 hover:underline">
        Voltar para login
      </Link>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-lg">
        <div className="text-center mb-6">
          <div className="text-5xl mb-3">🔐</div>
          <h1 className="text-2xl font-bold text-slate-800">Nova Senha</h1>
          <p className="text-slate-500 mt-1">Digite sua nova senha</p>
        </div>

        <Suspense fallback={<div className="text-center py-8 text-slate-500">Carregando...</div>}>
          <ResetPasswordForm />
        </Suspense>
      </div>
    </div>
  );
}
