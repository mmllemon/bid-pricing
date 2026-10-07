import { Routes, Route } from 'react-router-dom';
import AppShell from './components/AppShell';
import HomePage from './pages/Home';
import TodosPage from './pages/Todos';
import PerformancePage from './pages/Performance';
import ScanPage from './pages/Scan';
import SettingsPage from './pages/Settings';
import HotspotsPage from './pages/Hotspots';
import KnowledgePage from './pages/Knowledge';
import FinancePage from './pages/Finance';
import BizPage from './pages/Biz';
import BizDetailPage from './pages/BizDetail';
import PortalPage from './features/portal/Portal';
import ToolsHome from './features/tools/ToolsHome';
import ToolDuct from './features/tools/ToolDuct';
import ToolEarth from './features/tools/ToolEarth';
import ToolCable from './features/tools/ToolCable';
import ToolWell from './features/tools/ToolWell';

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/portal" element={<PortalPage />} />
        <Route path="/tools" element={<ToolsHome />} />
        <Route path="/tools/duct" element={<ToolDuct />} />
        <Route path="/tools/earth" element={<ToolEarth />} />
        <Route path="/tools/cable" element={<ToolCable />} />
        <Route path="/tools/well" element={<ToolWell />} />
        <Route path="/" element={<HomePage />} />
        <Route path="/todos" element={<TodosPage />} />
        <Route path="/performance" element={<PerformancePage />} />
        <Route path="/hotspots" element={<HotspotsPage />} />
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="/scan" element={<ScanPage />} />
        <Route path="/finance" element={<FinancePage />} />
        <Route path="/biz" element={<BizPage />} />
        <Route path="/biz/:id" element={<BizDetailPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
