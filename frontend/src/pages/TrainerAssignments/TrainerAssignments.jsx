import { useState, useEffect, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import api from "../../api/axios";
import toast from "react-hot-toast";
import ConfirmModal from "../../components/ConfirmModal";
import MemberBill from "../../components/MemberBill";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function daysFromStr(str) {
  if (!str) return [0, 1, 2, 3, 4, 5, 6];
  return str.split(",").map(Number).filter(n => !isNaN(n));
}
function daysToStr(arr) {
  return arr.slice().sort((a, b) => a - b).join(",");
}
const fmt = n => Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtD = n => Number(n || 0).toLocaleString("en-IN");

/* ─── PT Bill HTML builder ─────────────────────────────────────────────────── */
const PT_BILL_CSS = `
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:'Segoe UI',Arial,sans-serif;background:#f4f4f4;padding:32px 16px;color:#111}
  .page{max-width:660px;margin:0 auto;background:#fff;border-radius:12px;
        box-shadow:0 4px 24px rgba(0,0,0,.12);overflow:hidden}
  .header{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:24px 32px;text-align:center}
  .gym-name{font-size:20px;font-weight:800;letter-spacing:1px;margin-bottom:4px}
  .gym-sub{font-size:11px;color:rgba(255,255,255,.65);line-height:1.7}
  .gym-gstin{display:inline-block;margin-top:6px;background:rgba(168,188,136,.18);
    color:#A8BC88;border:1px solid rgba(168,188,136,.38);border-radius:100px;
    padding:2px 12px;font-size:11px;font-weight:700;letter-spacing:1px}
  .doc-title{background:#697254;color:#fff;text-align:center;padding:9px;
    font-size:12px;font-weight:800;letter-spacing:3px;text-transform:uppercase}
  .body{padding:22px 32px}
  .meta{display:flex;justify-content:space-between;margin-bottom:14px;
    padding-bottom:12px;border-bottom:1px solid #eee;flex-wrap:wrap;gap:8px}
  .inv-no{font-size:12px;font-weight:700;color:#444;margin-bottom:2px}
  .inv-date{font-size:11px;color:#888}
  .status-badge{display:inline-block;padding:3px 12px;border-radius:100px;font-size:10px;font-weight:800;letter-spacing:1px}
  .s-paid   {background:#e8fff0;color:#1a7a00;border:1px solid #b0e0c0}
  .s-partial{background:#fff8e0;color:#a06000;border:1px solid #e0c070}
  .s-pending{background:#fff0f0;color:#cc0000;border:1px solid #f0c0c0}
  .member-card{background:#f9f9f9;border-radius:8px;padding:12px 14px;margin-bottom:14px}
  .member-name{font-size:16px;font-weight:800;color:#111;margin-bottom:3px}
  .member-meta{font-size:11px;color:#666;line-height:1.7}
  .member-id{display:inline-block;background:#e8f0ff;color:#1a3a9a;border-radius:4px;
    padding:2px 7px;font-family:monospace;font-size:11px;font-weight:700}
  .pt-box{background:#f0f8ff;border:1px solid #b0d8f0;border-radius:8px;
    padding:12px 14px;margin-bottom:14px}
  .pt-title{font-size:13px;font-weight:800;color:#0a4a7a;margin-bottom:6px}
  .pt-dates{font-size:12px;color:#1a5a8a;line-height:1.8}
  .pt-days-badge{display:inline-block;background:#1a5a8a;color:#fff;border-radius:4px;
    padding:2px 10px;font-size:12px;font-weight:700;margin-left:6px}
  .billing{margin-bottom:14px}
  .b-row{display:flex;justify-content:space-between;align-items:center;
    padding:7px 0;border-bottom:1px solid #f0f0f0;font-size:12px;color:#555}
  .b-row:last-child{border-bottom:none}
  .b-row.gst .val{color:#e05000}
  .b-row.total{background:#f8f8f8;margin:4px -4px 0;padding:8px 4px;
    border-radius:6px;border-bottom:none}
  .b-row.total .lbl{font-size:13px;font-weight:800;color:#111}
  .b-row.total .val{font-size:16px;font-weight:800;color:#111}
  .b-row.paid  .val{color:#1a7a00;font-weight:800}
  .b-row.bal   .val{color:#cc0000;font-weight:800}
  .prorated-note{background:#fff8e8;border:1px solid #f0d090;border-radius:6px;
    padding:8px 12px;margin-bottom:12px;font-size:11px;color:#8a5000;line-height:1.6}
  .footer{text-align:center;padding:16px 32px;border-top:1px solid #eee;
    font-size:10px;color:#999;line-height:1.8;background:#fafafa}
  @media print{body{background:#fff;padding:0}.page{box-shadow:none;border-radius:0}}
`;

function buildPtBillHtml(b) {
  const statusCls = b.status === "paid" ? "s-paid" : b.status === "partial" ? "s-partial" : "s-pending";
  const isProrated = b.pt_days < b.full_pt_days;
  return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
    <title>PT Renewal Bill — ${b.member_name}</title>
    <style>${PT_BILL_CSS}</style></head><body>
    <div class="page">
      <div class="header">
        <div class="gym-name">${b.gym_name || "Gym"}</div>
        <div class="gym-sub">${b.gym_address || ""}${b.gym_phone ? " · " + b.gym_phone : ""}${b.gym_email ? " · " + b.gym_email : ""}</div>
        ${b.gym_gstin ? `<div class="gym-gstin">GSTIN: ${b.gym_gstin}</div>` : ""}
      </div>
      <div class="doc-title">Personal Training Renewal Receipt</div>
      <div class="body">
        <div class="meta">
          <div>
            <div class="inv-no">${b.invoice_number}</div>
            <div class="inv-date">Date: ${b.date}</div>
          </div>
          <div>
            <span class="status-badge ${statusCls}">${b.status.toUpperCase()}</span>
          </div>
        </div>

        <div class="member-card">
          <div class="member-name">${b.member_name}</div>
          <div class="member-meta">
            <span class="member-id">${b.member_id}</span>
            ${b.phone ? ` &nbsp;·&nbsp; ${b.phone}` : ""}
            ${b.email ? ` &nbsp;·&nbsp; ${b.email}` : ""}<br>
            Plan: <strong>${b.plan_name || "—"}</strong> &nbsp;·&nbsp; Plan valid till: <strong>${b.plan_valid_to}</strong><br>
            Trainer: <strong>${b.trainer_name}</strong> (${b.trainer_id})
          </div>
        </div>

        <div class="pt-box">
          <div class="pt-title">Personal Training Period</div>
          <div class="pt-dates">
            Start: <strong>${b.pt_start_date}</strong> &nbsp;&rarr;&nbsp; End: <strong>${b.pt_end_date}</strong>
            <span class="pt-days-badge">${b.pt_days} days</span>
          </div>
        </div>

        ${isProrated ? `<div class="prorated-note">
          <strong>Prorated PT Fee:</strong> Only ${b.pt_days} days remain in the membership plan.
          Fee calculated as ${b.pt_days}/${b.full_pt_days} of the full monthly PT fee.
        </div>` : ""}

        <div class="billing">
          <div class="b-row"><span class="lbl">PT Base Fee (${b.pt_days} days)</span><span class="val">&#8377;${fmt(b.base_amount)}</span></div>
          <div class="b-row gst"><span class="lbl">GST (${b.gst_rate}%)</span><span class="val">&#8377;${fmt(b.gst_amount)}</span></div>
          <div class="b-row total"><span class="lbl">Total Amount</span><span class="val">&#8377;${fmt(b.total_amount)}</span></div>
          <div class="b-row paid"><span class="lbl">Amount Paid</span><span class="val">&#8377;${fmt(b.amount_paid)}</span></div>
          ${parseFloat(b.balance) > 0 ? `<div class="b-row bal"><span class="lbl">Balance Due</span><span class="val">&#8377;${fmt(b.balance)}</span></div>` : ""}
        </div>
        ${b.mode_of_payment ? `<div style="font-size:11px;color:#888;margin-bottom:12px;">Mode of Payment: <strong style="color:#555">${b.mode_of_payment.toUpperCase()}</strong></div>` : ""}
        ${b.notes ? `<div style="font-size:11px;color:#888;margin-bottom:12px;background:#f5f5f5;border-radius:6px;padding:8px 12px;">Note: ${b.notes}</div>` : ""}
      </div>
      <div class="footer">
        Thank you for your continued commitment to your fitness journey!<br>
        <strong>${b.gym_name || "Gym"}</strong> — This is a computer-generated receipt.
      </div>
    </div>
  </body></html>`;
}

function downloadPtBill(bill) {
  const html  = buildPtBillHtml(bill);
  const blob  = new Blob([html], { type: "text/html" });
  const url   = URL.createObjectURL(blob);
  const a     = document.createElement("a");
  a.href      = url;
  a.download  = `PT-Renewal-${bill.member_name.replace(/\s+/g, "-")}-${bill.pt_start_date}.html`;
  a.click();
  URL.revokeObjectURL(url);
}

/* ─── PT Renewal Modal ─────────────────────────────────────────────────────── */
function PTRenewalModal({ assignment, onClose, onSave }) {
  const [preview, setPreview]         = useState(null);
  const [loadingPreview, setLP]       = useState(true);
  const [amountPaid, setAmountPaid]   = useState("");
  const [mode, setMode]               = useState("cash");
  const [notes, setNotes]             = useState("");
  const [saving, setSaving]           = useState(false);
  const [bill, setBill]               = useState(null);

  useEffect(() => {
    api.get(`/members/assign-trainer/${assignment.id}/pt-renewal-preview/`)
      .then(r => {
        setPreview(r.data);
        if (r.data.can_renew) setAmountPaid(String(r.data.total_amount || ""));
      })
      .catch(() => setPreview({ can_renew: false, reason: "Failed to load preview." }))
      .finally(() => setLP(false));
  }, [assignment.id]);

  const submit = async (e) => {
    e.preventDefault();
    if (!preview?.can_renew) return;
    setSaving(true);
    try {
      const res = await api.post(`/members/assign-trainer/${assignment.id}/renew-pt/`, {
        amount_paid:     parseFloat(amountPaid || 0),
        mode_of_payment: mode,
        notes,
      });
      const billData = res.data.bill;
      setBill(billData);
      toast.success(`PT renewed for ${preview.pt_days} days!`);
      // NOTE: don't call onSave() here — it would close the modal and hide the
      // bill-download success state. onSave() runs when the user clicks Close.
    } catch (err) {
      const d = err.response?.data;
      toast.error(d?.detail ?? "PT renewal failed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={bill ? undefined : onClose}>
      <div className="modal" style={{ maxWidth: 500 }} onClick={e => e.stopPropagation()}>
        <div className="modal-title">Renew Personal Training</div>

        {loadingPreview ? (
          <div style={{ textAlign: "center", padding: 32, color: "var(--text-muted)" }}>Loading…</div>
        ) : !preview?.can_renew ? (
          <>
            <div style={{
              background: "rgba(220,50,50,.08)", border: "1px solid rgba(220,50,50,.3)",
              borderRadius: 8, padding: "12px 14px", color: "#e05555", fontSize: 13, marginBottom: 16,
            }}>
              {preview?.reason || "Cannot renew PT at this time."}
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button className="btn btn-ghost" onClick={onClose}>Close</button>
            </div>
          </>
        ) : bill ? (
          /* ── Success state: show bill download ── */
          <>
            <div style={{
              background: "rgba(105,114,84,.10)", border: "1px solid rgba(105,114,84,.28)",
              borderRadius: 8, padding: "12px 14px", color: "var(--accent)", fontSize: 13, marginBottom: 16,
            }}>
              PT renewed successfully for <strong>{bill.pt_days} days</strong> ({bill.pt_start_date} → {bill.pt_end_date}).
            </div>

            {/* Summary */}
            <div style={{ background: "var(--card-bg)", border: "1px solid var(--border)", borderRadius: 8, padding: "12px 14px", marginBottom: 16, fontSize: 13 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <span style={{ color: "var(--text2)" }}>Total Amount</span>
                <span style={{ fontWeight: 700 }}>₹{fmt(bill.total_amount)}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <span style={{ color: "var(--text2)" }}>Amount Paid</span>
                <span style={{ fontWeight: 700, color: "var(--accent)" }}>₹{fmt(bill.amount_paid)}</span>
              </div>
              {parseFloat(bill.balance) > 0 && (
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "var(--text2)" }}>Balance Due</span>
                  <span style={{ fontWeight: 700, color: "#e05555" }}>₹{fmt(bill.balance)}</span>
                </div>
              )}
            </div>

            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button className="btn btn-ghost" onClick={onSave}>Close</button>
              <button className="btn btn-primary" onClick={() => downloadPtBill(bill)}>
                Download PT Bill
              </button>
            </div>
          </>
        ) : (
          /* ── Renewal form ── */
          <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {/* Member + trainer info */}
            <div style={{ background: "var(--card-bg)", border: "1px solid var(--border)", borderRadius: 8, padding: "10px 14px", fontSize: 13 }}>
              <div style={{ fontWeight: 600, color: "var(--text1)", marginBottom: 4 }}>
                {preview.member_name}
                <span style={{ fontSize: 11, marginLeft: 8, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>{preview.member_id}</span>
              </div>
              <div style={{ color: "var(--text2)", fontSize: 12, lineHeight: 1.7 }}>
                {preview.member_phone && <span>{preview.member_phone} &nbsp;·&nbsp; </span>}
                Trainer: <strong>{preview.trainer_name}</strong><br />
                Plan: <strong>{preview.plan_name || "—"}</strong> &nbsp;·&nbsp; Valid till: <strong>{preview.plan_valid_to}</strong>
              </div>
            </div>

            {/* PT period */}
            <div style={{ background: "rgba(100,160,255,.07)", border: "1px solid rgba(100,160,255,.2)", borderRadius: 8, padding: "10px 14px", fontSize: 13 }}>
              <div style={{ fontWeight: 600, color: "var(--text1)", marginBottom: 6 }}>PT Period</div>
              <div style={{ color: "var(--text2)", lineHeight: 1.8 }}>
                {preview.pt_start_date} &rarr; {preview.pt_end_date}
                <span style={{
                  marginLeft: 8, background: "var(--accent)", color: "#fff",
                  borderRadius: 4, padding: "2px 8px", fontSize: 11, fontWeight: 700,
                }}>
                  {preview.pt_days + (preview.current_pt_remaining || 0)} days
                </span>
              </div>
              {preview.current_pt_remaining > 0 && (
                <div style={{ marginTop: 6, fontSize: 11, color: "var(--accent)" }}>
                  +{preview.current_pt_remaining} bonus days carried over from current active period (paid for {preview.pt_days} days).
                </div>
              )}
              {preview.pt_days < 30 && (
                <div style={{ marginTop: 4, fontSize: 11, color: "#e09020" }}>
                  Only {preview.pt_days} of 30 days available — prorated to match remaining plan duration.
                </div>
              )}
            </div>

            {/* Amount breakdown */}
            <div style={{ background: "var(--card-bg)", border: "1px solid var(--border)", borderRadius: 8, padding: "12px 14px", fontSize: 13 }}>
              <div style={{ fontWeight: 600, color: "var(--text1)", marginBottom: 8 }}>Amount Breakdown</div>
              <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text2)", marginBottom: 4 }}>
                <span>PT Base Fee ({preview.pt_days} days)</span>
                <span style={{ fontFamily: "var(--font-mono)" }}>₹{fmt(preview.base_amount)}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text2)", marginBottom: 4 }}>
                <span>GST ({preview.gst_rate}%)</span>
                <span style={{ fontFamily: "var(--font-mono)", color: "#e09020" }}>₹{fmt(preview.gst_amount)}</span>
              </div>
              <div style={{
                display: "flex", justifyContent: "space-between", fontWeight: 700, color: "var(--accent)",
                borderTop: "1px solid var(--border)", paddingTop: 8, marginTop: 4,
              }}>
                <span>Total</span>
                <span style={{ fontFamily: "var(--font-mono)" }}>₹{fmt(preview.total_amount)}</span>
              </div>
            </div>

            {/* Payment collection */}
            <div style={{ display: "flex", gap: 8 }}>
              <div className="form-group" style={{ flex: 1 }}>
                <label className="form-label">Amount to Collect (₹)</label>
                <input
                  className="form-input"
                  type="number" onWheel={e => e.target.blur()}
                  min="0"
                  step="0.01"
                  value={amountPaid}
                  onChange={e => setAmountPaid(e.target.value)}
                  placeholder="0 to collect later"
                />
              </div>
              <div className="form-group" style={{ flex: 1 }}>
                <label className="form-label">Mode of Payment</label>
                <select className="form-input" value={mode} onChange={e => setMode(e.target.value)}>
                  <option value="cash">Cash</option>
                  <option value="card">Card</option>
                  <option value="upi">UPI</option>
                  <option value="other">Other</option>
                </select>
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Notes (optional)</label>
              <input className="form-input" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Optional note" />
            </div>

            <div style={{ fontSize: 11, color: "var(--text3)" }}>
              Leave amount as 0 to record the renewal now and collect payment later.
            </div>

            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 4 }}>
              <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving ? "Renewing…" : `Renew PT — ₹${fmt(parseFloat(amountPaid) || 0)}`}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

/* ─── Assignment Modal ─────────────────────────────────────────────────────── */
function AssignmentModal({ assignment, allMembers, trainers, plans, onClose, onSave, newMemberId, newPlanId, pendingMember, pendingRenewal, renewMemberId, prevType }) {
  const isEdit = !!assignment?.id;

  const eligibleMembers = allMembers.filter(m => m.plan_allows_trainer);
  const trainerPlans    = plans.filter(p => p.is_active !== false);

  const [form, setForm] = useState(() => {
    if (isEdit) {
      return {
        member: assignment.member,
        trainer: assignment.trainer,
        plan: assignment.plan ?? "",
        startingtime: assignment.startingtime?.slice(0, 5) ?? "06:00",
        endingtime: assignment.endingtime?.slice(0, 5) ?? "07:00",
        working_days: daysFromStr(assignment.working_days),
        pt_start_date: assignment.pt_start_date ?? "",
        pt_end_date: assignment.pt_end_date ?? "",
      };
    }
    if (pendingMember) {
      return {
        member: "",
        trainer: "",
        plan: pendingMember.plan || "",
        startingtime: "06:00", endingtime: "07:00",
        working_days: [0, 1, 2, 3, 4, 5, 6],
      };
    }
    return {
      member: newMemberId || "", trainer: "", plan: newPlanId || "",
      startingtime: "06:00", endingtime: "07:00",
      working_days: [0, 1, 2, 3, 4, 5, 6],
    };
  });

  const [saving, setSaving]                   = useState(false);
  const [ptAmountToCollect, setPtAmountToCollect] = useState("");
  const [modeOfPayment, setModeOfPayment]     = useState("cash");
  const [assignBill, setAssignBill]           = useState(null);
  const [dietBaseAmt, setDietBaseAmt]         = useState(0);
  const [gymGstRate, setGymGstRate]           = useState(18);
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));

  useEffect(() => {
    api.get("/finances/gym-settings/").then(r => {
      const s = r.data || {};
      if (s.DIET_PLAN_AMOUNT != null) setDietBaseAmt(parseFloat(s.DIET_PLAN_AMOUNT) || 0);
      if (s.GST_RATE != null) { const _r = parseFloat(s.GST_RATE); setGymGstRate(isNaN(_r) ? 18 : _r); }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (newMemberId && !isEdit) {
      const found = eligibleMembers.find(m => String(m.id) === String(newMemberId));
      // Prefer explicit planId from URL, fall back to member's current plan
      if (newPlanId) set("plan", newPlanId);
      else if (found?.plan) set("plan", found.plan);
    }
  }, [newMemberId, newPlanId, eligibleMembers, isEdit]);

  const handleMemberChange = (memberId) => {
    set("member", memberId);
    if (!memberId) return;
    const found = eligibleMembers.find(m => String(m.id) === String(memberId));
    if (found?.plan) set("plan", found.plan);
  };

  const selectedTrainer   = trainers.find(t => String(t.id) === String(form.trainer));
  const selectedMemberObj = allMembers.find(m => String(m.id) === String(form.member));
  const memberPlanId      = pendingMember ? pendingMember.plan
                          : (pendingRenewal?.plan_id || newPlanId || selectedMemberObj?.plan);
  const memberPlan        = plans.find(p => String(p.id) === String(memberPlanId));
  // Use discounted plan price — from pendingMember/pendingRenewal flows or from member's latest payment (edit upgrade flow)
  const pendingDiscountAmt = parseFloat(
    pendingMember?.discount_amount ||
    pendingRenewal?.discount_amount ||
    selectedMemberObj?.latest_discount_amount ||
    0
  );
  const planBasePrice      = parseFloat(memberPlan?.price ?? 0);
  const planBaseAfterDiscount = Math.max(0, planBasePrice - pendingDiscountAmt);
  const planWithGst        = pendingDiscountAmt > 0
    ? parseFloat((planBaseAfterDiscount * (1 + gymGstRate / 100)).toFixed(2))
    : parseFloat(memberPlan?.price_with_gst ?? memberPlan?.price ?? 0);
  const ptFee             = parseFloat(selectedTrainer?.personal_trainer_amt ?? 0);

  // Prorate PT fee by actual days that will be assigned (same logic as PT renewal)
  // For deferred renewal: member hasn't been renewed yet, so estimate future renewal date
  // from the plan's duration_days (renewal will set renewal_date = today + duration_days)
  const memberRenewalDate = (() => {
    if (pendingMember?.renewal_date) return pendingMember.renewal_date;
    if (pendingRenewal && memberPlan?.duration_days) {
      const future = new Date();
      future.setDate(future.getDate() + memberPlan.duration_days);
      return future.toISOString().slice(0, 10);
    }
    return selectedMemberObj?.renewal_date;
  })();
  const ptDays = (() => {
    if (!memberRenewalDate) return 30;
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const renewal = new Date(memberRenewalDate); renewal.setHours(0, 0, 0, 0);
    const daysLeft = Math.round((renewal - today) / 86400000);
    return Math.min(30, Math.max(0, daysLeft));
  })();
  const proratedPtFee    = ptDays < 30 ? parseFloat((ptFee / 30 * ptDays).toFixed(2)) : ptFee;
  const ptFeeGst         = parseFloat((proratedPtFee * gymGstRate / 100).toFixed(2));
  const ptFeeWithGst     = proratedPtFee + ptFeeGst;

  // Determine if the member being assigned includes a diet fee.
  // For new enrollment / renewal: check plan_type (diet fee is collected regardless of chart assignment).
  // For edit upgrades (newMemberId): prevType tells us what was already collected.
  //   - prevType "dietonly-standard" → diet was already charged; only collect PT now.
  //   - prevType "basic" or "standard" → diet not yet collected; collect it now if plan is premium.
  const memberHasDiet = pendingMember
    ? (pendingMember.plan_type === "premium" || pendingMember.plan_type === "dietonly-standard")
    : pendingRenewal
      ? (pendingRenewal.plan_type === "premium" || pendingRenewal.plan_type === "dietonly-standard")
      : (() => {
          if (prevType === "dietonly-standard") return false; // diet already collected
          if (selectedMemberObj?.plan_type === "premium" || selectedMemberObj?.plan_type === "dietonly-standard") return true;
          return Boolean(selectedMemberObj?.diet_id);
        })();
  const proratedDietBaseAmt = memberHasDiet && ptDays < 30
    ? parseFloat((dietBaseAmt / 30 * ptDays).toFixed(2))
    : dietBaseAmt;
  const dietWithGst = memberHasDiet
    ? parseFloat((proratedDietBaseAmt * (1 + gymGstRate / 100)).toFixed(2))
    : 0;

  // For new enrollment (pendingMember): diet was already collected with plan fee at enrollment.
  //   → collect PT fee only at this step.
  // For existing member upgrade (newMemberId): plan already paid, collect only what's new.
  //   - basic→premium: collect PT + diet now.
  //   - dietonly-standard→premium: collect PT only (diet was already charged).
  const isEditUpgrade = !!newMemberId && !pendingMember && !pendingRenewal;
  const feesToCollect = pendingMember || pendingRenewal
    ? ptFeeWithGst
    : ptFeeWithGst + dietWithGst;

  // Grand total for information: for edit upgrades, only show what's being added (no plan amount)
  const grandTotal = isEditUpgrade
    ? ptFeeWithGst + dietWithGst
    : planWithGst + ptFeeWithGst + dietWithGst;

  useEffect(() => {
    if (feesToCollect > 0) setPtAmountToCollect(feesToCollect.toFixed(2));
    else setPtAmountToCollect("");
  }, [form.trainer, feesToCollect]);

  const toggleDay = (idx) => {
    set("working_days",
      form.working_days.includes(idx)
        ? form.working_days.filter(d => d !== idx)
        : [...form.working_days, idx]
    );
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!pendingMember && !renewMemberId && !form.member) { toast.error("Member is required."); return; }
    if (!form.trainer)                  { toast.error("Trainer is required."); return; }
    if (form.working_days.length === 0) { toast.error("Select at least one working day."); return; }
    setSaving(true);
    try {
      if (isEdit) {
        const payload = {
          member:       Number(form.member),
          trainer:      Number(form.trainer),
          plan:         form.plan ? Number(form.plan) : null,
          startingtime: form.startingtime,
          endingtime:   form.endingtime,
          working_days: daysToStr(form.working_days),
        };
        if (form.pt_start_date) payload.pt_start_date = form.pt_start_date;
        if (form.pt_end_date)   payload.pt_end_date   = form.pt_end_date;
        await api.patch(`/members/assign-trainer/${assignment.id}/`, payload);
        toast.success("Assignment updated!");
        onSave();
      } else if (pendingMember) {
        // Step 1: Create the member
        const mRes = await api.post("/members/list/", {
          name:            pendingMember.name,
          phone:           pendingMember.phone,
          email:           pendingMember.email || "",
          gender:          pendingMember.gender || "",
          address:         pendingMember.address || "",
          notes:           pendingMember.notes || "",
          age:             pendingMember.age || undefined,
          plan_id:         pendingMember.plan || undefined,
          diet_id:         pendingMember.diet || undefined,
          foodType:        pendingMember.foodType || "veg",
          plan_type:       pendingMember.plan_type,
          personal_trainer: true,
          amount_paid:     pendingMember.amount_paid || 0,
          mode_of_payment: pendingMember.mode_of_payment || "cash",
          renewal_date:    pendingMember.renewal_date || undefined,
          status:          pendingMember.status || "active",
          discount_amount: pendingMember.discount_amount || 0,
        });
        const createdMemberId = mRes.data.id;

        // Step 2: Assign trainer with combined enrollment + PT fee
        const collectAmt = parseFloat(ptAmountToCollect || 0);
        const enrollAmt  = parseFloat(pendingMember.amount_paid || 0);
        const combined   = enrollAmt + collectAmt;

        const aRes = await api.post("/members/assign-trainer/", {
          member:          createdMemberId,
          trainer:         Number(form.trainer),
          plan:            form.plan ? Number(form.plan) : null,
          startingtime:    form.startingtime,
          endingtime:      form.endingtime,
          working_days:    daysToStr(form.working_days),
          amount_paid:     collectAmt,
          mode_of_payment: modeOfPayment,
          notes:           pendingMember.notes || "",
        });

        toast.success(
          collectAmt > 0
            ? `Member enrolled & trainer assigned! ₹${fmtD(collectAmt)} recorded.`
            : "Member enrolled & trainer assigned!"
        );
        sessionStorage.removeItem("pendingMember");
        if (aRes.data?.bill) {
          setAssignBill(aRes.data.bill);
          return;
        }
        onSave();
      } else if (pendingRenewal && renewMemberId) {
        // Deferred renewal + trainer assignment flow
        // Step 1: Execute the deferred renewal
        const renewRes = await api.post(`/members/list/${renewMemberId}/renew/`, {
          plan_id:         pendingRenewal.plan_id,
          plan_type:       pendingRenewal.plan_type,
          diet_id:         pendingRenewal.diet_id,
          amount_paid:     pendingRenewal.amount_paid,
          notes:           pendingRenewal.notes || "",
          mode_of_payment: pendingRenewal.mode_of_payment || "cash",
          discount_amount: pendingRenewal.discount_amount || 0,
        });

        // Step 2: Assign trainer (include PT fee so backend handles it in one transaction)
        const collectAmt = parseFloat(ptAmountToCollect || 0);
        const aRes = await api.post("/members/assign-trainer/", {
          member:          Number(renewMemberId),
          trainer:         Number(form.trainer),
          plan:            form.plan ? Number(form.plan) : null,
          startingtime:    form.startingtime,
          endingtime:      form.endingtime,
          working_days:    daysToStr(form.working_days),
          amount_paid:     collectAmt,
          mode_of_payment: modeOfPayment,
          notes:           "PT fee collected at renewal upgrade",
        });

        toast.success(
          collectAmt > 0
            ? `Renewed & trainer assigned! ₹${fmtD(collectAmt)} PT fee recorded.`
            : "Renewed & trainer assigned!"
        );
        sessionStorage.removeItem("pendingRenewal");
        if (aRes.data?.bill) {
          setAssignBill(aRes.data.bill);
          return;
        }
        onSave();
      } else {
        // Existing member flow (non-renewal)
        const collectAmt = parseFloat(ptAmountToCollect || 0);
        const aRes = await api.post("/members/assign-trainer/", {
          member:          Number(form.member),
          trainer:         Number(form.trainer),
          plan:            form.plan ? Number(form.plan) : null,
          startingtime:    form.startingtime,
          endingtime:      form.endingtime,
          working_days:    daysToStr(form.working_days),
          amount_paid:     collectAmt,
          mode_of_payment: modeOfPayment,
          notes:           collectAmt > 0 ? "PT fee collected at assignment" : "",
        });

        toast.success(
          collectAmt > 0
            ? `Trainer assigned! ₹${fmtD(collectAmt)} PT fee recorded.`
            : "Trainer assigned!"
        );
        if (aRes.data?.bill) {
          const raw = aRes.data.bill;
          const ptBase   = parseFloat(raw.pt_fee || 0);
          // Only include diet in the bill if we actually collected it at this step.
          // For dietonly-standard → premium, diet was already collected; memberHasDiet = false.
          const dietBase = memberHasDiet ? parseFloat(raw.diet_plan_amount || 0) : 0;
          const addBase  = ptBase + dietBase;
          const gstAmt   = parseFloat((addBase * raw.gst_rate / 100).toFixed(2));
          const addTotal = parseFloat((addBase + gstAmt).toFixed(2));
          const paid     = Math.min(collectAmt, addTotal);
          const bal      = parseFloat(Math.max(0, addTotal - paid).toFixed(2));
          setAssignBill({
            ...raw,
            is_pt_upgrade:    true,
            plan_name:        "",      // hide plan info box — only show what's being added now
            membership_fee:   0,
            discount_amount:  0,       // hide discount rows from prior enrollment
            diet_plan_amount: dietBase, // reflect only what's being charged now
            plan_price:       addBase,
            gst_amount:       gstAmt,
            total_with_gst:   addTotal,
            amount_paid:      paid,
            balance:          bal,
          });
          return;
        }
        onSave();
      }
    } catch (err) {
      const d = err.response?.data;
      toast.error(d?.detail ?? (typeof d === "object" ? Object.values(d).flat().join(" ") : "Something went wrong"));
    } finally {
      setSaving(false);
    }
  };

  if (assignBill) {
    return <MemberBill bill={assignBill} onClose={() => { setAssignBill(null); onSave(); }} />;
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 520 }} onClick={e => e.stopPropagation()}>
        <div className="modal-title">{isEdit ? "Edit Assignment" : "Assign Trainer"}</div>

        {pendingMember && (
          <div style={{
            background: "rgba(105,114,84,.10)", color: "var(--accent)",
            border: "1px solid rgba(105,114,84,.28)", borderRadius: 8, padding: "10px 14px",
            marginBottom: 14, fontSize: 13,
          }}>
            Completing enrollment for <strong>{pendingMember.name}</strong> — assign a trainer below.
          </div>
        )}

        {pendingRenewal && selectedMemberObj && (
          <div style={{
            background: "rgba(78,124,96,.10)", color: "var(--teal)",
            border: "1px solid rgba(78,124,96,.28)", borderRadius: 8, padding: "10px 14px",
            marginBottom: 14, fontSize: 13,
          }}>
            Renewing <strong>{selectedMemberObj.name}</strong> with plan upgrade — assign a trainer to complete renewal.
            <br /><span style={{ fontSize: 11, color: "var(--text-muted)" }}>Cancelling will discard the renewal.</span>
          </div>
        )}

        {!pendingMember && !isEdit && eligibleMembers.length === 0 && (
          <div style={{
            background: "var(--badge-yellow-bg, #fef3c7)", color: "#92400e",
            border: "1px solid #fcd34d", borderRadius: 8, padding: "10px 14px",
            marginBottom: 14, fontSize: 13,
          }}>
            No eligible members found. Members need a <strong>Standard</strong> or <strong>Premium</strong> plan
            with <strong>Personal Trainer</strong> enabled.
          </div>
        )}

        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {/* Member */}
          <div className="form-group">
            <label className="form-label">
              Member *
              {!isEdit && !pendingMember && (
                <span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: 6 }}>
                  (Standard / Premium plans only)
                </span>
              )}
            </label>
            {isEdit ? (
              <input className="form-input" value={assignment.member_name} disabled />
            ) : pendingMember ? (
              <div style={{ background: "var(--card-bg)", border: "1px solid var(--border)", borderRadius: 8, padding: "10px 14px", fontSize: 13 }}>
                <div style={{ fontWeight: 600, color: "var(--text1)" }}>{pendingMember.name}</div>
                <div style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 2 }}>
                  {pendingMember.phone}
                  {memberPlan ? ` · ${memberPlan.name}` : ""}
                  {" · "}<span style={{ textTransform: "capitalize" }}>{pendingMember.plan_type}</span>
                </div>
              </div>
            ) : renewMemberId && selectedMemberObj ? (
              <div style={{ background: "var(--card-bg)", border: "1px solid var(--border)", borderRadius: 8, padding: "10px 14px", fontSize: 13 }}>
                <div style={{ fontWeight: 600, color: "var(--text1)" }}>{selectedMemberObj.name}</div>
                <div style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 2 }}>
                  {selectedMemberObj.phone}
                  {memberPlan ? ` · ${memberPlan.name}` : ""}
                  {" · Upgrading to "}<span style={{ textTransform: "capitalize" }}>{pendingRenewal?.plan_type || "standard"}</span>
                </div>
              </div>
            ) : (
              <select className="form-input" value={form.member} onChange={e => handleMemberChange(e.target.value)} required>
                <option value="">— Select eligible member —</option>
                {eligibleMembers.map(m => (
                  <option key={m.id} value={m.id}>{m.member_id_display} — {m.name} ({m.plan_name})</option>
                ))}
              </select>
            )}
          </div>

          {/* Trainer */}
          <div className="form-group">
            <label className="form-label">Trainer *</label>
            <select className="form-input" value={form.trainer} onChange={e => set("trainer", e.target.value)} required>
              <option value="">— Select trainer —</option>
              {trainers.map(t => (
                <option key={t.id} value={t.id}>S{String(t.id).padStart(4, "0")} — {t.name}</option>
              ))}
            </select>
            {trainers.length === 0 && (
              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>No active trainers found.</span>
            )}
          </div>

          {/* Plan */}
          <div className="form-group">
            <label className="form-label">
              Plan
              <span style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: 6 }}>(Standard / Premium with PT)</span>
            </label>
            <select className="form-input" value={form.plan} onChange={e => set("plan", e.target.value)}>
              <option value="">— No specific plan —</option>
              {trainerPlans.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>

          {/* Time slot */}
          <div className="grid-2">
            <div className="form-group">
              <label className="form-label">Start Time *</label>
              <input className="form-input" type="time" value={form.startingtime}
                onChange={e => set("startingtime", e.target.value)} required />
            </div>
            <div className="form-group">
              <label className="form-label">End Time *</label>
              <input className="form-input" type="time" value={form.endingtime}
                onChange={e => set("endingtime", e.target.value)} required />
            </div>
          </div>

          {/* Working days */}
          <div className="form-group">
            <label className="form-label">Working Days *</label>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
              {DAYS.map((day, idx) => (
                <label key={idx} style={{
                  display: "flex", alignItems: "center", gap: 4,
                  padding: "4px 12px", borderRadius: 6, cursor: "pointer", fontSize: 13,
                  background: form.working_days.includes(idx) ? "var(--accent)" : "var(--card-bg)",
                  color: form.working_days.includes(idx) ? "#fff" : "var(--text-muted)",
                  border: "1px solid var(--border)",
                  userSelect: "none", transition: "background 0.15s",
                }}>
                  <input type="checkbox" style={{ display: "none" }}
                    checked={form.working_days.includes(idx)} onChange={() => toggleDay(idx)} />
                  {day}
                </label>
              ))}
            </div>
          </div>

          {/* PT Period — edit only */}
          {isEdit && (
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text2)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                PT Period Override
              </div>
              <div className="grid-2">
                <div className="form-group">
                  <label className="form-label">PT Start Date</label>
                  <input
                    className="form-input"
                    type="date"
                    value={form.pt_start_date}
                    onChange={e => set("pt_start_date", e.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">PT End Date (Expiry)</label>
                  <input
                    className="form-input"
                    type="date"
                    value={form.pt_end_date}
                    onChange={e => set("pt_end_date", e.target.value)}
                  />
                </div>
              </div>
              {form.pt_start_date && form.pt_end_date && (
                <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                  {(() => {
                    const days = Math.ceil((new Date(form.pt_end_date) - new Date(form.pt_start_date)) / 86400000);
                    return days > 0 ? `${days} day${days !== 1 ? "s" : ""} PT period` : "End must be after start";
                  })()}
                </div>
              )}
              <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 4 }}>
                Use this to manually adjust the PT expiry for testing or corrections.
              </div>
            </div>
          )}

          {/* Amount breakdown */}
          {form.trainer && (isEditUpgrade ? (ptFeeWithGst > 0 || dietWithGst > 0) : planWithGst > 0) && (
            <div style={{ background: "var(--card-bg)", border: "1px solid var(--border)", borderRadius: 8, padding: "12px 14px", fontSize: 13 }}>
              <div style={{ fontWeight: 600, marginBottom: 8, color: "var(--text1)" }}>
                {isEditUpgrade ? "Fees Being Added" : "Amount Breakdown"}
              </div>
              {/* Plan amount — only for new enrollment / renewal, not for edit upgrades */}
              {!isEditUpgrade && (pendingDiscountAmt > 0 ? (
                <>
                  <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text2)", marginBottom: 4 }}>
                    <span>Plan Price (Original)</span>
                    <span style={{ fontFamily: "var(--font-mono)" }}>₹{fmtD(parseFloat((planBasePrice * (1 + gymGstRate / 100)).toFixed(2)))}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", color: "var(--accent)", marginBottom: 4 }}>
                    <span>Discount</span>
                    <span style={{ fontFamily: "var(--font-mono)" }}>- ₹{fmtD(pendingDiscountAmt)}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text1)", fontWeight: 700, marginBottom: 4, borderTop: "1px dashed var(--border)", paddingTop: 6 }}>
                    <span>Plan after Discount (incl. GST)</span>
                    <span style={{ fontFamily: "var(--font-mono)" }}>₹{fmtD(planWithGst)}</span>
                  </div>
                </>
              ) : (
                <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text2)", marginBottom: 4 }}>
                  <span>Plan (incl. GST)</span>
                  <span style={{ fontFamily: "var(--font-mono)" }}>₹{fmtD(planWithGst)}</span>
                </div>
              ))}
              {ptFee > 0 && (
                <>
                  <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text2)", marginBottom: 4 }}>
                    <span>Personal Trainer Fee (base{ptDays < 30 ? `, ${ptDays} days` : ""})</span>
                    <span style={{ fontFamily: "var(--font-mono)" }}>₹{fmtD(proratedPtFee)}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text2)", marginBottom: 4 }}>
                    <span>GST on PT Fee ({gymGstRate}%)</span>
                    <span style={{ fontFamily: "var(--font-mono)" }}>₹{fmtD(ptFeeGst)}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text2)", marginBottom: 4 }}>
                    <span>Personal Trainer Fee (incl. GST)</span>
                    <span style={{ fontFamily: "var(--font-mono)" }}>₹{fmtD(ptFeeWithGst)}</span>
                  </div>
                </>
              )}
              {dietWithGst > 0 && (
                <div style={{ display: "flex", justifyContent: "space-between", color: "var(--teal)", marginBottom: 4 }}>
                  <span>Diet Plan (incl. GST{ptDays < 30 ? `, ${ptDays} days` : ""}{(pendingMember || pendingRenewal) ? " — collected at enrollment" : ""})</span>
                  <span style={{ fontFamily: "var(--font-mono)" }}>₹{fmtD(dietWithGst)}</span>
                </div>
              )}
              <div style={{
                display: "flex", justifyContent: "space-between",
                fontWeight: 700, color: "var(--accent)",
                borderTop: "1px solid var(--border)", paddingTop: 8, marginTop: 4,
              }}>
                <span>{isEditUpgrade ? "Total to Collect" : "Grand Total"}</span>
                <span style={{ fontFamily: "var(--font-mono)" }}>₹{fmtD(grandTotal)}</span>
              </div>
              {ptFee === 0 && (
                <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 6 }}>
                  This trainer has no PT fee set. Add one in Staff settings.
                </div>
              )}

              {!isEdit && feesToCollect > 0 && (
                <div style={{ marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
                  <div style={{ fontWeight: 600, marginBottom: 4, color: "var(--text1)" }}>
                    {isEditUpgrade && dietWithGst > 0
                      ? "Collect PT + Diet Fee Now"
                      : (pendingMember || pendingRenewal) && dietWithGst > 0
                        ? "Collect PT Fee Now (Diet collected at enrollment)"
                        : "Collect PT Fee Now"}
                  </div>
                  {isEditUpgrade && dietWithGst > 0 && (
                    <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 8 }}>
                      PT ₹{fmtD(ptFeeWithGst)} + Diet ₹{fmtD(dietWithGst)} = ₹{fmtD(feesToCollect)}
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 8 }}>
                    <div style={{ flex: 1 }}>
                      <label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>Amount (₹)</label>
                      <input className="form-input" type="number" onWheel={e => e.target.blur()} min="0" max={feesToCollect}
                        value={ptAmountToCollect} onChange={e => setPtAmountToCollect(e.target.value)}
                        placeholder="0 to collect later" />
                    </div>
                    <div style={{ flex: 1 }}>
                      <label style={{ fontSize: 11, color: "var(--text3)", display: "block", marginBottom: 4 }}>Mode</label>
                      <select className="form-input" value={modeOfPayment} onChange={e => setModeOfPayment(e.target.value)}>
                        <option value="cash">Cash</option>
                        <option value="card">Card</option>
                        <option value="upi">UPI</option>
                        <option value="other">Other</option>
                      </select>
                    </div>
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 4 }}>Leave 0 to collect later via Payments.</div>
                </div>
              )}
            </div>
          )}

          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 4 }}>
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? "Saving…" : isEdit ? "Update" : pendingMember ? "Enroll & Assign Trainer" : "Assign Trainer"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ─── PT Balance Modal ─────────────────────────────────────────────────────── */
function PTBalanceModal({ assignment, onClose, onSave }) {
  const balance = assignment.pending_pt_balance || 0;
  const [amountPaid, setAmountPaid] = useState(String(balance));
  const [mode, setMode]             = useState("cash");
  const [notes, setNotes]           = useState("");
  const [saving, setSaving]         = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    const amt = parseFloat(amountPaid || 0);
    if (amt <= 0) { toast.error("Enter a valid amount."); return; }
    setSaving(true);
    try {
      await api.post(`/members/assign-trainer/${assignment.id}/pay-pt-balance/`, {
        amount_paid:     amt,
        mode_of_payment: mode,
        notes,
      });
      toast.success(`₹${fmt(amt)} PT balance recorded.`);
      onSave();
    } catch (err) {
      toast.error(err.response?.data?.detail ?? "Payment failed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 420 }} onClick={e => e.stopPropagation()}>
        <div className="modal-title">Pay PT Renewal Balance</div>
        <div style={{ fontSize: 13, color: "var(--text2)", marginBottom: 16 }}>
          Outstanding balance: <strong style={{ color: "#e05555" }}>₹{fmt(balance)}</strong>
          {assignment.pending_pt_balance_invoice && (
            <span style={{ marginLeft: 8, fontSize: 11, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
              ({assignment.pending_pt_balance_invoice})
            </span>
          )}
        </div>
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <div className="form-group" style={{ flex: 1 }}>
              <label className="form-label">Amount (₹)</label>
              <input
                className="form-input"
                type="number" onWheel={e => e.target.blur()}
                min="0.01"
                max={balance}
                step="0.01"
                value={amountPaid}
                onChange={e => setAmountPaid(e.target.value)}
                required
              />
            </div>
            <div className="form-group" style={{ flex: 1 }}>
              <label className="form-label">Mode of Payment</label>
              <select className="form-input" value={mode} onChange={e => setMode(e.target.value)}>
                <option value="cash">Cash</option>
                <option value="card">Card</option>
                <option value="upi">UPI</option>
                <option value="other">Other</option>
              </select>
            </div>
          </div>
          <div className="form-group">
            <label className="form-label">Notes (optional)</label>
            <input className="form-input" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Optional note" />
          </div>
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? "Saving…" : `Pay ₹${fmt(parseFloat(amountPaid) || 0)}`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ─── PT Status badge helper ───────────────────────────────────────────────── */
function PTStatusBadge({ assignment }) {
  const days = assignment.pt_days_remaining;
  const canRenew = assignment.can_renew_pt;

  if (days === null || days === undefined) {
    // No PT dates yet (legacy assignment)
    return (
      <span style={{ color: "var(--text-muted)", fontSize: 11 }}>—</span>
    );
  }

  if (days > 0) {
    const urgency = days <= 5 ? "#e09020" : days <= 10 ? "#c07000" : "var(--accent)";
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span className="badge badge-green" style={{ fontSize: 11 }}>Active</span>
        <span style={{ fontSize: 11, color: urgency, fontWeight: days <= 5 ? 700 : 400 }}>
          {days} day{days !== 1 ? "s" : ""} left
        </span>
        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
          Expires: {assignment.pt_end_date}
        </span>
      </div>
    );
  }

  // Expired
  const expiredDays = Math.abs(days);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span className="badge badge-red" style={{ fontSize: 11 }}>
        {canRenew ? "PT Expired" : "PT Expired"}
      </span>
      <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
        {expiredDays} day{expiredDays !== 1 ? "s" : ""} ago
      </span>
    </div>
  );
}

/* ─── Main Page ────────────────────────────────────────────────────────────── */
export default function TrainerAssignments() {
  const navigate = useNavigate();
  const location = useLocation();
  const urlParams   = new URLSearchParams(location.search);
  const newMemberId   = urlParams.get("newMember");
  const newPlanId     = urlParams.get("planId");
  const fromPage      = urlParams.get("from");
  const isPending     = urlParams.get("pending") === "1";
  const prevType      = urlParams.get("prevType");
  const isRenewUpgrade = urlParams.get("renewUpgrade") === "1";

  const [assignments, setAssignments]   = useState([]);
  const [count, setCount]               = useState(0);
  const [page, setPage]                 = useState(1);
  const [search, setSearch]             = useState("");
  const [allMembers, setAllMembers]     = useState([]);
  const [trainers, setTrainers]         = useState([]);
  const [plans, setPlans]               = useState([]);
  const [loading, setLoading]           = useState(true);
  const [modal, setModal]               = useState(null);       // null | "new" | assignment obj
  const [ptRenewalModal, setPtRenewalModal] = useState(null);   // null | assignment obj
  const [ptBalanceModal, setPtBalanceModal] = useState(null);   // null | assignment obj
  const [filterMember, setFilterMember] = useState("");
  const [filterTrainer, setFilterTrainer] = useState("");
  const [confirmState, setConfirmState] = useState(null);
  const [pendingMember, setPendingMember] = useState(null);
  const [pendingRenewal, setPendingRenewal] = useState(null);

  const eligibleMembers = allMembers.filter(m => m.plan_allows_trainer);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page };
      if (filterMember)  params.member  = filterMember;
      if (filterTrainer) params.trainer = filterTrainer;
      if (search)        params.search  = search;
      const res = await api.get("/members/assign-trainer/", { params });
      const raw = res.data;
      setAssignments(Array.isArray(raw) ? raw : raw?.results ?? []);
      setCount(raw?.count ?? (Array.isArray(raw) ? raw.length : 0));
    } catch {
      toast.error("Failed to load assignments.");
    } finally {
      setLoading(false);
    }
  }, [page, filterMember, filterTrainer, search]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const fetches = [
      api.get("/members/list/", { params: { status: "active", page_size: 9999 } }),
      api.get("/staff/members/", { params: { role: "trainer", status: "active" } }),
      api.get("/members/plans/"),
    ];
    // For renewUpgrade the member is still basic — ensure we fetch them specifically
    if (newMemberId) {
      fetches.push(api.get(`/members/list/${newMemberId}/`).catch(() => null));
    }
    Promise.all(fetches).then(([mRes, tRes, pRes, specificMemberRes]) => {
      const get = r => Array.isArray(r.data) ? r.data : r.data?.results ?? [];
      let members = get(mRes);
      // Ensure the specific member is included in the list
      if (specificMemberRes?.data && !members.find(m => m.id === specificMemberRes.data.id)) {
        members = [...members, specificMemberRes.data];
      }
      setAllMembers(members);
      setTrainers(get(tRes));
      setPlans(get(pRes));
    }).catch(() => toast.error("Failed to load reference data."));
  }, []);

  useEffect(() => {
    if (newMemberId && allMembers.length > 0) setModal("new");
  }, [newMemberId, allMembers]);

  useEffect(() => {
    if (isPending) {
      const stored = sessionStorage.getItem("pendingMember");
      if (stored) {
        try {
          setPendingMember(JSON.parse(stored));
          setModal("new");
        } catch {
          sessionStorage.removeItem("pendingMember");
        }
      }
    }
  }, [isPending]);

  useEffect(() => {
    if (isRenewUpgrade && newMemberId) {
      const stored = sessionStorage.getItem("pendingRenewal");
      if (stored) {
        try {
          setPendingRenewal(JSON.parse(stored));
        } catch {
          sessionStorage.removeItem("pendingRenewal");
        }
      }
    }
  }, [isRenewUpgrade, newMemberId]);

  const handlePayPtTrainerFee = (assignment) => {
    const pending = assignment.pending_pt_renewal_trainer_amount || 0;
    setConfirmState({
      title:       "Pay PT Renewal Trainer Fee",
      message:     `Pay ₹${pending.toLocaleString("en-IN", { minimumFractionDigits: 2 })} to ${assignment.trainer_name} for all pending PT renewal periods? This will be recorded as an expense.`,
      confirmText: "Pay",
      danger:      false,
      onConfirm: async () => {
        setConfirmState(null);
        try {
          await api.post(`/members/assign-trainer/${assignment.id}/pay-pt-trainer-fee/`);
          toast.success(`₹${pending.toLocaleString("en-IN")} PT renewal fee paid to ${assignment.trainer_name}.`);
          load();
        } catch (err) {
          toast.error(err.response?.data?.detail || "Payment failed.");
        }
      },
      onCancel: () => setConfirmState(null),
    });
  };

  const handlePayTrainerFee = (assignment) => {
    setConfirmState({
      title:       "Pay Trainer Fee",
      message:     `Pay ₹${(assignment.trainer_pt_amt || 0).toLocaleString("en-IN")} to ${assignment.trainer_name} for ${assignment.member_name}? This will be recorded as an expense.`,
      confirmText: "Pay",
      danger:      false,
      onConfirm: async () => {
        setConfirmState(null);
        try {
          await api.post(`/members/assign-trainer/${assignment.id}/pay-trainer-fee/`);
          toast.success(`₹${(assignment.trainer_pt_amt || 0).toLocaleString("en-IN")} paid to ${assignment.trainer_name}.`);
          load();
        } catch (err) {
          toast.error(err.response?.data?.detail || "Payment failed.");
        }
      },
      onCancel: () => setConfirmState(null),
    });
  };

  const handleDelete = (id) => {
    setConfirmState({
      title:       "Delete Assignment",
      message:     "Delete this trainer assignment?",
      confirmText: "Delete",
      danger:      true,
      onConfirm: async () => {
        setConfirmState(null);
        try {
          await api.delete(`/members/assign-trainer/${id}/`);
          toast.success("Assignment deleted.");
          load();
        } catch {
          toast.error("Delete failed.");
        }
      },
      onCancel: () => setConfirmState(null),
    });
  };

  return (
    <div className="page">
      {confirmState && <ConfirmModal {...confirmState} />}

      <div className="page-header">
        <div>
          {fromPage && (
            <button className="btn btn-ghost" style={{ marginBottom: 6, fontSize: 13 }}
              onClick={() => navigate(`/${fromPage}`)}>
              ← Back
            </button>
          )}
          <h1 className="page-title">Trainer Assignments</h1>
          <p className="page-sub">Personal trainer scheduling for Standard &amp; Premium members</p>
        </div>
        <button className="btn btn-primary" onClick={() => setModal("new")}>+ Assign Trainer</button>
      </div>

      {/* Info pills */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ fontSize: 13, color: "var(--text-muted)", background: "var(--card-bg)", border: "1px solid var(--border)", borderRadius: 8, padding: "4px 12px" }}>
          {eligibleMembers.length} eligible member{eligibleMembers.length !== 1 ? "s" : ""}
          <span style={{ marginLeft: 4, color: "var(--text-muted)", fontSize: 11 }}>(Standard / Premium + PT)</span>
        </span>
        <span style={{ fontSize: 13, color: "var(--text-muted)", background: "var(--card-bg)", border: "1px solid var(--border)", borderRadius: 8, padding: "4px 12px" }}>
          {trainers.length} active trainer{trainers.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
        <input
          className="form-input" style={{ width: 220 }}
          placeholder="Search member / trainer name…"
          value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
        />
        <select className="form-input" style={{ width: 230 }}
          value={filterMember} onChange={e => { setFilterMember(e.target.value); setPage(1); }}>
          <option value="">All Members</option>
          {eligibleMembers.map(m => (
            <option key={m.id} value={m.id}>{m.member_id_display} — {m.name}</option>
          ))}
        </select>
        <select className="form-input" style={{ width: 230 }}
          value={filterTrainer} onChange={e => { setFilterTrainer(e.target.value); setPage(1); }}>
          <option value="">All Trainers</option>
          {trainers.map(t => (
            <option key={t.id} value={t.id}>S{String(t.id).padStart(4, "0")} — {t.name}</option>
          ))}
        </select>
        {(filterMember || filterTrainer || search) && (
          <button className="btn btn-ghost" onClick={() => { setFilterMember(""); setFilterTrainer(""); setSearch(""); setPage(1); }}>
            Clear
          </button>
        )}
      </div>

      {/* Mobile cards */}
      {!loading && assignments.length > 0 && (
        <div className="mobile-card-list">
          {assignments.map(a => {
            const ptAmt      = a.trainer_pt_amt || 0;
            const memberPaid = a.member_amount_paid || 0;
            const memberCoveredPT = ptAmt > 0 && memberPaid >= ptAmt;
            const canRenew   = a.can_renew_pt;
            const pendingRenewalTrainer = a.pending_pt_renewal_trainer_amount || 0;
            const renewalMemberPaid     = a.pt_renewal_member_paid_amount || 0;
            const renewalCoveredPT      = pendingRenewalTrainer > 0 && renewalMemberPaid >= pendingRenewalTrainer;
            const ptBalance             = a.pending_pt_balance || 0;
            return (
              <div key={a.id} className="mobile-card" style={{ flexDirection: "column", alignItems: "stretch" }}>
                <div className="mobile-card__left" style={{ width: "100%" }}>
                  <span className="mobile-card__id">{a.member_display_id}</span>
                  <span className="mobile-card__title">{a.member_name}</span>
                  {a.plan_name && (
                    <span className="badge badge-green" style={{ fontSize: 11, width: "fit-content" }}>
                      {a.plan_name}
                    </span>
                  )}
                  <span className="mobile-card__meta">
                    Trainer: {a.trainer_name} ({a.trainer_display_id})
                  </span>
                  <span className="mobile-card__meta">
                    {a.startingtime?.slice(0, 5)} – {a.endingtime?.slice(0, 5)}
                    {(a.working_day_names ?? []).length > 0 ? ` · ${(a.working_day_names ?? []).join(", ")}` : ""}
                  </span>
                  <div style={{ marginTop: 4 }}>
                    <PTStatusBadge assignment={a} />
                  </div>
                  {ptAmt > 0 && (
                    <span className="mobile-card__meta" style={{ color: "var(--text2)" }}>
                      Member PT: ₹{memberPaid.toLocaleString("en-IN")} / ₹{ptAmt.toLocaleString("en-IN")}
                      {memberCoveredPT ? " ✓" : ""}
                    </span>
                  )}
                  {pendingRenewalTrainer > 0 && (
                    <span className="mobile-card__meta" style={{ color: "var(--text2)" }}>
                      Renewal: ₹{renewalMemberPaid.toLocaleString("en-IN")} / ₹{pendingRenewalTrainer.toLocaleString("en-IN")}
                    </span>
                  )}
                </div>
                <div className="mobile-card__actions" style={{ marginTop: 10, justifyContent: "flex-start" }}>
                  {canRenew && (
                    <button className="btn btn-sm btn-primary" onClick={() => setPtRenewalModal(a)}>
                      Renew PT{a.pt_renewal_days > 0 ? ` (${a.pt_renewal_days}d)` : ""}
                    </button>
                  )}
                  {ptBalance > 0 && (
                    <button className="btn btn-sm btn-ghost"
                      style={{ color: "#e09020", borderColor: "#e09020" }}
                      onClick={() => setPtBalanceModal(a)}>
                      Pay ₹{fmt(ptBalance)}
                    </button>
                  )}
                  {ptAmt > 0 && !a.trainer_fee_paid && (
                    <button className="btn btn-sm btn-primary"
                      disabled={!memberCoveredPT}
                      onClick={() => handlePayTrainerFee(a)}>
                      Pay ₹{ptAmt.toLocaleString("en-IN")}
                    </button>
                  )}
                  {pendingRenewalTrainer > 0 && (
                    <button className="btn btn-sm btn-primary"
                      disabled={!renewalCoveredPT}
                      onClick={() => handlePayPtTrainerFee(a)}>
                      Renewal ₹{pendingRenewalTrainer.toLocaleString("en-IN")}
                    </button>
                  )}
                  <button className="btn btn-sm btn-ghost" onClick={() => setModal(a)}>Edit</button>
                  <button className="btn btn-sm btn-danger" onClick={() => handleDelete(a.id)}>Delete</button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="empty-state">Loading…</div>
      ) : assignments.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">◈</div>
          <div className="empty-state-title">No assignments found</div>
          <div className="empty-state-sub">
            {eligibleMembers.length === 0
              ? "No members have a Standard/Premium plan with Personal Trainer enabled."
              : "Click \"Assign Trainer\" to create one."}
          </div>
        </div>
      ) : (
        <div className="table-wrapper desktop-table-view">
          <table className="table">
            <thead>
              <tr>
                <th>Member</th>
                <th>Plan</th>
                <th>Trainer</th>
                <th>Time Slot</th>
                <th>Days</th>
                <th>PT Period</th>
                <th>Member PT Status</th>
                <th>Trainer Fee</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {assignments.map(a => {
                const ptAmt      = a.trainer_pt_amt || 0;
                const memberPaid = a.member_amount_paid || 0;
                const memberCoveredPT = ptAmt > 0 && memberPaid >= ptAmt;
                const canRenew   = a.can_renew_pt;
                // Renewal: compare member-collected amount vs trainer payable (not total_amount)
                const pendingRenewalTrainer = a.pending_pt_renewal_trainer_amount || 0;
                const renewalMemberPaid     = a.pt_renewal_member_paid_amount || 0;
                const renewalCoveredPT      = pendingRenewalTrainer > 0 && renewalMemberPaid >= pendingRenewalTrainer;
                const ptBalance             = a.pending_pt_balance || 0;

                return (
                  <tr key={a.id}>
                    <td>
                      <div>
                        <span className="badge badge-blue" style={{ marginRight: 6, fontSize: 11 }}>
                          {a.member_display_id}
                        </span>
                        {a.member_name}
                      </div>
                      {a.member_plan_expiry && (
                        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
                          Plan till: {a.member_plan_expiry}
                        </div>
                      )}
                    </td>

                    <td>
                      {a.plan_name
                        ? <span className="badge badge-green">{a.plan_name}</span>
                        : <span style={{ color: "var(--text-muted)", fontSize: 12 }}>—</span>}
                    </td>

                    <td>
                      <div>
                        <span className="badge badge-gray" style={{ marginRight: 6, fontSize: 11 }}>{a.trainer_display_id}</span>
                        {a.trainer_name}
                      </div>
                    </td>

                    <td style={{ whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                      {a.startingtime?.slice(0, 5)} – {a.endingtime?.slice(0, 5)}
                    </td>

                    <td>
                      <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
                        {(a.working_day_names ?? []).map(d => (
                          <span key={d} className="badge badge-yellow" style={{ padding: "1px 6px", fontSize: 11 }}>{d}</span>
                        ))}
                      </div>
                    </td>

                    {/* PT Period column */}
                    <td style={{ minWidth: 140 }}>
                      <PTStatusBadge assignment={a} />
                      {/* Renew PT button */}
                      <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
                        {canRenew ? (
                          <button
                            className="btn btn-sm btn-primary"
                            style={{ fontSize: 11, padding: "3px 10px" }}
                            onClick={() => setPtRenewalModal(a)}
                            title={a.pt_renewal_days < 30
                              ? `Renew PT for ${a.pt_renewal_days} days (prorated) — ₹${fmt(a.pt_renewal_amount)}`
                              : `Renew PT for 30 days — ₹${fmt(a.pt_renewal_amount)}`}
                          >
                            Renew PT
                            {a.pt_renewal_days > 0 && (
                              <span style={{ marginLeft: 4, opacity: 0.8 }}>({a.pt_renewal_days}d)</span>
                            )}
                          </button>
                        ) : (
                          <span
                            style={{ fontSize: 10, color: "var(--text-muted)", cursor: "help" }}
                            title={a.pt_renewal_blocked_reason || ""}
                          >
                            {a.pt_end_date && a.member_plan_expiry && a.pt_end_date >= a.member_plan_expiry
                              ? "PT covers plan expiry"
                              : a.member_status !== "active"
                                ? "Plan inactive"
                                : "Plan expired"}
                          </span>
                        )}
                        {/* Pay PT Balance button when renewal is partial/pending */}
                        {ptBalance > 0 && (
                          <button
                            className="btn btn-sm btn-ghost"
                            style={{ fontSize: 11, padding: "3px 10px", color: "#e09020", borderColor: "#e09020" }}
                            onClick={() => setPtBalanceModal(a)}
                            title={`Pay outstanding PT renewal balance ₹${fmt(ptBalance)}`}
                          >
                            Pay Balance ₹{fmt(ptBalance)}
                          </button>
                        )}
                      </div>
                    </td>

                    {/* Member PT payment status */}
                    <td>
                      {ptAmt > 0 ? (
                        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                          {/* Enrollment status */}
                          <span className={`badge ${memberCoveredPT ? "badge-green" : "badge-yellow"}`} style={{ fontSize: 11 }}>
                            {memberCoveredPT ? "Enroll Covered" : "Enroll Pending"}
                          </span>
                          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                            ₹{memberPaid.toLocaleString("en-IN")} / ₹{ptAmt.toLocaleString("en-IN")}
                          </span>
                          {/* Renewal status — compare collected vs trainer payable (not total) */}
                          {pendingRenewalTrainer > 0 && (
                            <>
                              <span className={`badge ${renewalCoveredPT ? "badge-green" : "badge-yellow"}`} style={{ fontSize: 11, marginTop: 2 }}>
                                {renewalCoveredPT ? "Renewal Covered" : "Renewal Pending"}
                              </span>
                              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                                ₹{renewalMemberPaid.toLocaleString("en-IN", { minimumFractionDigits: 2 })} / ₹{pendingRenewalTrainer.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                              </span>
                            </>
                          )}
                        </div>
                      ) : (
                        <span style={{ color: "var(--text-muted)", fontSize: 12 }}>—</span>
                      )}
                    </td>

                    {/* Pay trainer fee (enrollment + PT renewals) */}
                    <td>
                      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                        {/* ── Initial enrollment fee ── */}
                        {ptAmt > 0 ? (
                          a.trainer_fee_paid ? (
                            <span className="badge badge-green" style={{ fontSize: 11 }}>Enrollment Paid</span>
                          ) : (
                            <button
                              className="btn btn-sm btn-primary"
                              disabled={!memberCoveredPT}
                              title={!memberCoveredPT ? "Member hasn't paid enrollment PT fee yet" : `Pay ₹${ptAmt.toLocaleString("en-IN")} to ${a.trainer_name}`}
                              onClick={() => handlePayTrainerFee(a)}
                            >
                              Pay ₹{ptAmt.toLocaleString("en-IN")}
                            </button>
                          )
                        ) : null}

                        {/* ── PT renewal pending payout ── */}
                        {pendingRenewalTrainer > 0 ? (
                          <button
                            className="btn btn-sm btn-primary"
                            style={{ background: "var(--accent-2, #4da6ff)", borderColor: "var(--accent-2, #4da6ff)" }}
                            disabled={!renewalCoveredPT}
                            onClick={() => handlePayPtTrainerFee(a)}
                            title={!renewalCoveredPT
                              ? `Member hasn't paid enough for PT renewal yet (₹${renewalMemberPaid.toFixed(2)} / ₹${pendingRenewalTrainer.toFixed(2)})`
                              : `Pay accumulated PT renewal trainer fee to ${a.trainer_name}`}
                          >
                            Renewal ₹{pendingRenewalTrainer.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </button>
                        ) : a.has_paid_pt_renewals ? (
                          <span className="badge badge-green" style={{ fontSize: 11 }}>Renewal Paid</span>
                        ) : null}

                        {/* ── No PT configured ── */}
                        {ptAmt === 0 && pendingRenewalTrainer === 0 && !a.has_paid_pt_renewals && (
                          <span style={{ color: "var(--text-muted)", fontSize: 12 }}>—</span>
                        )}
                      </div>
                    </td>

                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        <button className="btn btn-sm btn-ghost" onClick={() => setModal(a)}>Edit</button>
                        <button className="btn btn-sm btn-danger" onClick={() => handleDelete(a.id)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {!loading && (assignments.length > 0 || page > 1) && (
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "12px 16px", borderTop: "1px solid var(--border)",
        }}>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{count} total</span>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn btn-sm btn-secondary" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
            <button className="btn btn-sm btn-secondary" disabled={assignments.length < 20} onClick={() => setPage(p => p + 1)}>Next →</button>
          </div>
        </div>
      )}

      {/* Assignment Modal */}
      {modal && (
        <AssignmentModal
          assignment={modal === "new" ? null : modal}
          allMembers={allMembers}
          trainers={trainers}
          plans={plans}
          newMemberId={modal === "new" ? newMemberId : null}
          newPlanId={modal === "new" ? newPlanId : null}
          prevType={modal === "new" ? prevType : null}
          pendingMember={modal === "new" ? pendingMember : null}
          pendingRenewal={modal === "new" ? pendingRenewal : null}
          renewMemberId={modal === "new" && isRenewUpgrade ? newMemberId : null}
          onClose={async () => {
            // Deferred renewal: nothing was saved yet, just clean up and navigate back
            if (isRenewUpgrade) {
              sessionStorage.removeItem("pendingRenewal");
              navigate(`/${fromPage || "members"}`);
              return;
            }
            // Edit upgrade cancelled: revert plan_type and personal_trainer back to original
            // so the member's dashboard shows the correct type
            if (newMemberId && prevType && fromPage && !isPending && modal === "new") {
              const prevPersonalTrainer = prevType === "standard" || prevType === "premium";
              try {
                await api.patch(`/members/list/${newMemberId}/`, {
                  plan_type:        prevType,
                  personal_trainer: prevPersonalTrainer,
                });
              } catch (_) { /* best-effort — navigate back regardless */ }
              navigate(`/${fromPage}`);
              return;
            }
            setModal(null);
          }}
          onSave={() => {
            setModal(null);
            setPendingMember(null);
            if (pendingRenewal) {
              sessionStorage.removeItem("pendingRenewal");
              setPendingRenewal(null);
            }
            load();
            if (fromPage) navigate(`/${fromPage}`);
          }}
        />
      )}

      {/* PT Renewal Modal */}
      {ptRenewalModal && (
        <PTRenewalModal
          assignment={ptRenewalModal}
          onClose={() => setPtRenewalModal(null)}
          onSave={() => {
            setPtRenewalModal(null);
            load();
          }}
        />
      )}

      {/* PT Balance Modal */}
      {ptBalanceModal && (
        <PTBalanceModal
          assignment={ptBalanceModal}
          onClose={() => setPtBalanceModal(null)}
          onSave={() => {
            setPtBalanceModal(null);
            load();
          }}
        />
      )}
    </div>
  );
}
