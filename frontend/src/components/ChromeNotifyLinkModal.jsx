import { useEffect, useState } from "react";
import { Html5Qrcode } from "html5-qrcode";
import api from "../api/axios";
import toast from "react-hot-toast";

const SCANNER_ELEMENT_ID = "chrome-notify-qr-scanner";

// Admin-side half of the Phase 2 member opt-in flow: the member's own device
// generates a QR (via the public opt-in page) encoding its raw push
// subscription; this modal scans that QR with the ADMIN's camera and links
// it to the member whose profile this was opened from. Also lists/removes
// devices already linked to this member.
export default function ChromeNotifyLinkModal({ member, onClose }) {
  const [scanning, setScanning] = useState(false);
  const [linking, setLinking] = useState(false);
  const [devices, setDevices] = useState([]);
  const [loadingDevices, setLoadingDevices] = useState(true);
  const [showPaste, setShowPaste] = useState(false);
  const [pasteText, setPasteText] = useState("");

  const loadDevices = () => {
    setLoadingDevices(true);
    api.get(`/notifications/push/member/${member.id}/subscriptions/`)
      .then(r => setDevices(r.data))
      .catch(() => {})
      .finally(() => setLoadingDevices(false));
  };

  useEffect(() => { loadDevices(); }, []);

  const linkSubscription = async (decodedText) => {
    setLinking(true);
    try {
      const payload = JSON.parse(decodedText);
      await api.post(`/notifications/push/member/${member.id}/link/`, payload);
      toast.success("Device linked!");
      loadDevices();
    } catch {
      toast.error("Invalid QR code, or linking failed. Try again.");
    } finally {
      setLinking(false);
    }
  };

  // Owns the camera's full lifecycle: starts when `scanning` becomes true,
  // stops on cleanup — whether that's from a successful scan (setScanning(false)
  // below), the Cancel button, or the modal closing/unmounting mid-scan.
  useEffect(() => {
    if (!scanning) return;
    const html5QrCode = new Html5Qrcode(SCANNER_ELEMENT_ID);
    let handled = false;

    html5QrCode.start(
      { facingMode: "environment" },
      {
        fps: 10,
        qrbox: 250,
        // Best-effort: asks the browser to keep re-focusing the video stream (a
        // getUserMedia feed doesn't autofocus as aggressively up-close as a native
        // camera app by default). Unsupported on some devices/browsers, in which
        // case it's silently ignored rather than failing the camera start.
        videoConstraints: { facingMode: "environment", advanced: [{ focusMode: "continuous" }] },
      },
      (decodedText) => {
        if (handled) return;
        handled = true;
        setScanning(false);
        linkSubscription(decodedText);
      },
      () => { /* per-frame miss — expected constantly while aiming the camera */ }
    ).catch((err) => {
      toast.error("Could not access camera: " + (err?.message || err));
      setScanning(false);
    });

    return () => {
      html5QrCode.stop().then(() => html5QrCode.clear()).catch(() => {});
    };
  }, [scanning]);

  const revoke = async (subId) => {
    try {
      await api.post(`/notifications/push/subscriptions/${subId}/revoke/`);
      toast.success("Device removed.");
      loadDevices();
    } catch {
      toast.error("Failed to remove device.");
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 420 }} onClick={e => e.stopPropagation()}>
        <div className="modal-title">Chrome Notifications — {member.name}</div>

        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: "var(--text3)", marginBottom: 8, fontWeight: 600 }}>
            Linked devices
          </div>
          {loadingDevices ? (
            <div style={{ fontSize: 13, color: "var(--text3)" }}>Loading…</div>
          ) : devices.length === 0 ? (
            <div style={{ fontSize: 13, color: "var(--text3)" }}>No device linked yet.</div>
          ) : (
            devices.map(d => (
              <div key={d.id} style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                padding: "8px 0", borderBottom: "1px solid var(--border)",
              }}>
                <span style={{ fontSize: 12, color: "var(--text2)" }}>
                  {d.user_agent ? d.user_agent.slice(0, 40) : "Unknown device"} — added{" "}
                  {new Date(d.created_at).toLocaleDateString()}
                </span>
                <button className="btn btn-sm btn-danger" onClick={() => revoke(d.id)}>Remove</button>
              </div>
            ))
          )}
        </div>

        {!scanning ? (
          <button className="btn btn-primary" style={{ width: "100%" }} onClick={() => setScanning(true)}>
            📷 Scan Member's QR to Link a Device
          </button>
        ) : (
          <>
            <div id={SCANNER_ELEMENT_ID} style={{ width: "100%", borderRadius: 10, overflow: "hidden" }} />
            <button
              className="btn btn-ghost" style={{ width: "100%", marginTop: 10 }}
              onClick={() => setScanning(false)} disabled={linking}
            >
              {linking ? "Linking…" : "Cancel Scan"}
            </button>
          </>
        )}

        {/* Fallback for devices where the in-app camera won't decode the QR:
            read it with any other camera/QR app instead, then paste the text
            here — same linkSubscription() call either way. */}
        {!showPaste ? (
          <button
            className="btn btn-ghost" style={{ width: "100%", marginTop: 10, fontSize: 12 }}
            onClick={() => setShowPaste(true)}
          >
            Can't scan? Paste the code instead
          </button>
        ) : (
          <div style={{ marginTop: 10 }}>
            <textarea
              className="form-input" rows={3} style={{ width: "100%", fontSize: 12, fontFamily: "monospace" }}
              placeholder="Paste the text decoded from the member's QR here…"
              value={pasteText} onChange={e => setPasteText(e.target.value)}
            />
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button
                className="btn btn-primary" style={{ flex: 1 }} disabled={linking || !pasteText.trim()}
                onClick={() => linkSubscription(pasteText.trim()).then(() => setPasteText(""))}
              >
                {linking ? "Linking…" : "Link"}
              </button>
              <button className="btn btn-ghost" onClick={() => { setShowPaste(false); setPasteText(""); }}>
                Cancel
              </button>
            </div>
          </div>
        )}

        <button className="btn btn-secondary" style={{ width: "100%", marginTop: 14 }} onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}
