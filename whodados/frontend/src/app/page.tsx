"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

export default function HomePage() {
  const router = useRouter();
  const { username, isLoading } = useAuth();

  useEffect(() => {
    if (!isLoading) {
      if (username) {
        // A selecao decide: com uma empresa so' ela segue direto pro painel.
        router.replace("/selecionar-empresa");
      } else {
        router.replace("/login");
      }
    }
  }, [isLoading, username, router]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="text-center">
        <div className="text-4xl mb-4">🛡️</div>
        <h1 className="text-2xl font-bold text-slate-800">WhoDados</h1>
        <p className="text-slate-500 mt-2">Carregando...</p>
      </div>
    </div>
  );
}
