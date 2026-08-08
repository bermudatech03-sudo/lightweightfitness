import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useState } from "react";
import "./Layout.css";

function LogoutConfirmModal({ onConfirm, onCancel }) {
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal" style={{ maxWidth: 380 }} onClick={e => e.stopPropagation()}>
        <div style={{ textAlign: "center", padding: "8px 0 16px" }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>⏏</div>
          <div className="modal-title" style={{ marginBottom: 8 }}>Confirm Logout</div>
          <p style={{ color: "var(--text2)", fontSize: 14, margin: "0 0 24px" }}>
            Are you sure you want to logout?
          </p>
          <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
            <button className="btn btn-secondary" style={{ minWidth: 100 }} onClick={onCancel}>
              Cancel
            </button>
            <button className="btn btn-danger" style={{ minWidth: 100 }} onClick={onConfirm}>
              Logout
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

const NAV = [
  { to:"/dashboard",     icon:"⬡",  label:"Dashboard" },
  { to:"/members",       icon:"◈",  label:"Members" },
  { to:"/plans",         icon:"◉",  label:"Membership Plans" },
  { to:"/diets",                icon:"◯",  label:"Diets" },
  { to:"/trainer-assignments", icon:"⊛",  label:"Trainer Assign" },
  { to:"/staff",               icon:"◆",  label:"Staff" },
  { to:"/attendance",    icon:"✓",  label:"Attendance" },
  { to:"/equipment",     icon:"◇",  label:"Equipment" },
  { to:"/finances",      icon:"◎",  label:"Finances" },
  { to:"/enquiries",     icon:"◑",  label:"Enquiries" },
  { to:"/notifications", icon:"⚇",  label:"Notifications" },
  { to:"/notify-permissions", icon:"🔔", label:"Notify Permissions" },
  { to:"/settings",      icon:"⚙",  label:"Settings" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);

  const handleLogout = () => setShowLogoutConfirm(true);
  const confirmLogout = () => { logout(); navigate("/login"); };

  return (
    <div className={`layout ${collapsed ? "layout--collapsed" : ""}`}>
      {showLogoutConfirm && (
        <LogoutConfirmModal
          onConfirm={confirmLogout}
          onCancel={() => setShowLogoutConfirm(false)}
        />
      )}
      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="sidebar-overlay" onClick={() => setMobileOpen(false)} />
      )}
      <aside className={`sidebar ${mobileOpen ? "sidebar--mobile-open" : ""}`}>
        <div className="sidebar__logo">
            <img 
              src="/light-weight_fitness_logo.jpeg" 
              alt="Light Weight Fitness Logo" 
              className="login-logo-img"
              style={{ width: "50px", height: "50px", borderRadius: "50%", objectFit: "cover" }}
            />
          <div className="sidebar__logo-text">
            <span className="sidebar__logo-name">GymPro</span>
            <span className="sidebar__logo-sub">CRM</span>
          </div>
          <button
            className="sidebar__collapse"
            onClick={() => setCollapsed(p => !p)}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? "›" : "‹"}
          </button>
        </div>

        <nav className="sidebar__nav">
          {NAV.map(n => (
            <NavLink key={n.to} to={n.to}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) =>
                `sidebar__link ${isActive ? "sidebar__link--active" : ""}`}>
              <span className="sidebar__link-icon">{n.icon}</span>
              <span className="sidebar__link-label">{n.label}</span>
            </NavLink>
          ))}

          {/* Kiosk quick-launch */}
          <a href="/kiosk" target="_blank" rel="noopener"
            className="sidebar__link sidebar__link--kiosk"
            title="Open Kiosk"
            onClick={() => setMobileOpen(false)}>
            <span className="sidebar__link-icon">⊙</span>
            <span className="sidebar__link-label">Kiosk ↗</span>
          </a>
        </nav>

        <div className="sidebar__footer">
          <div className="sidebar__user">
            <div className="sidebar__avatar">
              {user?.full_name?.[0] || user?.username?.[0] || "A"}
            </div>
            <div className="sidebar__user-info">
              <span className="sidebar__user-name">{user?.full_name||user?.username}</span>
              <span className="sidebar__user-role">{user?.role}</span>
            </div>
          </div>
          <button className="sidebar__logout" onClick={handleLogout} title="Logout">⏏</button>
        </div>
      </aside>

      <div className="main-area">
        <header className="topbar">
          <div className="topbar__left">
            <button className="topbar__hamburger" onClick={() => setMobileOpen(p => !p)} aria-label="Toggle menu">
              ☰
            </button>
            <div className="topbar__title" id="page-title">Dashboard</div>
          </div>
          <div className="topbar__right">
            <div className="topbar__badge badge badge-green"><span>●</span> Live</div>
            <div className="topbar__date">
              {new Date().toLocaleDateString("en-IN",{weekday:"long",year:"numeric",month:"long",day:"numeric"})}
            </div>
          </div>
        </header>
        <main className="content"><Outlet /></main>
      </div>
    </div>
  );
}