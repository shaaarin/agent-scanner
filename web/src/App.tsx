import { Navigate, Route, Routes } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { Header } from "./components/Header";
import { Dashboard } from "./pages/Dashboard";
import { LLMModels } from "./pages/LLMModels";
import { Events } from "./pages/Events";
import { Scans } from "./pages/Scans";
import { ScansDetail } from "./pages/ScansDetail";
import { Help } from "./pages/Help";
import { Library } from "./pages/Library";
import { Assets } from "./pages/Assets";
import { AssetDetail } from "./pages/AssetDetail";
import { Organizations } from "./pages/Organizations";
import { InvitePage } from "./pages/InvitePage";
import { LoginScreen } from "./components/LoginScreen";
import { useAuth } from "./auth/AuthContext";

export default function App() {
  const {loading, user} = useAuth();

  if (loading) {
    return (
      <div
        style={{
          minHeight: "100dvh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-500)",
        }}
      >
        Загрузка…
      </div>
    );
  }
  // Не вошли (и авторизация настроена) -- весь интерфейс закрыт экраном входа.
  if (user == null) {
    return <LoginScreen />;
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateAreas: `"sidebar header" "sidebar main"`,
        gridTemplateRows: "var(--header-height) auto",
        gridTemplateColumns: "var(--sidebar-width) minmax(0, 1fr)",
        minHeight: "100dvh",
      }}
    >
      <Sidebar />
      <Header />
      <main
        style={{
          gridArea: "main",
          minWidth: 0,
          background: "var(--background-warm)",
          minHeight: "calc(100dvh - var(--header-height))",
        }}
      >
        <div className="app-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/help" element={<Help />} />
            <Route path="/assets" element={<Assets />} />
            <Route path="/assets/:kind/:id" element={<AssetDetail />} />
            {/* Конфигурации агентов переехали в раздел «Активы». */}
            <Route path="/agent-configs" element={<Navigate to="/assets?tab=agent" replace />} />
            <Route path="/scans" element={<Scans />} />
            <Route path="/scans/:id" element={<ScansDetail />} />
            <Route path="/llm-models" element={<LLMModels />} />
            <Route path="/orgs" element={<Organizations />} />
            <Route path="/invite/:token" element={<InvitePage />} />
            <Route path="/library" element={<Library />} />
            <Route path="/events" element={<Events />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
