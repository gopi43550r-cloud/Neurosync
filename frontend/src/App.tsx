import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import Dashboard from "./pages/Dashboard";
import Documents from "./pages/Documents";
import DocumentDetail from "./pages/DocumentDetail";
import Conflicts from "./pages/Conflicts";
import ConflictDetail from "./pages/ConflictDetail";
import Blackboard from "./pages/Blackboard";
import KnowledgeGraphPage from "./pages/KnowledgeGraph";
import Agents from "./pages/Agents";
import Hypotheses from "./pages/Hypotheses";
import Evidence from "./pages/Evidence";
import Investigations from "./pages/Investigations";
import InvestigationWorkspace from "./pages/InvestigationWorkspace";
import Reports from "./pages/Reports";
import Evaluation from "./pages/Evaluation";
import Audit from "./pages/Audit";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Dashboard />} />
        <Route path="documents" element={<Documents />} />
        <Route path="documents/:id" element={<DocumentDetail />} />
        <Route path="conflicts" element={<Conflicts />} />
        <Route path="conflicts/:id" element={<ConflictDetail />} />
        <Route path="blackboard" element={<Blackboard />} />
        <Route path="knowledge-graph" element={<KnowledgeGraphPage />} />
        <Route path="agents" element={<Agents />} />
        <Route path="hypotheses" element={<Hypotheses />} />
        <Route path="evidence" element={<Evidence />} />
        <Route path="investigations" element={<Investigations />} />
        <Route path="investigations/:id" element={<InvestigationWorkspace />} />
        <Route path="reports" element={<Reports />} />
        <Route path="evaluation" element={<Evaluation />} />
        <Route path="audit" element={<Audit />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
