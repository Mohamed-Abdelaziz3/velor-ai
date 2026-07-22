import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { VelorLogo } from './velor/VelorLogo';

export default function ProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-5 bg-velor-bg text-velor-text">
        <VelorLogo size={38} wordmarkClassName="text-base" />
        <span className="h-7 w-7 animate-spin rounded-full border-2 border-white/10 border-t-velor-purple" role="status" aria-label="جاري التحقق من الجلسة الآمنة" />
      </div>
    );
  }

  if (!isAuthenticated) {
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace state={{ next }} />;
  }

  return children;
}
