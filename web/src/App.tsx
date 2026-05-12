import { Routes, Route, Navigate } from 'react-router-dom';
import AppLayout from './components/layout/AppLayout';
import InputPage from './pages/InputPage';
import RunDashboard from './pages/RunDashboard';

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to="/new" replace />} />
        <Route path="/new" element={<InputPage />} />
        <Route path="/run/:runId" element={<RunDashboard />} />
        <Route path="/run/:runId/:tab" element={<RunDashboard />} />
      </Route>
    </Routes>
  );
}
