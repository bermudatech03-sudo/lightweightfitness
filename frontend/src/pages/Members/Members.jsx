import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../api/axios";
import toast from "react-hot-toast";
import "./Members.css";
import MemberBill from "../../components/MemberBill";
import ConfirmModal from "../../components/ConfirmModal";
import ChromeNotifyLinkModal from "../../components/ChromeNotifyLinkModal";


function statusBadge(s) {
  const m = { active: "badge-green", expired: "badge-red", cancelled: "badge-gray", paused: "badge-yellow" };
  return <span className={`badge ${m[s] || "badge-gray"}`}>{s}</span>;
}

/* ─── Enroll modal ─────────────────────────────────── */
function MemberModal({ member, plans, dietPlans: initialDietPlans, onClose, onSave }) {
  const isEdit = !!member?.id;
  // Coerce plan/diet to strings so React <select> matches <option> values correctly
  const [form, setForm] = useState(member
    ? {
      ...member,
      plan: member.plan != null ? String(member.plan) : "",
      diet: member.diet != null ? String(member.diet) : "",
      plan_type: member.plan_type || "basic",
      joining_date: member.joining_date,
    }
    : {
      name: "", phone: "", email: "", gender: "", plan: "", plan_type: "basic", diet: "",
      dob: "", gym_member_id: "",
      joining_date: new Date().toISOString().slice(0, 10),
      renewal_date: "", notes: "", status: "active", amount_paid: "", foodType: "veg", personal_trainer: false,
      mode_of_payment: "cash"
    }
  );
  const [saving, setSaving] = useState(false);
  const [dietBaseAmt, setDietBaseAmt] = useState(0);
  const [gymGstRate, setGymGstRate] = useState(18);
  const [discountedPlanBase, setDiscountedPlanBase] = useState("");
  // Keep an always-fresh list of diet plans — parent may have a stale copy
  // if plans were created/updated on another page since the last Members load.
  const [dietPlans, setDietPlans] = useState(initialDietPlans || []);
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));

  useEffect(() => {
    api.get("/finances/gym-settings/").then(r => {
      const s = r.data || {};
      if (s.DIET_PLAN_AMOUNT != null) setDietBaseAmt(parseFloat(s.DIET_PLAN_AMOUNT) || 0);
      if (s.GST_RATE != null) { const _r = parseFloat(s.GST_RATE); setGymGstRate(isNaN(_r) ? 18 : _r); }
    }).catch(() => { });
    // Always pull a fresh copy of diet plans when the modal opens
    api.get("/members/diet-plans/").then(r => {
      const data = Array.isArray(r.data) ? r.data : (r.data?.results ?? []);
      setDietPlans(data);
    }).catch(() => { });
  }, []);

  const selectedPlan      = plans.find(p => String(p.id) === String(form.plan));
  const planBasePrice     = parseFloat(selectedPlan?.price ?? 0);
  const effectivePlanBase = parseFloat(discountedPlanBase) || planBasePrice;
  const discountAmt       = Math.max(0, planBasePrice - effectivePlanBase);
  const dietWithGst = (form.plan_type === "premium" || form.plan_type === "dietonly-standard")
    ? parseFloat((dietBaseAmt * (1 + gymGstRate / 100)).toFixed(2))
    : 0;
  // Recompute plan total from effective (post-discount) base + GST rate
  const planWithGst  = effectivePlanBase > 0 ? parseFloat((effectivePlanBase * (1 + gymGstRate / 100)).toFixed(2)) : 0;
  const enrollTotal  = planWithGst + dietWithGst;

  const handlePlanChange = (id) => {
    set("plan", id);
    const found = plans.find(p => String(p.id) === String(id));
    if (found) {
      if (found.duration_days) {
        const renewal = new Date();
        renewal.setDate(renewal.getDate() + Number(found.duration_days));
        set("renewal_date", renewal.toISOString().split("T")[0]);
      }
      setDiscountedPlanBase(parseFloat(found.price).toFixed(2));
    } else {
      set("renewal_date", "");
      setDiscountedPlanBase("");
    }
    // reset plan_type and extras when plan changes
    set("plan_type", "basic");
    set("personal_trainer", false);
    set("diet", "");
    if (!isEdit) set("amount_paid", found ? (found.price_with_gst ?? found.price) : "");
  };

  const handlePlanTypeChange = (planType) => {
    set("plan_type", planType);
    set("personal_trainer", planType === "standard" || planType === "premium");
    if (planType !== "premium" && planType !== "dietonly-standard") {
      set("diet", "");
    }
    if (!isEdit) {
      const newDietFee = (planType === "premium" || planType === "dietonly-standard")
        ? parseFloat((dietBaseAmt * (1 + gymGstRate / 100)).toFixed(2))
        : 0;
      set("amount_paid", (planWithGst + newDietFee).toFixed(2));
    }
  };

  // Only update the selected diet chart; amount_paid already includes diet fee for premium/dietonly-standard
  const handleDietChange = (dietId) => {
    set("diet", dietId);
  };

  const submit = async (e) => {
    e.preventDefault(); setSaving(true);
    try {
      if (isEdit) {
        await api.patch(`/members/list/${member.id}/`, {
          ...form,
          diet: form.diet || null,
          foodType: form.foodType || "veg"
        });
        toast.success("Member updated!");
        const prevType = member.plan_type || "basic";
        const nextType = form.plan_type;
        // basic → standard/premium: need trainer assignment (PT + maybe diet)
        if (prevType === "basic" && (nextType === "standard" || nextType === "premium")) {
          onSave({ upgradeMemberId: member.id, upgradeType: "pt", prevType });
          return;
        }
        // basic → dietonly-standard: diet fee only, no trainer needed
        if (prevType === "basic" && nextType === "dietonly-standard") {
          onSave({ upgradeMemberId: member.id, upgradeType: "diet_only", prevType, prevDiet: member.diet || null });
          return;
        }
        // standard → premium: trainer already assigned, only need diet fee
        if (prevType === "standard" && nextType === "premium") {
          onSave({ upgradeMemberId: member.id, upgradeType: "diet_only", prevType, prevDiet: member.diet || null });
          return;
        }
        // dietonly-standard → premium: diet already collected, need trainer for PT fee
        if (prevType === "dietonly-standard" && nextType === "premium") {
          onSave({ upgradeMemberId: member.id, upgradeType: "pt_only", prevType });
          return;
        }
        onSave(null);
      } else {
        // Standard / Premium → hold enrollment until trainer is assigned
        if (form.plan_type === "standard" || form.plan_type === "premium") {
          sessionStorage.setItem("pendingMember", JSON.stringify({
            name: form.name,
            phone: form.phone,
            email: form.email || "",
            gender: form.gender || "",
            address: form.address || "",
            notes: form.notes || "",
            age: form.age || undefined,
            dob: form.dob || undefined,
            gym_member_id: form.gym_member_id || "",
            plan: form.plan || undefined,
            plan_id: form.plan || undefined,
            diet: form.diet || undefined,
            diet_id: form.diet || undefined,
            foodType: form.foodType || "veg",
            plan_type: form.plan_type,
            personal_trainer: true,
            amount_paid: form.amount_paid || 0,
            mode_of_payment: form.mode_of_payment || "cash",
            joining_date: form.joining_date || undefined,
            renewal_date: form.renewal_date || undefined,
            status: form.status || "active",
            discount_amount: discountAmt,
          }));
          toast.success("Details saved — assign a trainer to complete enrollment.");
          onSave({ isPending: true, planType: form.plan_type });
          return;
        }

        const res = await api.post("/members/list/", {
          ...form,
          dob:             form.dob || null,
          plan_id:         form.plan || undefined,
          diet_id:         form.diet || undefined,
          foodType:        form.foodType || "veg",
          discount_amount: discountAmt,
        });
        toast.success("Member enrolled!");
        let billData = res.data.bill ?? null;
        if (billData && res.data.id) {
          try {
            const hRes = await api.get("/members/payments/", { params: { member: res.data.id } });
            const raw = hRes.data;
            const list = Array.isArray(raw) ? raw : Array.isArray(raw?.results) ? raw.results : [];
            list.sort((a, b) => new Date(a.paid_date) - new Date(b.paid_date));
            const listWithInsts = list.map(p => ({
              ...p,
              cycle_installments: p.installment_payments || [],
            }));
            billData = { ...billData, installments: listWithInsts };
          } catch (_) { /* non-fatal */ }
        }
        onSave({ bill: billData, newMemberId: res.data.id, planType: form.plan_type });
      }
    } catch (err) {
      const d = err.response?.data;
      toast.error(
        typeof d === "object"
          ? Object.values(d).flat().join(" ")
          : "Something went wrong"
      );
    } finally { setSaving(false); }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-title">{isEdit ? "Edit Member" : "Enroll New Member"}</div>
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="grid-2">
            <div className="form-group">
              <label className="form-label">Full Name *</label>
              <input className="form-input" value={form.name}
                onChange={e => set("name", e.target.value)} required placeholder="Rajan Kumar" />
            </div>
            <div className="form-group">
              <label className="form-label">Age</label>
              <input className="form-input" type="number" onWheel={e => e.target.blur()} min="1" max="120" value={form.age || ""}
                onChange={e => set("age", e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Date of Birth</label>
              <input className="form-input" type="date" value={form.dob || ""}
                onChange={e => set("dob", e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Gym ID (from gym end)</label>
              <input className="form-input" value={form.gym_member_id || ""}
                onChange={e => set("gym_member_id", e.target.value)}
                placeholder="e.g. GYM-001 (optional)" />
            </div>
            <div className="form-group">
              <label className="form-label">Phone *</label>
              <input className="form-input" value={form.phone}
                onChange={e => set("phone", e.target.value)} required placeholder="9876543210" />
            </div>
            <div className="form-group">
              <label className="form-label">Email</label>
              <input className="form-input" type="email" value={form.email || ""}
                onChange={e => set("email", e.target.value)} placeholder="rajan@email.com" />
            </div>
            <div className="form-group">
              <label className="form-label">Gender</label>
              <select className="form-input" value={form.gender || ""} onChange={e => set("gender", e.target.value)}>
                <option value="">Select</option>
                <option value="Male">Male</option>
                <option value="Female">Female</option>
                <option value="Other">Other</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Membership Plan</label>
              <select className="form-input" value={form.plan || ""} onChange={e => handlePlanChange(e.target.value)}>
                <option value="">No Plan</option>
                {plans.map(p => (
                  <option key={p.id} value={p.id}>
                    {p.name} — ₹{(p.price_with_gst ?? p.price).toLocaleString("en-IN")} incl. GST ({p.duration_days}d)
                  </option>
                ))}
              </select>
            </div>
            {form.plan && (
              <div className="form-group">
                <label className="form-label">Plan Type</label>
                <select className="form-input" value={form.plan_type} onChange={e => handlePlanTypeChange(e.target.value)}>
                  <option value="basic">Basic</option>
                  <option value="standard">Standard — includes Personal Trainer</option>
                  <option value="premium">Premium — includes Personal Trainer + Diet Plan</option>
                  <option value="dietonly-standard">Standard (Diet Only) — no Personal Trainer, includes Diet Plan</option>
                </select>
              </div>
            )}
            {/* {(form.plan_type === "standard" || form.plan_type === "premium") && (
              <div className="form-group">
                <label className="form-label">Personal Trainer</label>
                <select className="form-input" value={String(form.personal_trainer)} onChange={e => {
                  const isTrainer = e.target.value === "true";
                  set("personal_trainer", isTrainer);
                  if (!isEdit) {
                    const found = plans.find(p => String(p.id) === String(form.plan));
                    if (found) {
                      let basePrice = parseFloat(found.price);
                      if (isTrainer) {
                        if (form.plan_type === "standard") basePrice += 500;
                        else if (form.plan_type === "premium") basePrice += 1000;
                      }
                      const gstRate = found.gst_rate ?? 18;
                      const total = Math.round(basePrice * (1 + gstRate / 100) * 100) / 100;
                      set("amount_paid", total);
                    }
                  }
                }}>
                  <option value="false">No</option>
                  <option value="true">Yes</option>
                </select>
              </div>
            )} */}
            {form.plan_type === "premium" && (
              <div className="form-group">
                <label className="form-label">Diet Plan</label>
                <select className="form-input" value={form.diet || ""} onChange={e => handleDietChange(e.target.value)}>
                  <option value="">No Diet Plan</option>
                  {dietPlans.map(d => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </select>
              </div>
            )}
            {form.plan_type === "dietonly-standard" && (
              <div className="form-group">
                <label className="form-label">Diet Plan</label>
                <select className="form-input" value={form.diet || ""} onChange={e => handleDietChange(e.target.value)}>
                  <option value="">No Diet Plan</option>
                  {dietPlans.map(d => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </select>
              </div>
            )}
            {!isEdit ? (
              <div className="form-group">
                <label className="form-label">Joining Date</label>
                <input className="form-input" type="date" value={form.joining_date}
                  onChange={e => set("joining_date", e.target.value)} />
              </div>
            ) : (
              <div className="form-group">
                <label className="form-label">Joining Date</label>
                <input className="form-input" type="date" value={form.joining_date}
                  onChange={e => set("joining_date", e.target.value)} />
              </div>
            )}
            <div className="form-group">
              <label className="form-label">Renewal Date</label>
              <input className="form-input" type="date" value={form.renewal_date || ""}
                onChange={e => set("renewal_date", e.target.value)} />
            </div>
            {!isEdit && selectedPlan && (
              <>
                {/* ── Discount field ── */}
                <div className="form-group" style={{ gridColumn: "span 2" }}>
                  <label className="form-label">Plan Cost After Discount (₹)</label>
                  <input
                    className="form-input"
                    type="number" onWheel={e => e.target.blur()}
                    min="0"
                    max={planBasePrice}
                    step="0.01"
                    value={discountedPlanBase}
                    onChange={e => {
                      setDiscountedPlanBase(e.target.value);
                      const ep  = parseFloat(e.target.value) || planBasePrice;
                      const tot = parseFloat((ep * (1 + gymGstRate / 100)).toFixed(2)) + dietWithGst;
                      set("amount_paid", tot.toFixed(2));
                    }}
                    placeholder={planBasePrice.toFixed(2)}
                    style={{ fontFamily: "var(--font-mono)" }}
                  />
                  <span style={{ fontSize: 11, color: "var(--text3)", marginTop: 3, display: "block" }}>
                    Default is plan price ₹{planBasePrice.toLocaleString("en-IN")}. Reduce to apply a discount.
                  </span>
                </div>

                {/* Breakdown box */}
                <div style={{
                  gridColumn: "span 2", background: "var(--surface2)", borderRadius: 8,
                  padding: "10px 14px", fontSize: 12
                }}>
                  {discountAmt > 0 && (
                    <>
                      <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text3)", marginBottom: 3 }}>
                        <span>Plan (Original)</span>
                        <span style={{ fontFamily: "var(--font-mono)" }}>₹{planBasePrice.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", color: "var(--accent)", marginBottom: 3 }}>
                        <span>Discount</span>
                        <span style={{ fontFamily: "var(--font-mono)" }}>- ₹{discountAmt.toFixed(2)}</span>
                      </div>
                    </>
                  )}
                  <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text2)", marginBottom: 3 }}>
                    <span>Membership (incl. GST)</span>
                    <span style={{ fontFamily: "var(--font-mono)" }}>₹{planWithGst.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
                  </div>
                  {dietWithGst > 0 && (
                    <div style={{ display: "flex", justifyContent: "space-between", color: "var(--teal)", marginBottom: 3 }}>
                      <span>Diet Plan (incl. GST)</span>
                      <span style={{ fontFamily: "var(--font-mono)" }}>+ ₹{dietWithGst.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
                    </div>
                  )}
                  <div style={{
                    display: "flex", justifyContent: "space-between", fontWeight: 700,
                    borderTop: "1px solid var(--border)", paddingTop: 6, marginTop: 4, color: "var(--text1)"
                  }}>
                    <span>Total Payable</span>
                    <span style={{ fontFamily: "var(--font-mono)" }}>₹{enrollTotal.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label">Amount Paid Now (₹)</label>
                  <input className="form-input" type="number" onWheel={e => e.target.blur()} min="0" value={form.amount_paid || ""}
                    onChange={e => set("amount_paid", e.target.value)} placeholder="0" />
                </div>
                {(() => {
                  const total = enrollTotal || parseFloat(selectedPlan.price_with_gst ?? selectedPlan.price);
                  const remaining = Math.max(0, total - parseFloat(form.amount_paid || 0));
                  return (
                    <div className="form-group">
                      <label className="form-label">Balance Remaining (₹)</label>
                      <input className="form-input" disabled
                        value={remaining.toLocaleString("en-IN")}
                        style={{
                          opacity: .7, fontFamily: "var(--font-mono)",
                          color: remaining > 0 ? "var(--warn)" : "var(--accent)"
                        }} />
                      <span style={{ fontSize: 11, color: "var(--text3)", marginTop: 3, display: "block" }}>
                        Total incl. GST ₹{total.toLocaleString("en-IN", { maximumFractionDigits: 2 })} — auto-calculated
                      </span>
                    </div>
                  );
                })()}
              </>
            )}
            {!isEdit ? (
              <div className="form-group">
                <label className="form-label">Status</label>
                <select className="form-input" value={form.status} onChange={e => set("status", e.target.value)}>
                  <option value="active">Active</option>
                  {/* <option value="expired">Expired</option> */}
                  <option value="cancelled">Cancelled</option>
                  <option value="paused">Paused</option>
                </select>
              </div>) : (
              <div className="form-group">
                <label className="form-label">Status</label>
                <select className="form-input" value={form.status} onChange={e => set("status", e.target.value)}>
                  <option value="active">Active</option>
                  <option value="expired">Expired</option>
                  <option value="cancelled">Cancelled</option>
                  <option value="paused">Paused</option>
                </select>
              </div>
            )}

            {!isEdit && (
              <div className="form-group">
                <label className="form-label">Mode of Payment</label>
                <select className="form-input" value={form.mode_of_payment || "cash"} onChange={e => set("mode_of_payment", e.target.value)}>
                  <option value="cash">Cash</option>
                  <option value="card">Card</option>
                  <option value="upi">UPI</option>
                  <option value="other">Other</option>
                </select>
              </div>
            )}
          </div>

          <div className="form-group">
            <label className="form-label">Food Type</label>
            <select className="form-input" value={form.foodType || ""} onChange={e => set("foodType", e.target.value)}>
              <option value="veg">Vegetarian</option>
              <option value="nonveg">Non-Vegetarian</option>
              <option value="vegan">Vegan</option>
              <option value="other">Other</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Notes</label>
            <textarea className="form-input" value={form.notes || ""}
              onChange={e => set("notes", e.target.value)} rows={2} />
          </div>
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? "Saving…" : isEdit ? "Update Member" : "Enroll & Record"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ─── Renew modal ──────────────────────────────────── */
function RenewModal({ member, plans, dietPlans: initialDietPlans = [], onClose, onSave }) {
  const [planId, setPlanId] = useState(member.plan != null ? String(member.plan) : "");
  const [planType, setPlanType] = useState(member.plan_type || "basic");
  const [dietId, setDietId] = useState(member.diet != null ? String(member.diet) : "");
  const [amount, setAmount] = useState("");
  const [notes, setNotes] = useState("");
  const [modeOfPayment, setModeOfPayment] = useState("cash");
  const [saving, setSaving] = useState(false);
  const [dietBase, setDietBase] = useState(0);   // base diet amount (pre-GST) from gym settings
  const [gstRate, setGstRate] = useState(18);
  const [userEdited, setUserEdited] = useState(false);
  const [dietPlans, setDietPlans] = useState(initialDietPlans || []);
  const [discountedPlanBase, setDiscountedPlanBase] = useState("");

  useEffect(() => {
    api.get("/finances/gym-settings/").then(r => {
      const s = r.data || {};
      if (s.DIET_PLAN_AMOUNT != null) setDietBase(parseFloat(s.DIET_PLAN_AMOUNT) || 0);
      if (s.GST_RATE != null) { const _r = parseFloat(s.GST_RATE); setGstRate(isNaN(_r) ? 18 : _r); }
    }).catch(() => { });
    // Refresh diet plan list on modal open so newly created plans are available
    api.get("/members/diet-plans/").then(r => {
      const data = Array.isArray(r.data) ? r.data : (r.data?.results ?? []);
      setDietPlans(data);
    }).catch(() => { });
  }, []);

  const activePlan =
    plans.find(p => String(p.id) === String(planId)) ||
    plans.find(p => String(p.id) === String(member.plan));

  const planBase        = parseFloat(activePlan?.price ?? 0);
  const effectivePlanBase = parseFloat(discountedPlanBase) || planBase;
  const discountAmt     = Math.max(0, planBase - effectivePlanBase);
  const dietWithGst     = (planType === "premium" || planType === "dietonly-standard")
    ? parseFloat((dietBase * (1 + gstRate / 100)).toFixed(2)) : 0;
  const planWithGst     = effectivePlanBase * (1 + gstRate / 100);
  const planTotal       = planWithGst + dietWithGst;

  // Auto-fill amount when plan/diet changes (unless user has manually edited)
  useEffect(() => {
    if (!userEdited) setAmount(planTotal ? planTotal.toFixed(2) : "");
  }, [planTotal, userEdited]);

  // Reset discount when plan changes
  const handlePlanChange = (id) => {
    setPlanId(id);
    setDiscountedPlanBase("");
    setUserEdited(false);
  };

  const handlePlanTypeChange = (newType) => {
    setPlanType(newType);
    if (newType === "basic" || newType === "standard") {
      setDietId("");
    }
    setDiscountedPlanBase("");
    setUserEdited(false);
  };

  const balance = Math.max(0, planTotal - parseFloat(amount || 0));

  const submit = async (e) => {
    e.preventDefault(); setSaving(true);
    try {
      // Check if plan type upgrade requires trainer assignment
      const prevType = member.plan_type || "basic";
      const hadTrainer = prevType === "standard" || prevType === "premium";
      const needsTrainer = !hadTrainer && (planType === "standard" || planType === "premium");

      if (needsTrainer) {
        // Defer renewal — don't save yet, store data for trainer assignment step
        const renewalData = {
          plan_id:         planId || undefined,
          plan_type:       planType,
          diet_id:         dietId ? Number(dietId) : null,
          amount_paid:     amount,
          notes,
          mode_of_payment: modeOfPayment,
          discount_amount: discountAmt,
        };
        sessionStorage.setItem("pendingRenewal", JSON.stringify(renewalData));
        onSave({ renewUpgrade: true, memberId: member.id, planId: planId || member.plan, prevType });
      } else {
        const res = await api.post(`/members/list/${member.id}/renew/`, {
          plan_id:         planId || undefined,
          plan_type:       planType,
          diet_id:         dietId ? Number(dietId) : null,
          amount_paid:     amount,
          notes,
          mode_of_payment: modeOfPayment,
          discount_amount: discountAmt,
        });
        toast.success(balance > 0
          ? `Renewed! Balance ₹${balance} recorded.`
          : "Renewed! Full payment recorded in Finances.");
        let billData = res.data.bill ?? null;
        if (billData) {
          try {
            const hRes = await api.get("/members/payments/", { params: { member: member.id } });
            const raw = hRes.data;
            const list = Array.isArray(raw) ? raw : Array.isArray(raw?.results) ? raw.results : [];
            list.sort((a, b) => new Date(a.paid_date) - new Date(b.paid_date));
            const listWithInsts = list.map(p => ({
              ...p,
              cycle_installments: p.installment_payments || [],
            }));
            billData = { ...billData, installments: listWithInsts };
          } catch (_) { /* non-fatal */ }
        }
        onSave(billData);
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Renewal failed");
    } finally { setSaving(false); }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 460 }} onClick={e => e.stopPropagation()}>
        <div className="modal-title">Renew — {member.name}</div>
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 4 }}>
          <div className="form-group">
            <label className="form-label">Plan</label>
            <select className="form-input" value={planId} onChange={e => handlePlanChange(e.target.value)}>
              <option value="">Keep current plan</option>
              {plans.map(p => (
                <option key={p.id} value={p.id}>
                  {p.name} — ₹{(p.price_with_gst ?? p.price).toLocaleString("en-IN")} incl. GST
                </option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Plan Type</label>
            <select className="form-input" value={planType} onChange={e => handlePlanTypeChange(e.target.value)}>
              <option value="basic">Basic</option>
              <option value="standard">Standard</option>
              <option value="premium">Premium</option>
              <option value="dietonly-standard">Standard (Diet Only)</option>
            </select>
            {planType !== (member.plan_type || "basic") && (
              <span style={{ fontSize: 11, color: "var(--amber, orange)", marginTop: 3, display: "block" }}>
                Plan type will change from {member.plan_type || "basic"} to {planType} after current plan ends.
              </span>
            )}
          </div>
          {(planType === "premium" || planType === "dietonly-standard") && (
            <div className="form-group">
              <label className="form-label">Diet Plan</label>
              <select className="form-input" value={dietId} onChange={e => setDietId(e.target.value)}>
                <option value="">No Diet Plan</option>
                {dietPlans.map(d => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
              <span style={{ fontSize: 11, color: "var(--text3)", marginTop: 3, display: "block" }}>
                Diet fee will be added to the renewal total.
              </span>
            </div>
          )}
          {/* ── Discount field ── */}
          {planBase > 0 && (
            <div className="form-group">
              <label className="form-label">Plan Cost After Discount (₹)</label>
              <input
                className="form-input"
                type="number" onWheel={e => e.target.blur()}
                min="0"
                max={planBase}
                step="0.01"
                value={discountedPlanBase}
                onChange={e => {
                  setDiscountedPlanBase(e.target.value);
                  setUserEdited(false);
                }}
                placeholder={planBase.toFixed(2)}
                style={{ fontFamily: "var(--font-mono)" }}
              />
              <span style={{ fontSize: 11, color: "var(--text3)", marginTop: 3, display: "block" }}>
                Default is plan price ₹{planBase.toLocaleString("en-IN")}. Change to apply a discount.
              </span>
            </div>
          )}

          {planTotal > 0 && (
            <div style={{
              background: "var(--surface2)", borderRadius: 8, padding: "10px 14px", fontSize: 12,
            }}>
              {discountAmt > 0 && (
                <>
                  <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text3)", marginBottom: 3 }}>
                    <span>Plan (Original)</span>
                    <span style={{ fontFamily: "var(--font-mono)" }}>₹{planBase.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", color: "var(--accent)", marginBottom: 3 }}>
                    <span>Discount</span>
                    <span style={{ fontFamily: "var(--font-mono)" }}>- ₹{discountAmt.toFixed(2)}</span>
                  </div>
                </>
              )}
              <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text2)", marginBottom: 3 }}>
                <span>Membership (incl. GST)</span>
                <span style={{ fontFamily: "var(--font-mono)" }}>₹{planWithGst.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
              </div>
              {(planType === "premium" || planType === "dietonly-standard") && dietBase > 0 && (
                <div style={{ display: "flex", justifyContent: "space-between", color: "var(--teal)", marginBottom: 3 }}>
                  <span>Diet Plan (incl. GST{dietId ? "" : " — chart to be assigned"})</span>
                  <span style={{ fontFamily: "var(--font-mono)" }}>+ ₹{dietWithGst.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
                </div>
              )}
              <div style={{
                display: "flex", justifyContent: "space-between", fontWeight: 700,
                borderTop: "1px solid var(--border)", paddingTop: 6, marginTop: 4, color: "var(--text1)"
              }}>
                <span>Total Payable</span>
                <span style={{ fontFamily: "var(--font-mono)" }}>₹{planTotal.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
              </div>
            </div>
          )}
          <div className="grid-2">
            <div className="form-group">
              <label className="form-label">Total incl. GST (₹)</label>
              <input className="form-input" value={planTotal.toFixed(2)} disabled style={{ opacity: .6 }} />
            </div>
            <div className="form-group">
              <label className="form-label">Amount Collected (₹) *</label>
              <input className="form-input" type="number" onWheel={e => e.target.blur()} min="0" value={amount}
                onChange={e => { setUserEdited(true); setAmount(e.target.value); }} required placeholder="1500" />
            </div>
          </div>
          {planTotal > 0 && (
            <div style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              background: balance > 0 ? "rgba(255,184,48,.1)" : "rgba(105,114,84,.08)",
              border: `1px solid ${balance > 0 ? "rgba(255,184,48,.3)" : "rgba(105,114,84,.20)"}`,
              borderRadius: 8, padding: "10px 14px", fontSize: 13
            }}>
              <span style={{ color: "var(--text2)" }}>
                {balance > 0 ? "⚠ Balance remaining" : "✓ Fully paid"}
              </span>
              <span style={{
                fontFamily: "var(--font-mono)", fontWeight: 700,
                color: balance > 0 ? "var(--warn)" : "var(--accent)"
              }}>
                ₹{balance.toLocaleString("en-IN")}
              </span>
            </div>
          )}
          <div className="form-group">
            <label className="form-label">Notes</label>
            <input className="form-input" value={notes} onChange={e => setNotes(e.target.value)}
              placeholder="Optional note…" />
          </div>
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <label className="form-label">Mode Of Payment </label>
            <select className="form-input" value={modeOfPayment} onChange={e => setModeOfPayment(e.target.value)}>
              <option value="cash">Cash</option>
              <option value="card">Card</option>
              <option value="upi">UPI</option>
              <option value="other">Other</option>
            </select>
          </div>
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? "Processing…" : "Renew & Record"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ─── Payment history + balance payment modal ──────── */
function PaymentHistoryModal({ member, onClose, onRefresh, onBill, gymInfo = {} }) {
  const [payments, setPayments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [balAmt, setBalAmt] = useState("");
  const [balMode, setBalMode] = useState("cash");
  const [paying, setPaying] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api.get("/members/payments/", { params: { member: member.id } })
      .then(res => {
        const data = res.data;
        const list = Array.isArray(data)
          ? data
          : Array.isArray(data?.results)
            ? data.results
            : [];
        list.sort((a, b) => new Date(b.paid_date) - new Date(a.paid_date));
        setPayments(list);
      })
      .catch(err => {
        console.error("Payments fetch error:", err);
        setError("Failed to load payments. Please try again.");
        setPayments([]);
      })
      .finally(() => setLoading(false));
  }, [member.id]);

  useEffect(() => { load(); }, [load]);

  const totalPaid = payments.reduce((s, p) => s + parseFloat(p.amount_paid || 0), 0);
  const totalDue = payments.reduce((s, p) => s + parseFloat(p.total_with_gst || 0), 0);
  const totalBal = payments.reduce((s, p) => s + parseFloat(p.balance || 0), 0);

  const hasOutstanding = payments.some(p => ["partial", "pending"].includes(p.status));
  const latestBal = payments.find(p => ["partial", "pending"].includes(p.status));

  const payBalance = async () => {
    if (!balAmt || parseFloat(balAmt) <= 0) {
      toast.error("Enter a valid amount"); return;
    }
    setPaying(true);
    try {
      const res = await api.post(`/members/list/${member.id}/pay-balance/`, { amount_paid: balAmt, mode_of_payment: balMode });
      toast.success("Balance payment recorded in Finances!");
      setBalAmt("");
      const updated = await api.get("/members/payments/", { params: { member: member.id } });
      const updatedList = (() => {
        const d = updated.data;
        const list = Array.isArray(d) ? d : Array.isArray(d?.results) ? d.results : [];
        list.sort((a, b) => new Date(b.paid_date) - new Date(a.paid_date));
        return list;
      })();
      setPayments(updatedList);
      onRefresh();
      if (res.data.bill) {
        const listWithInsts = [...updatedList]
          .sort((a, b) => new Date(a.paid_date) - new Date(b.paid_date))
          .map(p => ({ ...p, cycle_installments: p.installment_payments || [] }));
        onBill({ ...res.data.bill, installments: listWithInsts });
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed");
    } finally { setPaying(false); }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 720 }} onClick={e => e.stopPropagation()}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <div className="modal-title" style={{ marginBottom: 0 }}>Payments — {member.name}</div>
          <div style={{ display: "flex", gap: 8 }}>
            {payments.length > 0 && (
              <button className="btn btn-sm btn-primary" onClick={() => {
                const sortedAsc = [...payments]
                  .sort((a, b) => new Date(a.paid_date) - new Date(b.paid_date))
                  .map(p => ({ ...p, cycle_installments: p.installment_payments || [] }));
                onBill({
                  isStatement: true,
                  member_name: member.name,
                  member_id: member.member_id_display || `M${String(member.id).padStart(4, "0")}`,
                  phone: member.phone || "",
                  email: member.email || "",
                  date: new Date().toISOString().slice(0, 10),
                  invoice_number: "",
                  plan_price: 0, gst_rate: 0, gst_amount: 0,
                  total_with_gst: 0, amount_paid: 0, balance: 0,
                  ...gymInfo,
                  installments: sortedAsc,
                });
              }}>📋 Full Statement</button>
            )}
            <button className="btn btn-sm btn-secondary" onClick={onClose}>✕</button>
          </div>
        </div>

        {/* Summary row */}
        <div className="payment-summary-row">
          {[
            { label: "Total Billed", val: `₹${totalDue.toLocaleString("en-IN")}`, color: "var(--text1)", cls: "" },
            { label: "Total Paid", val: `₹${totalPaid.toLocaleString("en-IN")}`, color: "var(--accent)", cls: "" },
            { label: "Balance Due", val: `₹${totalBal.toLocaleString("en-IN")}`, color: totalBal > 0 ? "var(--warn)" : "var(--teal)", cls: totalBal > 0 ? "payment-summary-card--alert" : "" },
          ].map(c => (
            <div key={c.label} className={`payment-summary-card ${c.cls}`}>
              <div className="payment-summary-card__label">
                {c.label}
              </div>
              <div className="payment-summary-card__value" style={{ color: c.color }}>
                {c.val}
              </div>
            </div>
          ))}
        </div>

        {/* Balance payment input */}
        {hasOutstanding && latestBal && (
          <div style={{
            background: "rgba(255,184,48,.08)", border: "1px solid rgba(255,184,48,.25)",
            borderRadius: 10, padding: "14px 16px", marginBottom: 16,
            display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap"
          }}>
            <div style={{ flex: 1, minWidth: 200 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: "var(--warn)", marginBottom: 4 }}>
                ⚠ Outstanding balance: ₹{parseFloat(latestBal.balance).toLocaleString("en-IN")}
              </div>
              <div style={{ fontSize: 11, color: "var(--text3)" }}>
                Valid: {latestBal.valid_from} → {latestBal.valid_to}
              </div>
            </div>
            <input className="form-input" type="number" onWheel={e => e.target.blur()} min="1" max={latestBal.balance}
              value={balAmt} onChange={e => setBalAmt(e.target.value)}
              placeholder={`Max ₹${latestBal.balance}`} style={{ maxWidth: 140 }} />
            <select className="form-input" value={balMode} onChange={e => setBalMode(e.target.value)} style={{ maxWidth: 110 }}>
              <option value="cash">Cash</option>
              <option value="card">Card</option>
              <option value="upi">UPI</option>
              <option value="other">Other</option>
            </select>
            <button className="btn btn-primary btn-sm" onClick={payBalance} disabled={paying}>
              {paying ? "…" : "Record Payment"}
            </button>
          </div>
        )}

        {/* Payments — expanded cycle cards */}
        {loading ? (
          <div style={{ textAlign: "center", padding: 32, color: "var(--text3)" }}>Loading…</div>
        ) : error ? (
          <div style={{ textAlign: "center", padding: 32, color: "var(--danger)" }}>
            {error}<br />
            <button className="btn btn-sm btn-secondary" style={{ marginTop: 12 }} onClick={load}>Retry</button>
          </div>
        ) : payments.length === 0 ? (
          <div style={{ textAlign: "center", padding: 32, color: "var(--text3)" }}>
            No payments recorded yet for this member.
          </div>
        ) : (
          <div className="table-wrap">
            {payments.map(p => {
              const insts = p.installment_payments || [];
              return (
                <div key={p.id} style={{
                  marginBottom: 12, border: "1px solid var(--border)",
                  borderRadius: 8, overflow: "hidden"
                }}>
                  {/* Cycle header */}
                  <div style={{
                    background: "var(--surface2)", padding: "8px 14px",
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                    borderBottom: "1px solid var(--border)", flexWrap: "wrap", gap: 6
                  }}>
                    <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                      <span style={{
                        fontSize: 10, fontWeight: 800, letterSpacing: .8, padding: "2px 8px",
                        borderRadius: 100,
                        background: (p.invoice_number || "").includes("-R") ? "rgba(78,124,96,.12)" : "rgba(105,114,84,.12)",
                        color: (p.invoice_number || "").includes("-R") ? "var(--teal)" : "var(--accent)",
                        border: (p.invoice_number || "").includes("-R") ? "1px solid rgba(78,124,96,.28)" : "1px solid rgba(105,114,84,.28)"
                      }}>
                        {(p.invoice_number || "").includes("-R") ? "RENEWAL" : "ENROLLMENT"}
                      </span>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text3)" }}>
                        {p.invoice_number || "—"}
                      </span>
                      <span style={{ fontSize: 11, color: "var(--text2)" }}>{p.plan_name || "—"}</span>
                    </div>
                    <div style={{ display: "flex", gap: 12, alignItems: "center", fontSize: 12 }}>
                      <span style={{ color: "var(--text3)" }}>{p.valid_from} → {p.valid_to}</span>
                      <span className={`badge ${p.status === "paid" ? "badge-green" :
                        p.status === "partial" ? "badge-yellow" : "badge-red"
                        }`}>{p.status}</span>
                    </div>
                  </div>

                  {/* GST info row */}
                  <div style={{
                    background: "var(--surface)", padding: "5px 14px",
                    borderBottom: "1px solid var(--border)", fontSize: 11, color: "var(--text3)"
                  }}>
                    Billed: <strong style={{ color: "var(--text1)" }}>
                      ₹{Number(p.total_with_gst || 0).toLocaleString("en-IN")}
                    </strong>
                    &ensp;|&ensp; Membership: <strong>₹{(Number(p.plan_price || 0) - Number(p.diet_plan_amount || 0)).toLocaleString("en-IN")}</strong>
                    {Number(p.diet_plan_amount || 0) > 0 && (
                      <>
                        &ensp;+&ensp; Diet: <strong style={{ color: "var(--teal)" }}>
                          ₹{Number(p.diet_plan_amount).toLocaleString("en-IN")}
                        </strong>
                      </>
                    )}
                    &ensp;+&ensp; GST {p.gst_rate || 0}%: <strong style={{ color: "var(--warn)" }}>
                      ₹{Number(p.gst_amount || 0).toLocaleString("en-IN")}
                    </strong>
                  </div>

                  {/* Installment rows */}
                  {insts.length > 0 && (
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                      <thead>
                        <tr style={{ background: "var(--surface)" }}>
                          {["Date", "Type", "Amount Paid", "Balance After"].map((h, i) => (
                            <th key={h} style={{
                              padding: "5px 10px", fontWeight: 700, color: "var(--text3)", fontSize: 11,
                              textAlign: i >= 2 ? "right" : "left",
                              borderBottom: "1px solid var(--border)"
                            }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {insts.map((inst, ri) => {
                          const typeLabel =
                            inst.installment_type === "enrollment" ? "Enrollment" :
                              inst.installment_type === "renewal" ? "Renewal" : "Balance Payment";
                          return (
                            <tr key={inst.id} style={{ borderTop: ri > 0 ? "1px solid var(--border)" : "none" }}>
                              <td style={{ padding: "6px 10px", color: "var(--text2)" }}>{inst.paid_date}</td>
                              <td style={{ padding: "6px 10px", color: "var(--info)", fontWeight: 600, fontSize: 11 }}>
                                {typeLabel}
                              </td>
                              <td style={{ padding: "6px 10px", textAlign: "right", fontFamily: "var(--font-mono)", color: "var(--accent)", fontWeight: 700 }}>
                                ₹{Number(inst.amount).toLocaleString("en-IN")}
                              </td>
                              <td style={{
                                padding: "6px 10px", textAlign: "right", fontFamily: "var(--font-mono)",
                                color: parseFloat(inst.balance_after) > 0 ? "var(--warn)" : "var(--teal)"
                              }}>
                                ₹{Number(inst.balance_after).toLocaleString("en-IN")}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}

                  {/* Cycle subtotal */}
                  <div style={{
                    background: "var(--surface2)", padding: "6px 14px",
                    borderTop: "1px solid var(--border)", fontSize: 12,
                    display: "flex", justifyContent: "space-between"
                  }}>
                    <span style={{ color: "var(--text3)" }}>
                      Total Paid: <strong style={{ color: "var(--accent)" }}>
                        ₹{Number(p.amount_paid).toLocaleString("en-IN")}
                      </strong>
                    </span>
                    <strong style={{ color: parseFloat(p.balance) > 0 ? "var(--warn)" : "var(--teal)" }}>
                      Balance: ₹{Number(p.balance).toLocaleString("en-IN")}
                    </strong>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── View Member Detail Modal (mobile) ───────────── */
function ViewMemberModal({ member: m, onClose, onEdit, onRenew, onPayments, onCancel, onDelete, onChromeNotify }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 420 }} onClick={e => e.stopPropagation()}>
        <div className="modal-title" style={{ marginBottom: 16 }}>Member Details</div>

        {/* ID + Status */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <span style={{
            fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--accent)",
            fontWeight: 700, background: "var(--accent-dim)", padding: "3px 10px", borderRadius: 6
          }}>
            {m.member_id_display || `M${String(m.id).padStart(4, "0")}`}
          </span>
          <span className={`badge ${{ active: "badge-green", expired: "badge-red", cancelled: "badge-gray", paused: "badge-yellow" }[m.status] || "badge-gray"}`}>
            {m.status}
          </span>
        </div>

        {/* Core info */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 16px", marginBottom: 16 }}>
          {[
            { label: "Name", val: m.name },
            { label: "Phone", val: m.phone || "—" },
            { label: "Email", val: m.email || "—" },
            { label: "Gender", val: m.gender || "—" },
            { label: "Plan", val: m.plan_name || "No Plan" },
            { label: "Plan Type", val: m.plan_type || "—" },
            { label: "Renewal", val: m.renewal_date || "—" },
            { label: "Days Left", val: m.days_until_expiry != null ? `${m.days_until_expiry}d` : "—" },
            { label: "Total Paid", val: `₹${Number(m.total_paid || 0).toLocaleString("en-IN")}` },
            { label: "Balance Due", val: (m.balance_due || 0) > 0 ? `₹${Number(m.balance_due).toLocaleString("en-IN")}` : "None" },
          ].map(({ label, val }) => (
            <div key={label}>
              <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 2 }}>{label}</div>
              <div style={{ fontSize: 13, color: "var(--text1)", fontWeight: 500 }}>{val}</div>
            </div>
          ))}
          {m.diet_name && (
            <div style={{ gridColumn: "span 2" }}>
              <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 2 }}>Diet Plan</div>
              <div style={{ fontSize: 13, color: "var(--teal)" }}>🥗 {m.diet_name}</div>
            </div>
          )}
          {m.notes && (
            <div style={{ gridColumn: "span 2" }}>
              <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 2 }}>Notes</div>
              <div style={{ fontSize: 12, color: "var(--text2)" }}>{m.notes}</div>
            </div>
          )}
        </div>

        {/* Actions */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn btn-sm btn-secondary" onClick={onEdit}>Edit</button>
          <button className="btn btn-sm" style={{ background: "rgba(78,124,96,.12)", color: "var(--teal)" }}
            disabled={m.days_until_expiry != null && m.days_until_expiry > 0} onClick={onRenew}>Renew</button>
          <button className="btn btn-sm" style={{ background: "rgba(77,166,255,.12)", color: "var(--info)" }} onClick={onPayments}>
            Payments{(m.balance_due || 0) > 0 ? " ⚠" : ""}
          </button>
          <button className="btn btn-sm" style={{ background: "var(--accent-dim)", color: "var(--accent)" }} onClick={onChromeNotify}>
            🔔 Chrome Notifications
          </button>
          {m.status !== "cancelled" && (
            <button className="btn btn-sm btn-danger" onClick={onCancel}>Cancel</button>
          )}
          <button className="btn btn-sm" style={{ background: "rgba(255,91,91,.15)", color: "var(--danger)", border: "1px solid rgba(255,91,91,.3)" }} onClick={onDelete}>
            🗑 Delete
          </button>
        </div>

        <button className="btn btn-secondary" style={{ width: "100%", marginTop: 14 }} onClick={onClose}>Close</button>
      </div>
    </div>
  );
}

/* ─── Diet Upgrade Modal (standard → premium) ─────── */
function DietUpgradeModal({ memberId, memberRenewalDate, onClose, onBill }) {
  const [dietBase, setDietBase] = useState(0);
  const [gstRate, setGstRate] = useState(18);
  const [amount, setAmount] = useState("");
  const [mode, setMode] = useState("cash");
  const [saving, setSaving] = useState(false);
  const [prevPlanTotal, setPrevPlanTotal] = useState(null);

  useEffect(() => {
    api.get("/finances/gym-settings/").then(r => {
      const s = r.data || {};
      const base = parseFloat(s.DIET_PLAN_AMOUNT) || 0;
      const _r = parseFloat(s.GST_RATE); const rate = isNaN(_r) ? 18 : _r;
      setDietBase(base);
      setGstRate(rate);
      // Prorate by pending membership days (capped at 30)
      let dietDays = 30;
      if (memberRenewalDate) {
        const today = new Date(); today.setHours(0, 0, 0, 0);
        const renewal = new Date(memberRenewalDate); renewal.setHours(0, 0, 0, 0);
        dietDays = Math.min(30, Math.max(0, Math.round((renewal - today) / 86400000)));
      }
      const prorated = dietDays < 30 ? parseFloat((base / 30 * dietDays).toFixed(2)) : base;
      setAmount((prorated * (1 + rate / 100)).toFixed(2));
    }).catch(() => { });
    // Fetch current plan total from latest payment for breakdown display
    api.get("/members/payments/", { params: { member: memberId } }).then(r => {
      const list = Array.isArray(r.data) ? r.data : (r.data?.results ?? []);
      if (list.length > 0) {
        const latest = list.sort((a, b) => new Date(b.paid_date || 0) - new Date(a.paid_date || 0))[0];
        setPrevPlanTotal(parseFloat(latest.total_with_gst || 0));
      }
    }).catch(() => { });
  }, [memberRenewalDate, memberId]);

  // Prorate diet base by pending days for display
  const dietDays = (() => {
    if (!memberRenewalDate) return 30;
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const renewal = new Date(memberRenewalDate); renewal.setHours(0, 0, 0, 0);
    return Math.min(30, Math.max(0, Math.round((renewal - today) / 86400000)));
  })();
  const proratedDietBase = dietDays < 30 ? parseFloat((dietBase / 30 * dietDays).toFixed(2)) : dietBase;
  const dietWithGst = parseFloat((proratedDietBase * (1 + gstRate / 100)).toFixed(2));
  const balance = Math.max(0, dietWithGst - parseFloat(amount || 0));

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const res = await api.post(`/members/list/${memberId}/upgrade-diet/`, {
        amount_paid: parseFloat(amount || 0),
        mode_of_payment: mode,
      });
      toast.success("Diet plan fee recorded!");
      if (res.data.bill) {
        const raw = res.data.bill;
        const dietB = parseFloat(raw.diet_plan_amount || 0);
        const gstAmt = parseFloat((dietB * raw.gst_rate / 100).toFixed(2));
        const addTotal = parseFloat((dietB + gstAmt).toFixed(2));
        const paid = Math.min(parseFloat(amount || 0), addTotal);
        const bal = parseFloat(Math.max(0, addTotal - paid).toFixed(2));
        onBill({
          ...raw,
          is_diet_upgrade:  true,
          plan_name:        "",    // hide plan info box — only showing diet addition
          membership_fee:   0,
          discount_amount:  0,     // hide prior discount — not relevant to this transaction
          pt_fee:           0,
          plan_price:       dietB,
          gst_amount:       gstAmt,
          total_with_gst:   addTotal,
          amount_paid:      paid,
          balance:          bal,
        });
      } else onClose();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to record diet fee");
    } finally { setSaving(false); }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 420 }} onClick={e => e.stopPropagation()}>
        <div className="modal-title">Diet Plan Upgrade — Collect Fee</div>
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 4 }}>
          <div style={{ background: "var(--surface2)", borderRadius: 8, padding: "10px 14px", fontSize: 12 }}>
            {prevPlanTotal != null && (
              <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text2)", marginBottom: 6, paddingBottom: 6, borderBottom: "1px dashed var(--border)" }}>
                <span>Plan Amount (already charged, incl. GST)</span>
                <span style={{ fontFamily: "var(--font-mono)" }}>₹{prevPlanTotal.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "space-between", color: "var(--text2)", marginBottom: 3 }}>
              <span>Diet Plan (base{dietDays < 30 ? `, ${dietDays} days` : ""})</span>
              <span style={{ fontFamily: "var(--font-mono)" }}>₹{proratedDietBase.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", color: "var(--warn)", marginBottom: 3 }}>
              <span>GST ({gstRate}%)</span>
              <span style={{ fontFamily: "var(--font-mono)" }}>₹{(dietWithGst - proratedDietBase).toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 700, color: "var(--teal)", borderTop: "1px solid var(--border)", paddingTop: 6, marginTop: 4 }}>
              <span>Diet Fee (incl. GST)</span>
              <span style={{ fontFamily: "var(--font-mono)" }}>₹{dietWithGst.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
            </div>
            {prevPlanTotal != null && (
              <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 700, color: "var(--accent)", borderTop: "1px solid var(--border)", paddingTop: 6, marginTop: 4 }}>
                <span>New Grand Total (incl. GST)</span>
                <span style={{ fontFamily: "var(--font-mono)" }}>₹{(prevPlanTotal + dietWithGst).toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
              </div>
            )}
          </div>
          <div className="grid-2">
            <div className="form-group">
              <label className="form-label">Amount to Collect (₹)</label>
              <input className="form-input" type="number" onWheel={e => e.target.blur()} min="0" step="0.01" value={amount}
                onChange={e => setAmount(e.target.value)} placeholder="0" />
            </div>
            <div className="form-group">
              <label className="form-label">Mode of Payment</label>
              <select className="form-input" value={mode} onChange={e => setMode(e.target.value)}>
                <option value="cash">Cash</option>
                <option value="card">Card</option>
                <option value="upi">UPI</option>
                <option value="other">Other</option>
              </select>
            </div>
          </div>
          {dietWithGst > 0 && (
            <div style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              background: balance > 0 ? "rgba(255,184,48,.1)" : "rgba(105,114,84,.08)",
              border: `1px solid ${balance > 0 ? "rgba(255,184,48,.3)" : "rgba(105,114,84,.20)"}`,
              borderRadius: 8, padding: "10px 14px", fontSize: 13
            }}>
              <span style={{ color: "var(--text2)" }}>{balance > 0 ? "⚠ Balance remaining" : "✓ Fully paid"}</span>
              <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700, color: balance > 0 ? "var(--warn)" : "var(--accent)" }}>
                ₹{balance.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
              </span>
            </div>
          )}
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? "Recording…" : "Record Diet Fee"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ─── Main page ────────────────────────────────────── */
export default function Members() {
  const navigate = useNavigate();
  const [members, setMembers] = useState([]);
  const [plans, setPlans] = useState([]);
  const [dietPlans, setDietPlans] = useState([]);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [selected, setSelected] = useState(null);
  const [page, setPage] = useState(1);
  const [count, setCount] = useState(0);
  const [bill, setBill] = useState(null);
  const [gymInfo, setGymInfo] = useState({});       // status filter
  const [planFilter, setPlanFilter] = useState("");
  const [balanceFilter, setBalanceFilter] = useState("");
  const [expiringDays, setExpiringDays] = useState("");
  const [dobFrom, setDobFrom] = useState("");
  const [dobTo, setDobTo] = useState("");
  const [confirmState, setConfirmState] = useState(null);
  const [viewMember, setViewMember] = useState(null);
  const [dietUpgradeMemberId, setDietUpgradeMemberId] = useState(null);
  const [chromeNotifyMember, setChromeNotifyMember] = useState(null);


  useEffect(() => {
    document.getElementById("page-title").textContent = "Members";
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { search, page };
      if (filter !== "all") params.status = filter;
      if (planFilter) params.plan = planFilter;
      if (balanceFilter) params.balance_filter = balanceFilter;
      if (expiringDays) params.expiring_days = expiringDays;
      if (dobFrom) params.dob_from = dobFrom;
      if (dobTo) params.dob_to = dobTo;

      const [mRes, pRes, dRes] = await Promise.all([
        api.get("/members/list/", { params }),
        api.get("/members/plans/?active_only=true"),
        api.get("/members/diet-plans/"),
      ]);
      setMembers(mRes.data.results || mRes.data);
      console.log("Members loaded:", mRes.data);
      console.log("Members Result data", mRes.data.results);
      setCount(mRes.data.count || 0);
      setPlans(pRes.data.results || pRes.data);
      setDietPlans(Array.isArray(dRes.data) ? dRes.data : (dRes.data.results ?? []));
    } finally { setLoading(false); }
  }, [search, filter, planFilter, balanceFilter, expiringDays, dobFrom, dobTo, page]);

  useEffect(() => { load(); }, [load]);

  const resetFilters = () => {
    setFilter("all");
    setPlanFilter("");
    setBalanceFilter("");
    setExpiringDays("");
    setDobFrom("");
    setDobTo("");
    setSearch("");
    setPage(1);
  };

  const hasActiveFilters = filter !== "all" || planFilter || balanceFilter || expiringDays || search || dobFrom || dobTo;

  const closeModal = () => { setModal(null); setSelected(null); };
  const afterSave = (data) => {
    const isNewEnroll = data && typeof data === "object" && "newMemberId" in data;
    const isPending = data && typeof data === "object" && data.isPending === true;
    const isUpgrade = data && typeof data === "object" && "upgradeMemberId" in data;
    const isRenewUpgrade = data && typeof data === "object" && data.renewUpgrade === true;

    closeModal();

    if (isRenewUpgrade) {
      navigate(`/trainer-assignments?newMember=${data.memberId}&planId=${data.planId || ""}&from=members&prevType=${data.prevType || "basic"}&renewUpgrade=1`);
      return;
    }

    if (isUpgrade) {
      if (data.upgradeType === "diet_only") {
        load();
        setDietUpgradeMemberId({ id: data.upgradeMemberId, prevType: data.prevType, prevDiet: data.prevDiet });
        return;
      }
      // "pt" (basic→standard/premium) and "pt_only" (dietonly-standard→premium) both go to trainer assign
      navigate(`/trainer-assignments?newMember=${data.upgradeMemberId}&from=members&prevType=${data.prevType || "basic"}`);
      return;
    }

    // Standard/Premium pending: navigate to trainer assignment without refreshing
    if (isPending) {
      navigate(`/trainer-assignments?pending=1&from=members`);
      return;
    }

    load();

    const billData = isNewEnroll ? data.bill : data;
    const newMemberId = isNewEnroll ? data.newMemberId : null;
    const planType = isNewEnroll ? data.planType : null;

    if (newMemberId && (planType === "standard" || planType === "premium")) {
      navigate(`/trainer-assignments?newMember=${newMemberId}&from=members`);
      return;
    }

    if (billData) {
      setBill(billData);
      setGymInfo({
        gym_name: billData.gym_name || "",
        gym_address: billData.gym_address || "",
        gym_phone: billData.gym_phone || "",
        gym_email: billData.gym_email || "",
        gym_gstin: billData.gym_gstin || "",
      });
    }
  };

  const toggleNotifications = (m) => {
    const newVal = !m.notifications_enabled;
    setConfirmState({
      title: newVal ? "Enable Notifications" : "Disable Notifications",
      message: newVal
        ? `Enable WhatsApp notifications for ${m.name}?`
        : `Disable WhatsApp notifications for ${m.name}? They will not receive any WhatsApp messages.`,
      confirmText: newVal ? "Enable" : "Disable",
      onConfirm: async () => {
        setConfirmState(null);
        setMembers(prev => prev.map(x => x.id === m.id ? { ...x, notifications_enabled: newVal } : x));
        try {
          await api.patch(`/members/list/${m.id}/`, { notifications_enabled: newVal });
        } catch {
          setMembers(prev => prev.map(x => x.id === m.id ? { ...x, notifications_enabled: !newVal } : x));
          toast.error("Failed to update notification setting.");
        }
      },
      onCancel: () => setConfirmState(null),
    });
  };

  const cancelMember = (m) => {
    setConfirmState({
      title: "Cancel Membership",
      message: `Cancel membership for ${m.name}?`,
      confirmText: "Cancel Membership",
      onConfirm: async () => {
        setConfirmState(null);
        try {
          await api.post(`/members/list/${m.id}/cancel/`, { reason: "Admin cancelled" });
          toast.success("Member cancelled");
          load();
        } catch (err) {
          toast.error(err.response?.data?.detail || "Failed to cancel member");
        }
      },
      onCancel: () => setConfirmState(null),
    });
  };

  const deleteMember = (m) => {
    setConfirmState({
      title: "Delete Member",
      message: `Permanently delete ${m.name}? This cannot be undone and removes all payment history.`,
      confirmText: "Delete Permanently",
      danger: true,
      onConfirm: async () => {
        setConfirmState(null);
        try {
          await api.delete(`/members/list/${m.id}/`);
          toast.success("Member deleted permanently");
          load();
        } catch (err) {
          toast.error(err.response?.data?.detail || "Failed to delete member");
        }
      },
      onCancel: () => setConfirmState(null),
    });
  };

  return (
    <div>
      {confirmState && <ConfirmModal {...confirmState} />}
      <div className="page-header">
        <div>
          <div className="page-title">Members</div>
          <div className="page-subtitle">Enrollments, renewals, payments and balance tracking</div>
        </div>
        <button className="btn btn-primary" onClick={() => setModal("add")}>
          + Enroll Member
        </button>
      </div>

      {/* ── Filters ── */}
      <div className="members-filters">
        {/* Search */}
        <div className="search-bar">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.35-4.35" />
          </svg>
          <input className="form-input" placeholder="Search name, phone, gym ID…" value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }} style={{ paddingLeft: 38 }} />
        </div>

        {/* Status pills */}
        <div className="filter-pills">
          {["all", "active", "expired", "cancelled", "paused"].map(f => (
            <button key={f}
              className={`filter-pill ${filter === f ? "filter-pill--active" : ""}`}
              onClick={() => { setFilter(f); setPage(1); }}>
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>

        {/* Secondary filter row */}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", width: "100%", marginTop: 6 }}>

          {/* Plan filter */}
          <select
            className="form-input"
            style={{ maxWidth: 200, fontSize: 12 }}
            value={planFilter}
            onChange={e => { setPlanFilter(e.target.value); setPage(1); }}>
            <option value="">All Plans</option>
            {plans.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>

          {/* Balance filter */}
          <select
            className="form-input"
            style={{ maxWidth: 180, fontSize: 12 }}
            value={balanceFilter}
            onChange={e => { setBalanceFilter(e.target.value); setPage(1); }}>
            <option value="">All Balances</option>
            <option value="has_balance">⚠ Has Balance Due</option>
            <option value="no_balance">✓ Fully Paid</option>
          </select>

          {/* DOB date range filter */}
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 12, color: "var(--text3)", whiteSpace: "nowrap" }}>DOB</span>
            <input
              className="form-input"
              type="date"
              value={dobFrom}
              onChange={e => { setDobFrom(e.target.value); setPage(1); }}
              style={{ width: 140, fontSize: 12 }}
              title="DOB from"
            />
            <span style={{ fontSize: 12, color: "var(--text3)" }}>–</span>
            <input
              className="form-input"
              type="date"
              value={dobTo}
              onChange={e => { setDobTo(e.target.value); setPage(1); }}
              style={{ width: 140, fontSize: 12 }}
              title="DOB to"
            />
            {(dobFrom || dobTo) && (
              <button
                style={{ fontSize: 11, color: "var(--text3)", background: "none", border: "none", cursor: "pointer", padding: "0 4px" }}
                onClick={() => { setDobFrom(""); setDobTo(""); setPage(1); }}>✕</button>
            )}
          </div>

          {/* Expiring within N days */}
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 12, color: "var(--text3)", whiteSpace: "nowrap" }}>Expiring in</span>
            <input
              className="form-input"
              type="number" onWheel={e => e.target.blur()} min="1" max="365"
              placeholder="days"
              value={expiringDays}
              onChange={e => { setExpiringDays(e.target.value); setPage(1); }}
              style={{ width: 72, fontSize: 12 }}
            />
            <span style={{ fontSize: 12, color: "var(--text3)" }}>days</span>
            {expiringDays && (
              <button
                style={{ fontSize: 11, color: "var(--text3)", background: "none", border: "none", cursor: "pointer", padding: "0 4px" }}
                onClick={() => { setExpiringDays(""); setPage(1); }}>✕</button>
            )}
          </div>

          {/* Clear all filters */}
          {hasActiveFilters && (
            <button
              className="btn btn-sm btn-secondary"
              style={{ fontSize: 11, marginLeft: "auto" }}
              onClick={resetFilters}>
              ✕ Clear Filters
            </button>
          )}
        </div>
      </div>

      {/* ── Mobile card list (visible only on small screens) ── */}
      <div className="members-mobile-list">
        {loading ? (
          <div style={{ textAlign: "center", padding: 40, color: "var(--text3)" }}>Loading…</div>
        ) : members.length === 0 ? (
          <div style={{ textAlign: "center", padding: 40, color: "var(--text3)" }}>No members found</div>
        ) : members.map(m => (
          <div key={m.id} className="member-mobile-card">
            <div className="member-mobile-card__left">
              <span className="member-mobile-card__id">
                {m.member_id_display || `M${String(m.id).padStart(4, "0")}`}
              </span>
              <span className="member-mobile-card__name">{m.name}</span>
              <span className={`badge ${{ active: "badge-green", expired: "badge-red", cancelled: "badge-gray", paused: "badge-yellow" }[m.status] || "badge-gray"}`} style={{ fontSize: 11 }}>
                {m.status}
              </span>
            </div>
            <button
              className="btn btn-sm"
              style={{ background: "var(--accent-dim)", color: "var(--accent)", border: "1px solid rgba(105,114,84,.28)", whiteSpace: "nowrap" }}
              onClick={() => setViewMember(m)}>
              View Member
            </button>
          </div>
        ))}
        <div className="members-pagination">
          <span style={{ fontSize: 12, color: "var(--text3)" }}>{count} total</span>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn btn-sm btn-secondary" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
            <button className="btn btn-sm btn-secondary" disabled={members.length < 20} onClick={() => setPage(p => p + 1)}>Next →</button>
          </div>
        </div>
      </div>

      {/* ── Desktop table (hidden on small screens) ── */}
      <div className="members-desktop-table">
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>Member</th>
                <th>Plan</th>
                <th>Renewal</th>
                <th style={{ textAlign: "right" }}>Financials</th>
                <th>Status</th>
                <th>Actions</th>
              </tr></thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={6} style={{ textAlign: "center", padding: 40, color: "var(--text3)" }}>Loading…</td></tr>
                ) : members.length === 0 ? (
                  <tr><td colSpan={6} style={{ textAlign: "center", padding: 40, color: "var(--text3)" }}>No members found</td></tr>
                ) : members.map(m => (
                  <tr key={m.id}>

                    {/* ── Member cell: IDs + name + contact + DOB ── */}
                    <td style={{ minWidth: 200 }}>
                      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 3 }}>
                        <span style={{
                          fontFamily: "var(--font-mono)", fontSize: 11,
                          color: "var(--accent)", fontWeight: 700,
                          background: "var(--accent-dim)", padding: "1px 6px", borderRadius: 4
                        }}>
                          {m.member_id_display || `M${String(m.id).padStart(4, "0")}`}
                        </span>
                        {m.gym_member_id && (
                          <span style={{
                            fontFamily: "var(--font-mono)", fontSize: 11,
                            color: "var(--text3)", background: "var(--surface2)",
                            padding: "1px 6px", borderRadius: 4, border: "1px solid var(--border)"
                          }}>
                            {m.gym_member_id}
                          </span>
                        )}
                      </div>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{m.name}</div>
                      <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 2 }}>
                        {m.phone}
                        {m.email && <span> · {m.email}</span>}
                      </div>
                      {m.dob && (
                        <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 1 }}>
                          DOB: {m.dob}
                        </div>
                      )}
                    </td>

                    {/* ── Plan cell: name + type + diet ── */}
                    <td style={{ minWidth: 150 }}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>
                        {m.plan_name || <span style={{ color: "var(--text3)" }}>No Plan</span>}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 2, textTransform: "capitalize" }}>
                        {m.plan_type}
                      </div>
                      {m.diet_name && (
                        <div style={{ fontSize: 11, color: "var(--teal)", marginTop: 2 }}>
                          🥗 {m.diet_name}
                        </div>
                      )}
                    </td>

                    {/* ── Renewal cell: date + days badge ── */}
                    <td style={{ minWidth: 110, whiteSpace: "nowrap" }}>
                      <div style={{
                        fontSize: 13,
                        color: (m.days_until_expiry ?? 99) <= 0 ? "var(--danger)"
                          : (m.days_until_expiry ?? 99) <= 7 ? "var(--warn)" : "var(--text2)"
                      }}>
                        {m.renewal_date || "—"}
                      </div>
                      <div style={{ marginTop: 4 }}>
                        {m.days_until_expiry != null ? (() => {
                          const d = m.days_until_expiry;
                          if (d < 0)  return <span className="badge badge-red">{d}d</span>;
                          if (d === 0) return <span className="badge badge-red">Today</span>;
                          if (d <= 3) return <span className="badge badge-red">{d}d</span>;
                          if (d <= 7) return <span className="badge badge-yellow">{d}d</span>;
                          return <span className="badge badge-blue">{d}d</span>;
                        })() : "—"}
                      </div>
                    </td>

                    {/* ── Financials cell: paid + balance ── */}
                    <td style={{ textAlign: "right", minWidth: 110 }}>
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--accent)" }}>
                        ₹{Number(m.total_paid || 0).toLocaleString("en-IN")}
                      </div>
                      <div style={{ marginTop: 3 }}>
                        {(m.balance_due || 0) > 0
                          ? <span className="badge badge-yellow">
                              ₹{Number(m.balance_due).toLocaleString("en-IN")} due
                            </span>
                          : <span style={{ fontSize: 11, color: "var(--text3)" }}>✓ clear</span>
                        }
                      </div>
                    </td>

                    <td>
                      {statusBadge(m.status)}
                      <button
                        title={m.notifications_enabled !== false ? "Notifications ON — click to disable" : "Notifications OFF — click to enable"}
                        onClick={() => toggleNotifications(m)}
                        style={{
                          display: "block", marginTop: 6,
                          background: "none", border: "none", cursor: "pointer",
                          fontSize: 15, lineHeight: 1, padding: 0,
                          opacity: m.notifications_enabled !== false ? 1 : 0.4,
                        }}
                      >
                        {m.notifications_enabled !== false ? "🔔" : "🔕"}
                      </button>
                    </td>
                    <td style={{ minWidth: 140 }}>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <div style={{ display: "flex", gap: 4 }}>
                          <button className="btn btn-sm btn-secondary"
                            onClick={() => setViewMember(m)}>View</button>
                          <button className="btn btn-sm btn-secondary"
                            onClick={() => { setSelected(m); setModal("edit"); }}>Edit</button>
                          <button className="btn btn-sm"
                            style={{ background: "rgba(45,255,195,.12)", color: "var(--teal)" }}
                            disabled={m.days_until_expiry != null && m.days_until_expiry > 0}
                            onClick={() => { setSelected(m); setModal("renew"); }}>Renew</button>
                        </div>
                        <div style={{ display: "flex", gap: 4 }}>
                          <button className="btn btn-sm"
                            style={{ background: "rgba(77,166,255,.12)", color: "var(--info)" }}
                            onClick={() => { setSelected(m); setModal("payments"); }}>
                            Payments{(m.balance_due || 0) > 0 ? " ⚠" : ""}
                          </button>
                          {m.status !== "cancelled" &&
                            <button className="btn btn-sm btn-danger"
                              onClick={() => cancelMember(m)}>Cancel</button>}
                          <button className="btn btn-sm"
                            style={{ background: "rgba(255,91,91,.15)", color: "var(--danger)", border: "1px solid rgba(255,91,91,.3)" }}
                            onClick={() => deleteMember(m)}>🗑</button>
                        </div>
                      </div>
                    </td>

                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="members-pagination">
            <span style={{ fontSize: 12, color: "var(--text3)" }}>{count} total members</span>
            <div style={{ display: "flex", gap: 6 }}>
              <button className="btn btn-sm btn-secondary" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
              <button className="btn btn-sm btn-secondary" disabled={members.length < 20} onClick={() => setPage(p => p + 1)}>Next →</button>
            </div>
          </div>
        </div>
      </div>{/* end members-desktop-table */}

      {modal === "add" && <MemberModal plans={plans} dietPlans={dietPlans} onClose={closeModal} onSave={afterSave} />}
      {modal === "edit" && selected && <MemberModal member={selected} plans={plans} dietPlans={dietPlans} onClose={closeModal} onSave={afterSave} />}
      {modal === "renew" && selected && <RenewModal member={selected} plans={plans} dietPlans={dietPlans} onClose={closeModal} onSave={afterSave} />}
      {modal === "payments" && selected && (
        <PaymentHistoryModal
          member={selected}
          onClose={closeModal}
          onRefresh={load}
          onBill={(billData) => {
            setBill(billData);
            if (billData.gym_name) setGymInfo({
              gym_name: billData.gym_name,
              gym_address: billData.gym_address,
              gym_phone: billData.gym_phone,
              gym_email: billData.gym_email,
              gym_gstin: billData.gym_gstin,
            });
          }}
          gymInfo={gymInfo}
        />
      )}
      {bill && <MemberBill bill={bill} onClose={() => setBill(null)} />}
      {dietUpgradeMemberId && (
        <DietUpgradeModal
          memberId={dietUpgradeMemberId.id}
          memberRenewalDate={members.find(m => m.id === dietUpgradeMemberId.id)?.renewal_date}
          onClose={async () => {
            // Revert plan_type and diet to previous values on cancel
            if (dietUpgradeMemberId.prevType) {
              try {
                await api.patch(`/members/list/${dietUpgradeMemberId.id}/`, {
                  plan_type: dietUpgradeMemberId.prevType,
                  diet: dietUpgradeMemberId.prevDiet || null,
                });
              } catch {}
              load();
            }
            setDietUpgradeMemberId(null);
          }}
          onBill={(billData) => {
            setDietUpgradeMemberId(null);
            setBill(billData);
          }}
        />
      )}
      {viewMember && (
        <ViewMemberModal
          member={viewMember}
          onClose={() => setViewMember(null)}
          onEdit={() => { setSelected(viewMember); setModal("edit"); setViewMember(null); }}
          onRenew={() => { setSelected(viewMember); setModal("renew"); setViewMember(null); }}
          onPayments={() => { setSelected(viewMember); setModal("payments"); setViewMember(null); }}
          onCancel={() => { cancelMember(viewMember); setViewMember(null); }}
          onDelete={() => { deleteMember(viewMember); setViewMember(null); }}
          onChromeNotify={() => setChromeNotifyMember(viewMember)}
        />
      )}
      {chromeNotifyMember && (
        <ChromeNotifyLinkModal
          member={chromeNotifyMember}
          onClose={() => setChromeNotifyMember(null)}
        />
      )}
    </div>
  );
}