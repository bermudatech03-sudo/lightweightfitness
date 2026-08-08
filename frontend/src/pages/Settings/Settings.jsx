import { useState, useEffect } from "react";
import { useAuth } from "../../hooks/useAuth";
import api from "../../api/axios";
import toast from "react-hot-toast";
import QRCode from "qrcode";
import "./Settings.css";
import {
  isPushSupported, getPushPermissionState, enableBrowserPush,
  disableBrowserPush, listMySubscriptions,
} from "../../push/pushClient";

// Same obscure path registered in App.jsx for MemberNotifyOptIn.
const MEMBER_OPTIN_PATH = "/nx7qk2vwmz9pfhrb3jt/";

// Only trigger types actually wired to a working Chrome-push code path (see
// backend apps/notifications/signals.py + push.py). Enquiry messages are
// deliberately excluded — those go to people who aren't members yet, so
// there's no one to ask to enable notifications. onOffKey is the SAME setting
// key used by the on/off toggles further up (removed from that list below to
// avoid two controls for one setting) — off/whatsapp/chrome, all in one place.
// Chrome here means two different things depending on the trigger — admin-facing
// ones (Weekly Pending Payment, Daily Buy Reminder, Staff Absentees) broadcast to
// admin; member-facing ones (Member Absentees, Diet Plan Reminder, About to
// Expire, Plan Expired) route to that SPECIFIC member's linked device instead
// (see MEMBER_ONLY_TRIGGERS in backend/apps/notifications/push.py) — the UI
// control is identical either way, only the backend routing differs.
const CHANNEL_TRIGGERS = [
  { onOffKey: "NOTIFY_PENDING_PAYMENT_ADMIN", channelKey: "NOTIFY_CHANNEL_PENDING_PAYMENT_ADMIN", label: "Weekly Pending Payment Summary (Admin)" },
  { onOffKey: "NOTIFY_DAILY_NOTICE",          channelKey: "NOTIFY_CHANNEL_DAILY_NOTICE",          label: "Daily Buy Reminder (Admin)" },
  { onOffKey: "NOTIFY_STAFF_ABSENT",          channelKey: "NOTIFY_CHANNEL_STAFF_ABSENT",          label: "Staff Absentees" },
  { onOffKey: "NOTIFY_ABSENT",                channelKey: "NOTIFY_CHANNEL_ABSENT",                label: "Member Absentees" },
  { onOffKey: "NOTIFY_DIET_REMINDER",         channelKey: "NOTIFY_CHANNEL_DIET_REMINDER",         label: "Diet Plan Reminder" },
  { onOffKey: "NOTIFY_RENEWAL_REMIND",        channelKey: "NOTIFY_CHANNEL_RENEWAL_REMIND",        label: "About to Expire" },
  { onOffKey: "NOTIFY_EXPIRY",                channelKey: "NOTIFY_CHANNEL_EXPIRY",                label: "Plan Expired" },
  { onOffKey: "NOTIFY_PENDING_PAYMENT_MEMBER", channelKey: "NOTIFY_CHANNEL_PENDING_PAYMENT_MEMBER", label: "Weekly Pending Payment (Members)" },
];

// Brand-new notification types (never existed before) — fire on every real
// check-in via fingerprint or manual attendance. Off by default (unlike the
// toggles above, which default on to preserve pre-existing behavior) since
// these are new and can be high-frequency; each is off/whatsapp/chrome.
const CHECKIN_TRIGGERS = [
  { onOffKey: "NOTIFY_MEMBER_CHECKIN", channelKey: "NOTIFY_CHANNEL_MEMBER_CHECKIN", label: "Member Check-in" },
  { onOffKey: "NOTIFY_STAFF_CHECKIN",  channelKey: "NOTIFY_CHANNEL_STAFF_CHECKIN",  label: "Staff Check-in" },
];

const GYM_FIELDS = [
  { key: "GYM_NAME",               label: "Gym Name",                     type: "text" },
  { key: "GYM_ADDRESS",            label: "Address",                      type: "text" },
  { key: "GYM_PHONE",              label: "Phone",                        type: "text" },
  { key: "GYM_EMAIL",              label: "Email",                        type: "email" },
  { key: "GYM_GSTIN",              label: "GSTIN",                        type: "text" },
  { key: "GST_RATE",               label: "GST Rate (%)",                 type: "number" },
  { key: "PT_PAYABLE_PERCENT",     label: "PT Payable to Trainer (%)",    type: "number" },
  { key: "DIET_PLAN_AMOUNT",       label: "Diet Plan Amount (₹)",         type: "number" },
  { key: "ADMIN_WHATSAPP_NUMBER",  label: "Admin WhatsApp Number",        type: "text",
    hint: "All admin notifications (daily buy reminder, pending payment summary, etc.) are sent to this number" },
];

// Note: Member/Staff Absentees, Diet Plan Reminder, Daily Buy Reminder (Admin),
// Weekly Pending Payment Summary (Admin), About to Expire, Plan Expired, and
// Weekly Pending Payment (Members) live in CHANNEL_TRIGGERS below instead
// (off/whatsapp/chrome, one control) — not duplicated here.
const NOTIFY_TOGGLES = [
  { key: "NOTIFY_ENROLLMENT",      label: "Enrollment",                  desc: "Sent when a new member enrolls" },
  { key: "NOTIFY_RENEWAL_CONFIRM", label: "Renewal & Installment Payments", desc: "Sent on membership renewal or balance payment" },
  { key: "NOTIFY_ENQUIRY_FOLLOWUP", label: "Enquiry Follow-up",          desc: "Sent on scheduled follow-up dates to enquiries" },
  { key: "NOTIFY_NEW_PLAN",        label: "New Membership / Offer Plan", desc: "Sent to all active members and enquiries when a new plan is added" },
  { key: "NOTIFY_PT_RENEWAL",      label: "PT Renewal & PT Balance",     desc: "Sends the PT receipt on personal training renewal or balance payment" },
];

export default function Settings() {
  const { user } = useAuth();
  const [pw, setPw] = useState({ old_password:"", new_password:"", confirm:"" });
  const [saving, setSaving] = useState(false);
  const [gymSettings, setGymSettings] = useState({});
  const [gymSaving, setGymSaving] = useState(false);
  const [pushPermission, setPushPermission] = useState("default");
  const [pushBusy, setPushBusy] = useState(false);
  const [mySubs, setMySubs] = useState([]);
  const [optinQr, setOptinQr] = useState(null);
  const [showOptinQr, setShowOptinQr] = useState(false);

  useEffect(() => { document.getElementById("page-title").textContent = "Settings"; }, []);

  useEffect(() => {
    api.get("/finances/gym-settings/").then(r => setGymSettings(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    const url = `${window.location.origin}${MEMBER_OPTIN_PATH}`;
    QRCode.toDataURL(url, { width: 260, margin: 2 }).then(setOptinQr).catch(() => {});
  }, []);

  const refreshPushState = () => {
    getPushPermissionState().then(setPushPermission);
    listMySubscriptions().then(setMySubs).catch(() => {});
  };
  useEffect(refreshPushState, []);

  const handleEnablePush = async () => {
    setPushBusy(true);
    try {
      await enableBrowserPush();
      toast.success("Desktop notifications enabled on this device!");
      refreshPushState();
    } catch (err) {
      toast.error(err.message || "Could not enable notifications.");
    } finally { setPushBusy(false); }
  };

  const handleDisablePush = async () => {
    setPushBusy(true);
    try {
      await disableBrowserPush();
      toast.success("Desktop notifications turned off for this device.");
      refreshPushState();
    } catch {
      toast.error("Could not disable notifications.");
    } finally { setPushBusy(false); }
  };

  // state: "off" | "whatsapp" | "chrome" — shared by CHANNEL_TRIGGERS and CHECKIN_TRIGGERS,
  // both of which are { onOffKey, channelKey, label } shaped.
  const setTriggerState = async ({ onOffKey, channelKey }, state) => {
    const patch = state === "off"
      ? { [onOffKey]: "false" }
      : { [onOffKey]: "true", [channelKey]: state };
    const prev = { [onOffKey]: gymSettings[onOffKey], [channelKey]: gymSettings[channelKey] };
    setGymSettings(p => ({ ...p, ...patch }));
    try {
      await api.patch("/finances/gym-settings/", patch);
    } catch {
      setGymSettings(p => ({ ...p, ...prev }));
      toast.error("Failed to save. Please try again.");
    }
  };

  const renderTriggerRow = (trigger) => {
    const isOn = gymSettings[trigger.onOffKey] === "true";
    const state = !isOn ? "off" : (gymSettings[trigger.channelKey] === "chrome" ? "chrome" : "whatsapp");
    return (
      <div key={trigger.onOffKey} style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexWrap: "wrap", gap: 10,
        background: "var(--surface2)", borderRadius: 10, padding: "12px 16px",
        border: "1px solid var(--border)",
      }}>
        <div style={{ fontWeight: 600, fontSize: 13, color: "var(--text1)" }}>{trigger.label}</div>
        <div style={{ display: "flex", gap: 4, background: "var(--surface)", borderRadius: 8, padding: 3 }}>
          {["off", "whatsapp", "chrome"].map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => setTriggerState(trigger, opt)}
              className={`btn btn-sm ${state === opt ? "btn-primary" : "btn-ghost"}`}
            >
              {opt === "off" ? "Off" : opt === "whatsapp" ? "WhatsApp" : "Chrome"}
            </button>
          ))}
        </div>
      </div>
    );
  };

  const saveGymSettings = async (e) => {
    e.preventDefault();
    setGymSaving(true);
    try {
      const res = await api.patch("/finances/gym-settings/", gymSettings);
      setGymSettings(res.data);
      toast.success("Gym settings saved!");
    } catch { toast.error("Failed to save settings."); }
    finally { setGymSaving(false); }
  };

  const changePassword = async (e) => {
    e.preventDefault();
    if (pw.new_password !== pw.confirm) { toast.error("Passwords don't match"); return; }
    setSaving(true);
    try {
      await api.post("/auth/change-password/", { old_password:pw.old_password, new_password:pw.new_password });
      toast.success("Password changed!");
      setPw({ old_password:"", new_password:"", confirm:"" });
    } catch { toast.error("Wrong current password"); } finally { setSaving(false); }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Settings</div>
          <div className="page-subtitle">Account, security and preferences</div>
        </div>
      </div>

      <div className="settings-grid">
        {/* Profile card */}
        <div className="card" style={{padding:24}}>
          <div style={{fontFamily:"var(--font-display)",fontSize:16,fontWeight:700,marginBottom:18}}>My Profile</div>
          <div style={{display:"flex",alignItems:"center",gap:16,marginBottom:20}}>
            <div style={{width:56,height:56,borderRadius:"50%",background:"linear-gradient(135deg,var(--accent),var(--accent2))",
              display:"flex",alignItems:"center",justifyContent:"center",
              fontFamily:"var(--font-display)",fontSize:24,fontWeight:800,color:"#fff"}}>
              {user?.full_name?.[0]||user?.username?.[0]||"A"}
            </div>
            <div>
              <div style={{fontWeight:700,fontSize:16}}>{user?.full_name||user?.username}</div>
              <div style={{fontSize:12,color:"var(--text3)"}}>{user?.email}</div>
              <span className="badge badge-green" style={{marginTop:4}}>{user?.role}</span>
            </div>
          </div>
        </div>

        {/* Gym Settings */}
        <div className="card" style={{ padding: 24, gridColumn: "1/-1" }}>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 16, fontWeight: 700, marginBottom: 18 }}>
            Gym Settings
          </div>
          <form onSubmit={saveGymSettings}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(260px,100%),1fr))", gap: 14, marginBottom: 18 }}>
              {GYM_FIELDS.map(({ key, label, type, hint }) => (
                <div className="form-group" key={key}>
                  <label className="form-label">{label}</label>
                  <input
                    className="form-input"
                    type={type}
                    min={type === "number" ? "0" : undefined}
                    max={key === "PT_PAYABLE_PERCENT" ? "100" : undefined}
                    value={gymSettings[key] ?? ""}
                    onChange={e => setGymSettings(p => ({ ...p, [key]: e.target.value }))}
                  />
                  {hint && <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 4 }}>{hint}</div>}
                </div>
              ))}
            </div>
            <button type="submit" className="btn btn-primary" disabled={gymSaving}>
              {gymSaving ? "Saving…" : "Save Gym Settings"}
            </button>
          </form>
        </div>

        {/* WhatsApp Notification Toggles */}
        <div className="card" style={{ padding: 24, gridColumn: "1/-1" }}>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 16, fontWeight: 700, marginBottom: 4 }}>
            WhatsApp Notifications
          </div>
          <div style={{ fontSize: 12, color: "var(--text3)", marginBottom: 18 }}>
            Turn each category on or off. Each toggle saves instantly.
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(300px,100%),1fr))", gap: 12 }}>
            {NOTIFY_TOGGLES.map(({ key, label, desc }) => {
              const isOn = (gymSettings[key] ?? "true") !== "false";
              const toggle = async () => {
                const newVal = isOn ? "false" : "true";
                setGymSettings(p => ({ ...p, [key]: newVal }));
                try {
                  await api.patch("/finances/gym-settings/", { [key]: newVal });
                } catch {
                  setGymSettings(p => ({ ...p, [key]: isOn ? "true" : "false" }));
                  toast.error("Failed to save. Please try again.");
                }
              };
              return (
                <div key={key} style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  background: "var(--surface2)", borderRadius: 10, padding: "12px 16px",
                  border: "1px solid var(--border)",
                }}>
                  <div style={{ flex: 1, marginRight: 14 }}>
                    <div style={{ fontWeight: 600, fontSize: 13, color: "var(--text1)", marginBottom: 2 }}>{label}</div>
                    <div style={{ fontSize: 11, color: "var(--text3)" }}>{desc}</div>
                  </div>
                  <button
                    type="button"
                    onClick={toggle}
                    style={{
                      flexShrink: 0,
                      width: 44, height: 24, borderRadius: 12, border: "none", cursor: "pointer",
                      background: isOn ? "var(--accent)" : "var(--surface)",
                      outline: isOn ? "none" : "1px solid var(--border)",
                      position: "relative", transition: "background 0.2s",
                    }}
                    aria-label={`Toggle ${label}`}
                  >
                    <span style={{
                      position: "absolute", top: 3,
                      left: isOn ? 23 : 3,
                      width: 18, height: 18, borderRadius: "50%",
                      background: isOn ? "#fff" : "var(--surface3)",
                      transition: "left 0.2s",
                      display: "block",
                    }} />
                  </button>
                </div>
              );
            })}
          </div>
        </div>

        {/* Chrome Push Notifications */}
        <div className="card" style={{ padding: 24, gridColumn: "1/-1" }}>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 16, fontWeight: 700, marginBottom: 4 }}>
            Chrome Push Notifications
          </div>
          <div style={{ fontSize: 12, color: "var(--text3)", marginBottom: 18 }}>
            A free alternative to WhatsApp for the categories below — no Meta messaging cost.
            Enable it on this device, then choose which categories should use it instead of WhatsApp.
          </div>

          {!isPushSupported() ? (
            <div style={{ fontSize: 13, color: "var(--text3)" }}>
              This browser doesn't support push notifications.
            </div>
          ) : (
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              flexWrap: "wrap", gap: 12, marginBottom: 20,
              background: "var(--surface2)", borderRadius: 10, padding: "12px 16px",
              border: "1px solid var(--border)",
            }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 13, color: "var(--text1)", marginBottom: 2 }}>
                  This device
                </div>
                <div style={{ fontSize: 11, color: "var(--text3)" }}>
                  {mySubs.length > 0
                    ? `Enabled — ${mySubs.length} device${mySubs.length !== 1 ? "s" : ""} subscribed on this account`
                    : pushPermission === "denied"
                      ? "Blocked — notification permission was denied in the browser"
                      : "Not enabled on this device yet"}
                </div>
              </div>
              {mySubs.length > 0 ? (
                <button type="button" className="btn btn-ghost" disabled={pushBusy} onClick={handleDisablePush}>
                  {pushBusy ? "Working…" : "Disable on this device"}
                </button>
              ) : (
                <button
                  type="button" className="btn btn-primary" disabled={pushBusy || pushPermission === "denied"}
                  onClick={handleEnablePush}
                >
                  {pushBusy ? "Working…" : "Enable Desktop Notifications"}
                </button>
              )}
            </div>
          )}

          <div style={{
            background: "var(--surface2)", borderRadius: 10, padding: "12px 16px",
            border: "1px solid var(--border)", marginBottom: 20,
          }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 13, color: "var(--text1)", marginBottom: 2 }}>
                  Get a member enabled
                </div>
                <div style={{ fontSize: 11, color: "var(--text3)" }}>
                  Show this QR — the member scans it, taps Allow, then shows you the QR their
                  page generates so you can link it (via a member's "Chrome Notifications" button).
                </div>
              </div>
              <button type="button" className="btn btn-ghost" onClick={() => setShowOptinQr(v => !v)}>
                {showOptinQr ? "Hide QR" : "Show QR"}
              </button>
            </div>
            {showOptinQr && optinQr && (
              <div style={{ marginTop: 14, textAlign: "center" }}>
                <img src={optinQr} alt="Member notification opt-in QR" style={{ width: 200, borderRadius: 8, background: "#fff", padding: 6 }} />
              </div>
            )}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(320px,100%),1fr))", gap: 12 }}>
            {CHANNEL_TRIGGERS.map(renderTriggerRow)}
          </div>

          <div style={{ height: 1, background: "var(--border)", margin: "20px 0" }} />

          <div style={{ fontFamily: "var(--font-display)", fontSize: 14, fontWeight: 700, marginBottom: 4 }}>
            Check-in Alerts
          </div>
          <div style={{ fontSize: 12, color: "var(--text3)", marginBottom: 14 }}>
            New — fires on every real check-in (fingerprint or manual attendance). Off by default.
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(320px,100%),1fr))", gap: 12 }}>
            {CHECKIN_TRIGGERS.map(renderTriggerRow)}
          </div>
        </div>

        {/* Change password */}
        <div className="card" style={{padding:24}}>
          <div style={{fontFamily:"var(--font-display)",fontSize:16,fontWeight:700,marginBottom:18}}>Change Password</div>
          <form onSubmit={changePassword} style={{display:"flex",flexDirection:"column",gap:14}}>
            <div className="form-group"><label className="form-label">Current Password</label>
              <input className="form-input" type="password" value={pw.old_password} onChange={e=>setPw(p=>({...p,old_password:e.target.value}))} required /></div>
            <div className="form-group"><label className="form-label">New Password</label>
              <input className="form-input" type="password" value={pw.new_password} onChange={e=>setPw(p=>({...p,new_password:e.target.value}))} required minLength={8} /></div>
            <div className="form-group"><label className="form-label">Confirm New Password</label>
              <input className="form-input" type="password" value={pw.confirm} onChange={e=>setPw(p=>({...p,confirm:e.target.value}))} required /></div>
            <button type="submit" className="btn btn-primary" style={{alignSelf:"flex-start"}} disabled={saving}>{saving?"Saving…":"Update Password"}</button>
          </form>
        </div>


        <div className="card" style={{ padding: 28, gridColumn: "1/-1", position: "relative", overflow: "hidden" }}>
  
  {/* Headline */}
  <div style={{ fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 800, marginBottom: 10 }}>
    GymPro CRM
  </div>

  {/* Tagline */}
  <div style={{ fontSize: 14, color: "var(--text2)", marginBottom: 20, maxWidth: 600 }}>
    The all-in-one solution to manage your gym, boost member engagement, and grow your fitness business effortlessly.
  </div>

  {/* Features Grid */}
  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(200px,100%),1fr))", gap: 14 }}>
    {[
      { label: "⚡ Fast & Scalable", value: "Built with Django + React" },
      { label: "🔐 Secure Access", value: "JWT Authentication" },
      { label: "📊 Smart Data", value: "PostgreSQL Powered" },
      { label: "📩 Instant Alerts", value: "Email + WhatsApp Integration" },
      { label: "🎯 Modern UI", value: "Lightning-fast React + Vite" },
    ].map(({ label, value }) => (
      <div key={label} style={{ background: "var(--surface2)", borderRadius: 10, padding: "14px 18px" }}>
        <div style={{ fontSize: 12, color: "var(--text3)", marginBottom: 6, fontWeight: 600 }}>
          {label}
        </div>
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text1)" }}>
          {value}
        </div>
      </div>
    ))}
  </div>

  {/* Call To Action */}
  <div style={{ marginTop: 22, display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
    <div style={{ fontSize: 13, color: "var(--text2)" }}>
      Transform your gym management today.
    </div>

    
  </div>
</div>


<div className="card" style={{ padding: 28, gridColumn: "1/-1" }}>

  {/* 🔝 Advertisement Section */}
  <div style={{ marginBottom: 28 }}>
    <div style={{ fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 800, marginBottom: 8 }}>
      Company Details
    </div>

    <div style={{ fontSize: 14, color: "var(--text2)", marginBottom: 18, maxWidth: 600 }}>
      
    </div>
  </div>

  {/* 🔽 Divider */}
  <div style={{ height: 1, background: "var(--border)", margin: "20px 0" }} />

  {/* 🔽 Company Details Section */}
  <div>
    <div style={{ fontFamily: "var(--font-display)", fontSize: 16, fontWeight: 700, marginBottom: 16 }}>
      Bermuda Tech
    </div>

    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(200px,100%),1fr))", gap: 12 }}>
      {[
        { label: "Company Name", value: "Bermuda Tech" },
       
        { label: "Location", value: "India" },
        { label: "Product", value: "GymPro CRM" },
        { label: "Support", value: "bermudatech03@gmail.com" },
        { label: "Website", value: "bermudatech.com" },
      ].map(({ label, value }) => (
        <div key={label} style={{ background: "var(--surface2)", borderRadius: 8, padding: "12px 16px" }}>
          <div style={{
            fontSize: 11,
            color: "var(--text3)",
            marginBottom: 4,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: .5
          }}>
            {label}
          </div>

          <div style={{
            fontSize: 13,
            fontWeight: 600,
            color: "var(--text1)",
            fontFamily: "var(--font-mono)"
          }}>
            {value}
          </div>
        </div>
      ))}
    </div>
  </div>

</div>
      </div>
    </div>
  );
}
