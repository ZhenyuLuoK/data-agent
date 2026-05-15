import { Route, Routes, Navigate } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { HomePage } from './pages/HomePage';
import { TasksPage } from './pages/TasksPage';
import { UploadPage } from './pages/UploadPage';
import { RunsPage } from './pages/RunsPage';
import { RunDetailPage } from './pages/RunDetailPage';
import { SettingsPage } from './pages/SettingsPage';
import { DocsArchitecturePage, DocsPapersPage } from './pages/DocsPages';

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="upload" element={<UploadPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="runs/:runId" element={<RunDetailPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="docs/architecture" element={<DocsArchitecturePage />} />
        <Route path="docs/papers" element={<DocsPapersPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
