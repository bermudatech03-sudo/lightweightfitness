import { useState, useEffect } from "react";
import api from "../../api/axios";
import toast from "react-hot-toast";

export default function NotifyPermissions() {
  const [subs, setSubs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    try { document.getElementById("page-title").textContent = "Notification Permissions"; } catch {}
  }, []);

  const load = () => {
    setLoading(true);
    api.get("/notifications/push/members/subscriptions/")
      .then(r => setSubs(r.data))
      .catch(() => toast.error("Failed to load permissions."))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const revoke = async (subId) => {
    try {
      await api.post(`/notifications/push/subscriptions/${subId}/revoke/`);
      toast.success("Permission revoked.");
      load();
    } catch {
      toast.error("Failed to revoke.");
    }
  };

  const q = search.trim().toLowerCase();
  const filtered = q ? subs.filter(s => s.member_name.toLowerCase().includes(q)) : subs;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Notification Permissions</h1>
          <p className="page-subtitle">Every member currently linked for Chrome notifications, across the whole gym</p>
        </div>
      </div>

      <div style={{ marginBottom: 20 }}>
        <input
          className="form-input" style={{ maxWidth: 280 }}
          placeholder="Search by member name…"
          value={search} onChange={e => setSearch(e.target.value)}
        />
      </div>

      {loading ? (
        <div className="empty-state">Loading…</div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">🔔</div>
          <div className="empty-state-title">
            {q ? "No matching member" : "No member has linked a device yet"}
          </div>
          <div className="empty-state-sub">
            Show the opt-in QR from Settings to get a member started.
          </div>
        </div>
      ) : (
        <div className="table-wrapper desktop-table-view">
          <table className="table">
            <thead>
              <tr>
                <th>Member</th>
                <th>Device</th>
                <th>Linked</th>
                <th>Last Used</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(s => (
                <tr key={s.id}>
                  <td style={{ fontWeight: 600 }}>{s.member_name}</td>
                  <td style={{ fontSize: 12, color: "var(--text-muted)", maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {s.user_agent || "Unknown device"}
                  </td>
                  <td style={{ fontSize: 12, whiteSpace: "nowrap" }}>
                    {new Date(s.created_at).toLocaleDateString("en-IN")}
                  </td>
                  <td style={{ fontSize: 12, whiteSpace: "nowrap", color: "var(--text-muted)" }}>
                    {s.last_used_at ? new Date(s.last_used_at).toLocaleDateString("en-IN") : "—"}
                  </td>
                  <td>
                    <button className="btn btn-sm btn-danger" onClick={() => revoke(s.id)}>Revoke</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
