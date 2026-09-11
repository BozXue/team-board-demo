import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { ProjectShell } from "./components/layout/ProjectShell";
import BatchPage from "./pages/BatchPage";
import CopilotPage from "./pages/CopilotPage";
import DataPage from "./pages/DataPage";
import DevicesPage from "./pages/DevicesPage";
import ModelsPage from "./pages/ModelsPage";
import MonitorPage from "./pages/MonitorPage";
import PipelinePage from "./pages/PipelinePage";
import ProjectsPage from "./pages/ProjectsPage";
import RuntimePage from "./pages/RuntimePage";
import SamPage from "./pages/SamPage";
import { Toasts } from "./components/ui";
import { useApp } from "./store/app";

export default function App() {
  const boot = useApp((s) => s.boot);
  const appName = useApp((s) => s.meta?.appName);

  useEffect(() => {
    void boot();
  }, [boot]);

  useEffect(() => {
    if (appName) document.title = appName;
  }, [appName]);

  return (
    <>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<ProjectsPage />} />
          <Route path="monitor" element={<MonitorPage />} />
          <Route path="devices" element={<DevicesPage />} />
          <Route path="projects/:projectId" element={<ProjectShell />}>
            <Route index element={<Navigate to="data" replace />} />
            <Route path="data" element={<DataPage />} />
            <Route path="copilot" element={<CopilotPage />} />
            <Route path="pipeline" element={<PipelinePage />} />
            <Route path="batch" element={<BatchPage />} />
            <Route path="models" element={<ModelsPage />} />
            <Route path="sam" element={<SamPage />} />
            <Route path="runtime" element={<RuntimePage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
      <Toasts />
    </>
  );
}
