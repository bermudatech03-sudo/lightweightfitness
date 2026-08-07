import api from "../api/axios";

// Converts a base64url VAPID public key into the Uint8Array pushManager.subscribe() expects.
function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
}

export function isPushSupported() {
  return "serviceWorker" in navigator && "PushManager" in window;
}

export async function getPushPermissionState() {
  if (!isPushSupported()) return "unsupported";
  return Notification.permission; // "default" | "granted" | "denied"
}

async function registerServiceWorker() {
  return navigator.serviceWorker.register("/push-sw.js");
}

export async function getCurrentSubscription() {
  if (!isPushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration("/push-sw.js");
  if (!reg) return null;
  return reg.pushManager.getSubscription();
}

/**
 * Full opt-in flow: register the service worker, request permission, subscribe
 * with the backend's VAPID public key, then register the subscription with the
 * backend so it knows where to send pushes for this user.
 * Throws if the browser doesn't support push, or the user denies permission.
 */
export async function enableBrowserPush() {
  if (!isPushSupported()) {
    throw new Error("This browser does not support push notifications.");
  }

  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error("Notification permission was not granted.");
  }

  const reg = await registerServiceWorker();
  await navigator.serviceWorker.ready;

  const { data } = await api.get("/notifications/push/vapid-key/");
  const applicationServerKey = urlBase64ToUint8Array(data.publicKey);

  let subscription = await reg.pushManager.getSubscription();
  if (!subscription) {
    subscription = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey,
    });
  }

  await api.post("/notifications/push/subscribe/", subscription.toJSON());
  return subscription;
}

/** Turns off push for this browser — unsubscribes locally and tells the backend to stop sending. */
export async function disableBrowserPush() {
  const subscription = await getCurrentSubscription();
  if (!subscription) return;
  const endpoint = subscription.endpoint;
  await subscription.unsubscribe();
  await api.post("/notifications/push/unsubscribe/", { endpoint });
}

export async function listMySubscriptions() {
  const { data } = await api.get("/notifications/push/subscriptions/");
  return data;
}
