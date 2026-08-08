import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./hooks/useAuth";
import Layout from "./components/Layout";
import Kiosk from "./pages/Kiosk/Kiosk";
import Login from "./pages/Login/Login";
import Dashboard from "./pages/Dashboard/Dashboard";
import Members from "./pages/Members/Members";
import Staff from "./pages/Staff/Staff";
import Equipment from "./pages/Equipment/Equipment";
import Finances from "./pages/Finances/Finances";
import Notifications from "./pages/Notifications/Notifications";
import Plans from "./pages/Plans/plans";
import Attendance from "./pages/Attendance/Attendance";
import Settings from "./pages/Settings/Settings";
import Diets from "./pages/Diet/DietPage";
import TrainerAssignments from "./pages/TrainerAssignments/TrainerAssignments";
import Enquiry from "./pages/Enquiry/Enquiry";
import MemberNotifyOptIn from "./pages/MemberNotifyOptIn/MemberNotifyOptIn";
function Protected({ children }) {
  const { user } = useAuth();
  return user ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public — no login needed */}
          <Route path="/login" element={<Login />} />
          <Route path="/kiosk" element={<Kiosk />} />
          {/* Obscure, hard-to-guess path — reached only via the QR the admin shows */}
          <Route path="/nx7qk2vwmz9pfhrb3jt/" element={<MemberNotifyOptIn />} />

          {/* Protected dashboard */}
          <Route path="/" element={<Protected><Layout /></Protected>}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="members/*" element={<Members />} />
            <Route path="plans" element={<Plans />} />
            <Route path="diets" element={<Diets />} />
            <Route path="staff/*" element={<Staff />} />
            <Route path="equipment/*" element={<Equipment />} />
            <Route path="finances/*" element={<Finances />} />
            <Route path="trainer-assignments" element={<TrainerAssignments />} />
            <Route path="attendance" element={<Attendance />} />
            <Route path="notifications" element={<Notifications />} />
            <Route path="enquiries" element={<Enquiry />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}