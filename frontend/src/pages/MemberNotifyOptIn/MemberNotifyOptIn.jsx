import { useState } from "react";
import QRCode from "qrcode";
import api from "../../api/axios";
import "./MemberNotifyOptIn.css";

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
}

// Public, unauthenticated page — a member scans the admin's QR to reach this.
// Generates a push subscription on THIS device, then shows it as a QR code
// for the admin to scan and link to the correct member profile. This page
// never talks to the backend to identify who the member is — that
// verification happens because the admin is physically choosing who to link
// it to, not because this page asks for any personal info.
export default function MemberNotifyOptIn() {
  const [status, setStatus] = useState("idle"); // idle | working | ready | error
  const [qrDataUrl, setQrDataUrl] = useState(null);
  const [errorMsg, setErrorMsg] = useState("");

  const isSupported = "serviceWorker" in navigator && "PushManager" in window;

  const handleEnable = async () => {
    setStatus("working");
    setErrorMsg("");
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        throw new Error("Notification permission was not granted.");
      }

      const reg = await navigator.serviceWorker.register("/push-sw.js");
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

      // A short device label instead of the full user-agent string (which alone can
      // run 100+ chars) — keeps the QR's data (and so its module density) down,
      // since the admin's in-app camera scanner has a harder time locking focus on
      // a dense code than a native camera app does.
      const ua = navigator.userAgent;
      const os = /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Windows/.test(ua) ? "Windows" : /Mac/.test(ua) ? "Mac" : "Unknown OS";
      const browserMatch = ua.match(/(Chrome|Firefox|Safari|Edg|SamsungBrowser)\/[\d.]+/);
      const uaShort = [os, browserMatch ? browserMatch[0].replace("Edg/", "Edge/") : ""].filter(Boolean).join(" · ");

      const payload = {
        ...subscription.toJSON(),
        user_agent: uaShort,
      };

      // errorCorrectionLevel "L" (vs the default "M") trades resilience to a
      // damaged/dirty code — irrelevant for one shown fresh on a screen — for a
      // coarser, larger-moduled QR that's easier for a phone camera to decode.
      const qr = await QRCode.toDataURL(JSON.stringify(payload), { width: 320, margin: 2, errorCorrectionLevel: "L" });
      setQrDataUrl(qr);
      setStatus("ready");
    } catch (err) {
      setErrorMsg(err.message || "Something went wrong enabling notifications.");
      setStatus("error");
    }
  };

  return (
    <div className="optin-page">
      <div className="optin-card">
        <img src="/Gympro_logo.jpeg" alt="Gym logo" className="optin-logo" />
        <h1>Enable Gym Notifications</h1>

        {!isSupported ? (
          <p className="optin-muted">This browser doesn't support notifications. Try Chrome on Android or a desktop browser.</p>
        ) : status === "idle" || status === "working" ? (
          <>
            <p className="optin-muted">
              Tap below, then allow notifications when your browser asks. Show the front desk
              the QR code that appears next to finish setup.
            </p>
            <button className="optin-btn" onClick={handleEnable} disabled={status === "working"}>
              {status === "working" ? "Working…" : "Enable Notifications"}
            </button>
          </>
        ) : status === "ready" ? (
          <>
            <p className="optin-muted">Show this to the front desk to finish linking your device.</p>
            <img src={qrDataUrl} alt="Show this to the front desk" className="optin-qr" />
          </>
        ) : (
          <>
            <p className="optin-error">{errorMsg}</p>
            <button className="optin-btn" onClick={handleEnable}>Try Again</button>
          </>
        )}
      </div>
    </div>
  );
}
