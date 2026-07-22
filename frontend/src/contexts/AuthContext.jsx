import { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import { rawClient } from '../services/api';

const AuthContext = createContext(null);

// eslint-disable-next-line react-refresh/only-export-components
export const useAuth = () => {
    const ctx = useContext(AuthContext);
    if (!ctx) throw new Error('useAuth must be used within AuthProvider');
    return ctx;
};

export const AuthProvider = ({ children }) => {
    const [companyId, setCompanyId] = useState(() => localStorage.getItem('company_id') || '');
    const [role, setRole] = useState(() => localStorage.getItem('role') || 'tenant');
    const [plan, setPlan] = useState(() => localStorage.getItem('plan') || 'FREE');
    const [loading, setLoading] = useState(true);
    const sessionEpochRef = useRef(0);

    const isAuthenticated = Boolean(companyId);

    const loginUser = useCallback((data) => {
        // Fence an initial /me request that may have started before login and
        // would otherwise clear this fresh session when its old 401 arrives.
        sessionEpochRef.current += 1;
        localStorage.setItem('company_id', data.company_id);
        localStorage.setItem('role', data.role || 'tenant');
        localStorage.setItem('plan', data.plan || 'FREE');
        setCompanyId(data.company_id);
        setRole(data.role || 'tenant');
        setPlan(data.plan || 'FREE');
    }, []);

    const logoutUser = useCallback(() => {
        sessionEpochRef.current += 1;
        try {
            localStorage.removeItem('company_id');
            localStorage.removeItem('role');
            localStorage.removeItem('plan');
        // eslint-disable-next-line unused-imports/no-unused-vars
        } catch (e) { /* ignore */ }
        setCompanyId('');
        setRole('tenant');
        setPlan('FREE');
    }, []);

    // On mount, verify session with server via /me using rawClient to avoid interceptor recursion.
    useEffect(() => {
        let mounted = true;
        const hydrationEpoch = sessionEpochRef.current;
        const currentPath = typeof window === 'undefined' ? '' : window.location.pathname;

        // Public customer chat has its own scoped visitor token. Probing the
        // merchant session there creates a guaranteed 401 for real customers
        // and adds noise without changing access to the page.
        if (/^\/(?:c|chat)\//.test(currentPath)) {
            // Keep an owner session in storage, but never activate merchant
            // SSE/auth state inside a customer-facing visitor page.
            setCompanyId('');
            setRole('tenant');
            setPlan('FREE');
            setLoading(false);
            return () => { mounted = false; };
        }
        if (['/', '/terms', '/privacy'].includes(currentPath) && !localStorage.getItem('company_id')) {
            setLoading(false);
            return () => { mounted = false; };
        }
        (async () => {
            try {
                const res = await rawClient.get('/me');
                if (!mounted || sessionEpochRef.current !== hydrationEpoch) return;
                if (res?.data?.company_id) {
                    const data = res.data;
                    localStorage.setItem('company_id', data.company_id);
                    localStorage.setItem('role', data.role || 'tenant');
                    localStorage.setItem('plan', data.plan || 'FREE');
                    setCompanyId(data.company_id);
                    setRole(data.role || 'tenant');
                    setPlan(data.plan || 'FREE');
                } else {
                    // server says not authenticated
                    logoutUser();
                }
            // eslint-disable-next-line unused-imports/no-unused-vars
            } catch (e) {
                // On any error assume not authenticated
                if (sessionEpochRef.current === hydrationEpoch) logoutUser();
            } finally {
                if (mounted) setLoading(false);
            }
        })();
        return () => { mounted = false; };
    }, [logoutUser]);

    return (
        <AuthContext.Provider value={{ companyId, role, plan, isAuthenticated, loginUser, logoutUser, loading }}>
            {children}
        </AuthContext.Provider>
    );
};

export default AuthContext;
