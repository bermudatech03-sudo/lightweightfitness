import { useState, useEffect, useCallback } from "react";
import api from "../../api/axios";
import toast from "react-hot-toast";
import ConfirmModal from "../../components/ConfirmModal";

const STATUS_LABELS = {
  followup: { label: "Follow-up", cls: "badge-yellow" },
  converted: { label: "Converted", cls: "badge-green" },
  lost: { label: "Lost", cls: "badge-gray" },
};

const EMPTY_FORM = { name: "", phone: "", email: "", notes: "", status: "followup" };

function EnquiryModal({ enquiry, onClose, onSave }) {
  const isEdit = !!enquiry?.id;
  const [form, setForm] = useState(isEdit ? {
    name: enquiry.name, phone: enquiry.phone, email: enquiry.email,
    notes: enquiry.notes, status: enquiry.status,
  } : { ...EMPTY_FORM });
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (isEdit) {
        await api.patch(`/enquiries/${enquiry.id}/`, form);
        toast.success("Enquiry updated!");
      } else {
        await api.post("/enquiries/", form);
        toast.success("Enquiry added! Welcome message sent via WhatsApp.");
      }
      onSave();
    } catch (err) {
      const d = err.response?.data;
      toast.error(d?.detail ?? (typeof d === "object" ? Object.values(d).flat().join(" ") : "Something went wrong"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 480 }} onClick={e => e.stopPropagation()}>
        <div className="modal-title">{isEdit ? "Edit Enquiry" : "Add Enquiry"}</div>
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="form-group">
            <label className="form-label">Name *</label>
            <input className="form-input" value={form.name} onChange={e => set("name", e.target.value)} required />
          </div>
          <div className="form-group">
            <label className="form-label">Phone *</label>
            <input className="form-input" type="tel" value={form.phone} onChange={e => set("phone", e.target.value)} required />
          </div>
          <div className="form-group">
            <label className="form-label">Email</label>
            <input className="form-input" type="email" value={form.email} onChange={e => set("email", e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Status</label>
            <select className="form-input" value={form.status} onChange={e => set("status", e.target.value)}>
              {Object.entries(STATUS_LABELS).map(([k, v]) => (
                <option key={k} value={k}>{v.label}</option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Notes</label>
            <textarea className="form-input" rows={3} value={form.notes} onChange={e => set("notes", e.target.value)} />
          </div>
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? "Saving…" : isEdit ? "Update" : "Add Enquiry"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function Enquiry() {
  const [enquiries, setEnquiries] = useState([]);
  const [count, setCount] = useState(0);
  const [statusCounts, setStatusCounts] = useState({});
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null); // null | "new" | enquiry obj
  const [confirmState, setConfirmState] = useState(null);
  const [filterStatus, setFilterStatus] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    try { document.getElementById("page-title").textContent = "Enquiries"; } catch { }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page };
      if (filterStatus) params.status = filterStatus;
      if (search) params.search = search;
      const res = await api.get("/enquiries/", { params });
      setEnquiries(Array.isArray(res.data) ? res.data : res.data?.results ?? []);
      setCount(res.data?.count ?? 0);
    } catch { toast.error("Failed to load enquiries."); }
    finally { setLoading(false); }
  }, [page, filterStatus, search]);

  // Status counts are across ALL enquiries (independent of page/search/filter),
  // so they're only refetched on mount and after a mutation, not on every keystroke.
  const loadCounts = useCallback(async () => {
    try {
      const res = await api.get("/enquiries/counts/");
      setStatusCounts(res.data || {});
    } catch { /* non-fatal — badges just keep their last known values */ }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadCounts(); }, [loadCounts]);

  const handleDelete = (enquiry) => {
    setConfirmState({
      title: "Delete Enquiry",
      message: `Delete enquiry for ${enquiry.name}? All scheduled follow-ups will also be removed.`,
      confirmText: "Delete",
      danger: true,
      onConfirm: async () => {
        setConfirmState(null);
        try {
          await api.delete(`/enquiries/${enquiry.id}/`);
          toast.success("Enquiry deleted.");
          load();
          loadCounts();
        } catch { toast.error("Delete failed."); }
      },
      onCancel: () => setConfirmState(null),
    });
  };

  // enquiries is already the server-filtered, server-paginated current page
  const filtered = enquiries;

  return (
    <div className="page">
      {confirmState && <ConfirmModal {...confirmState} />}

      <div className="page-header">
        <div>
          <h1 className="page-title">Enquiries</h1>
          <p className="page-sub">Track walk-in and call enquiries with automated WhatsApp follow-ups</p>
        </div>
        <button className="btn btn-primary" onClick={() => setModal("Follow-up")}>+ Add Enquiry</button>
      </div>

      {/* Summary badges — counts across ALL enquiries, from the server, not just this page */}
      <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
        {Object.entries(STATUS_LABELS).map(([k, v]) => (
          <span key={k} className={`badge ${v.cls}`} style={{ padding: "5px 14px", fontSize: 13 }}>
            {v.label}: {statusCounts[k] || 0}
          </span>
        ))}
        <span style={{ fontSize: 13, color: "var(--text-muted)", alignSelf: "center", marginLeft: 6 }}>
          Total: {statusCounts.total ?? count}
        </span>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
        <input
          className="form-input" style={{ width: 220 }}
          placeholder="Search name / phone…"
          value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
        />
        <select className="form-input" style={{ width: 180 }}
          value={filterStatus} onChange={e => { setFilterStatus(e.target.value); setPage(1); }}>
          <option value="">All Statuses</option>
          {Object.entries(STATUS_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v.label}</option>
          ))}
        </select>
        {(filterStatus || search) && (
          <button className="btn btn-ghost" onClick={() => { setFilterStatus(""); setSearch(""); setPage(1); }}>Clear</button>
        )}
      </div>

      {/* Mobile cards */}
      {!loading && filtered.length > 0 && (
        <div className="mobile-card-list">
          {filtered.map(e => {
            const s = STATUS_LABELS[e.status] || STATUS_LABELS.followup;
            return (
              <div key={e.id} className="mobile-card">
                <div className="mobile-card__left">
                  <span className="mobile-card__title">{e.name}</span>
                  <span className="mobile-card__meta" style={{ fontFamily: "var(--font-mono)" }}>
                    {e.phone}
                  </span>
                  {e.email && <span className="mobile-card__meta">{e.email}</span>}
                  <span style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                    <span className={`badge ${s.cls}`} style={{ fontSize: 11 }}>{s.label}</span>
                    <span className="mobile-card__meta">
                      Sent: {e.followups_sent} / Pending: {e.followups_pending}
                    </span>
                  </span>
                  <span className="mobile-card__meta">
                    Added: {new Date(e.created_at).toLocaleDateString("en-IN")}
                  </span>
                  {e.notes && (
                    <span className="mobile-card__meta" style={{ maxWidth: "100%" }}>
                      {e.notes}
                    </span>
                  )}
                </div>
                <div className="mobile-card__right">
                  <button className="btn btn-sm btn-ghost" onClick={() => setModal(e)}>Edit</button>
                  <button className="btn btn-sm btn-danger" onClick={() => handleDelete(e)}>Delete</button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="empty-state">Loading…</div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">◈</div>
          <div className="empty-state-title">No enquiries found</div>
          <div className="empty-state-sub">Click "Add Enquiry" to record a new walk-in or call.</div>
        </div>
      ) : (
        <div className="table-wrapper desktop-table-view">
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>Name</th>
                <th>Phone</th>
                <th>Email</th>
                <th>Status</th>
                <th>Follow-ups</th>
                <th>Added On</th>
                <th>Notes</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e, idx) => {
                const s = STATUS_LABELS[e.status] || STATUS_LABELS.followup;
                return (
                  <tr key={e.id}>
                    <td style={{ color: "var(--text-muted)", fontSize: 12 }}>{idx + 1}</td>
                    <td style={{ fontWeight: 600 }}>{e.name}</td>
                    <td style={{ fontFamily: "var(--font-mono)" }}>{e.phone}</td>
                    <td style={{ fontSize: 12, color: "var(--text-muted)" }}>{e.email || "—"}</td>
                    <td><span className={`badge ${s.cls}`}>{s.label}</span></td>
                    <td>
                      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        <span style={{ fontSize: 12 }}>
                          Sent: <strong>{e.followups_sent}</strong> / Pending: <strong>{e.followups_pending}</strong>
                        </span>
                        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                          (every 3 days × 10)
                        </span>
                      </div>
                    </td>
                    <td style={{ fontSize: 12, whiteSpace: "nowrap" }}>
                      {new Date(e.created_at).toLocaleDateString("en-IN")}
                    </td>
                    <td style={{
                      maxWidth: 180, fontSize: 12, color: "var(--text-muted)",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"
                    }}>
                      {e.notes || "—"}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        <button className="btn btn-sm btn-ghost" onClick={() => setModal(e)}>Edit</button>
                        <button className="btn btn-sm btn-danger" onClick={() => handleDelete(e)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {!loading && (enquiries.length > 0 || page > 1) && (
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "12px 16px", borderTop: "1px solid var(--border)",
        }}>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{count} total</span>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn btn-sm btn-secondary" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
            <button className="btn btn-sm btn-secondary" disabled={enquiries.length < 20} onClick={() => setPage(p => p + 1)}>Next →</button>
          </div>
        </div>
      )}

      {modal && (
        <EnquiryModal
          enquiry={modal === "Follow-up" ? null : modal}
          onClose={() => setModal(null)}
          onSave={() => { setModal(null); load(); loadCounts(); }}
        />
      )}
    </div>
  );
}
