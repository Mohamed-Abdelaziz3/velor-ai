import { lazy, Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useParams } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { ThemeProvider } from './contexts/ThemeContext';
import { GlobalEventProvider } from './contexts/GlobalEventContext';
import ErrorBoundary from './components/ErrorBoundary';
import ProtectedRoute from './components/ProtectedRoute';
import { Toaster } from 'react-hot-toast';

const Layout = lazy(() => import('./components/Layout'));
const LandingPage = lazy(() => import('./pages/LandingPage'));
const Login = lazy(() => import('./pages/Login'));
const Signup = lazy(() => import('./pages/Signup'));
const Terms = lazy(() => import('./pages/Terms'));
const Privacy = lazy(() => import('./pages/Privacy'));
const NotFound = lazy(() => import('./pages/NotFound'));
const PublicChat = lazy(() => import('./pages/PublicChat'));
const CustomerWorkspace = lazy(() => import('./pages/dashboard/CustomerWorkspace'));
const Dashboard = lazy(() => import('./pages/velor/Dashboard'));
const Inbox = lazy(() => import('./pages/velor/Inbox'));
const Analytics = lazy(() => import('./pages/velor/Analytics'));
const AutomationBuilder = lazy(() => import('./pages/velor/AutomationBuilder'));
const Onboarding = lazy(() => import('./pages/velor/Onboarding'));
const Settings = lazy(() => import('./pages/velor/Settings'));
const Billing = lazy(() => import('./pages/velor/Billing'));

function LegacyPublicChatRedirect() {
  const { slug } = useParams();
  return <Navigate to={`/c/${slug}`} replace />;
}

function LegacyCustomerWorkspaceRedirect() {
  const { id } = useParams();
  return <Navigate to={`/inbox/${id}`} replace />;
}

function RouteLoadingState() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-velor-bg text-velor-text" role="status" aria-label="جاري تحميل VELOR">
      <span className="h-8 w-8 animate-spin rounded-full border-2 border-velor-purple/25 border-t-velor-purple" aria-hidden="true" />
    </div>
  );
}

function App() {
  return (
    <ThemeProvider>
      <ErrorBoundary>
        <Toaster
          position="top-center"
          reverseOrder={false}
          toastOptions={{
            duration: 3800,
            className: 'font-sans text-sm',
            style: {
              background: '#151824',
              color: '#f7f5ff',
              border: '1px solid rgba(211,205,255,.14)',
              borderRadius: '12px',
              boxShadow: '0 20px 60px rgba(0,0,0,.38)',
            },
            success: { iconTheme: { primary: '#31d6a0', secondary: '#10121c' } },
            error: { iconTheme: { primary: '#ff647d', secondary: '#10121c' } },
          }}
        />
        <Router>
          <AuthProvider>
            <GlobalEventProvider>
              <Suspense fallback={<RouteLoadingState />}>
                <Routes>
                  <Route path="/" element={<LandingPage />} />
                  <Route path="/login" element={<Login />} />
                  <Route path="/signup" element={<Signup />} />
                  <Route path="/terms" element={<Terms />} />
                  <Route path="/privacy" element={<Privacy />} />
                  <Route path="/c/:slug" element={<PublicChat />} />
                  <Route path="/chat/:slug" element={<LegacyPublicChatRedirect />} />

                  <Route path="/onboarding" element={<ProtectedRoute><Onboarding /></ProtectedRoute>} />
                  <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
                    <Route path="/dashboard" element={<Dashboard />} />
                    <Route path="/inbox" element={<Inbox />} />
                    <Route path="/inbox/:id" element={<CustomerWorkspace />} />
                    <Route path="/analytics" element={<Analytics />} />
                    <Route path="/automations" element={<AutomationBuilder />} />
                    <Route path="/settings" element={<Settings />} />
                    <Route path="/billing" element={<Billing />} />
                    <Route path="/customers/:id" element={<LegacyCustomerWorkspaceRedirect />} />
                    <Route path="/customers" element={<Navigate to="/inbox" replace />} />
                    <Route path="/bot-settings" element={<Navigate to="/automations" replace />} />
                    <Route path="/business-intelligence" element={<Navigate to="/analytics" replace />} />
                    <Route path="/ai-reports" element={<Navigate to="/analytics" replace />} />
                  </Route>

                  <Route path="*" element={<NotFound />} />
                </Routes>
              </Suspense>
            </GlobalEventProvider>
          </AuthProvider>
        </Router>
      </ErrorBoundary>
    </ThemeProvider>
  );
}

export default App;
