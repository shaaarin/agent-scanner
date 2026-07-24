import { Route, Routes } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { Header } from "./components/Header";
import { Dashboard } from "./pages/Dashboard";
import { Templates } from "./pages/Templates";
import { LLMModels } from "./pages/LLMModels";
import { AgentConfigs } from "./pages/AgentConfigs";
import { Campaigns } from "./pages/Campaigns";
import { ScanDetail } from "./pages/ScanDetail";
import { FuzzRuns } from "./pages/FuzzRuns";
import { FuzzRunDetail } from "./pages/FuzzRunDetail";
import { TreeRuns } from "./pages/TreeRuns";
import { TreeRunDetail } from "./pages/TreeRunDetail";
import { Events } from "./pages/Events";
import { Findings } from "./pages/Findings";

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
            <Route path="/templates" element={<Templates />} />
            <Route path="/llm-models" element={<LLMModels />} />
            <Route path="/agent-configs" element={<AgentConfigs />} />
            <Route path="/campaigns" element={<Campaigns />} />
            <Route path="/campaigns/:id" element={<ScanDetail />} />
            <Route path="/fuzz-runs" element={<FuzzRuns />} />
            <Route path="/fuzz-runs/:id" element={<FuzzRunDetail />} />
            <Route path="/tree-runs" element={<TreeRuns />} />
            <Route path="/tree-runs/:id" element={<TreeRunDetail />} />
            <Route path="/events" element={<Events />} />
            <Route path="/findings" element={<Findings />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
