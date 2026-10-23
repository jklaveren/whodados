"use client";

/**
 * Web Push no navegador: registra /sw.js, pede permissao e inscreve o
 * aparelho no backend (que vincula a inscricao a empresa ativa).
 * iOS exige: app instalado na tela de inicio (iOS 16.4+) + gesto do usuario.
 */
import { getVapidPublicKey, subscribePush, unsubscribePush } from "./api";

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

export function pushSuportado(): boolean {
  if (typeof window === "undefined") return false;
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

async function getRegistration(): Promise<ServiceWorkerRegistration> {
  return navigator.serviceWorker.register("/sw.js");
}

export async function pushAtivo(): Promise<boolean> {
  if (!pushSuportado()) return false;
  try {
    const reg = await getRegistration();
    const sub = await reg.pushManager.getSubscription();
    return sub !== null;
  } catch {
    return false;
  }
}

/** Liga os avisos neste aparelho. Retorna false se o usuario negar ou o servidor nao tiver VAPID. */
export async function ativarPush(): Promise<{ ok: boolean; motivo?: string }> {
  if (!pushSuportado()) return { ok: false, motivo: "Este navegador não suporta avisos push." };
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return { ok: false, motivo: "Permissão de notificação negada." };
  const { publicKey, enabled } = await getVapidPublicKey();
  if (!enabled || !publicKey) return { ok: false, motivo: "Push ainda não configurado no servidor." };
  const reg = await getRegistration();
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(publicKey),
  });
  const json = sub.toJSON();
  await subscribePush({
    endpoint: sub.endpoint,
    keys: { p256dh: json.keys?.p256dh ?? "", auth: json.keys?.auth ?? "" },
  });
  return { ok: true };
}

export async function desativarPush(): Promise<void> {
  if (!pushSuportado()) return;
  try {
    const reg = await getRegistration();
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      const endpoint = sub.endpoint;
      await sub.unsubscribe();
      await unsubscribePush(endpoint).catch(() => {});
    }
  } catch {
    /* aparelho sem inscricao -- nada a desligar */
  }
}
