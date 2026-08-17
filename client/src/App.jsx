import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { FarmDataProvider } from "./context/FarmDataContext";
import { AppShell } from "./components/AppShell";
import { MonitorPage } from "./pages/MonitorPage";
import { ChatPage } from "./pages/ChatPage";
import { SettingsPage } from "./pages/SettingsPage";
import { FarmManagePage } from "./pages/FarmManagePage";

export default function App() {
  return (
    <BrowserRouter>
      <FarmDataProvider>
        <AppShell>
          <Routes>
            <Route path="/" element={<MonitorPage />} />
            <Route path="/farm" element={<FarmManagePage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/ai" element={<Navigate to="/settings" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppShell>
      </FarmDataProvider>
    </BrowserRouter>
  );
}
