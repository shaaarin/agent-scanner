import { Route, Routes } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { Header } from "./components/Header";
import { Dashboard } from "./pages/Dashboard";
import { LLMModels } from "./pages/LLMModels";
import { AgentConfigs } from "./pages/AgentConfigs";
import { Events } from "./pages/Events";
import { Scans } from "./pages/Scans";
import { ScansDetail } from "./pages/ScansDetail";
import { Help } from "./pages/Help";
import { MCPScanners } from "./pages/MCPScanners";
import { Library } from "./pages/Library";

export default function App() {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateAreas: `"sidebar header" "sidebar main"`,
        gridTemplateRows: "var(--header-height) auto",
        gridTemplateColumns: "var(--sidebar-width) auto",
        minHeight: "100dvh",
      }}
    >
      <Sidebar />
      <Header />
      <main
        style={{
          gridArea: "main",
          background: "var(--background-warm)",
          minHeight: "calc(100dvh - var(--header-height))",
        }}
      >
        <div style={{ maxWidth: 1200, margin: "0 auto", padding: "3.2rem" }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/help" element={<Help />} />
            <Route path="/mcp-scanners" element={<MCPScanners />} />
            <Route path="/scans" element={<Scans />} />
            <Route path="/scans/:id" element={<ScansDetail />} />
            <Route path="/llm-models" element={<LLMModels />} />
            <Route path="/agent-configs" element={<AgentConfigs />} />
            <Route path="/library" element={<Library />} />
            <Route path="/events" element={<Events />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
