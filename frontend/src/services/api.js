/**
 * api.js — VELOR Frontend API Client
 * =====================================
 */
import axios from 'axios';
import { resolveRuntimeApiBase } from './apiBase';

export const API_BASE = resolveRuntimeApiBase(
    import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_URL,
    typeof window !== 'undefined' ? window.location : null
);

export const OWNER_API_TIMEOUT_MS = 15_000;
export const PUBLIC_CHAT_TIMEOUT_MS = 25_000;

// rawClient is an axios instance WITHOUT the response interceptor.
// It's used for sensitive verification calls (e.g., /me) to avoid interceptor recursion/deadlock.
export const rawClient = axios.create({
    baseURL: API_BASE,
    withCredentials: true,
    timeout: OWNER_API_TIMEOUT_MS,
});

// Public Web Chat uses its own bearer session token but shares the same
// environment-aware base URL as the authenticated console.
export const publicClient = axios.create({
    baseURL: API_BASE,
    timeout: PUBLIC_CHAT_TIMEOUT_MS,
});

// 1️⃣ هنا اللقطة السحرية: withCredentials بتخلي المتصفح يبعت الكوكيز تلقائي
const api = axios.create({ 
    baseURL: API_BASE,
    timeout: OWNER_API_TIMEOUT_MS,
    withCredentials: true // 👈 دي اللي كانت ناقصة ومخلياه يطردك!
});

// ── Response interceptor: auto-refresh on 401 ────
let _refreshing = false;
let _queue = [];

// Helper to clear only auth-related localStorage keys on logout
function clearAuthStorage() {
    try {
        localStorage.removeItem('company_id');
        localStorage.removeItem('role');
        localStorage.removeItem('plan');
    // eslint-disable-next-line unused-imports/no-unused-vars
    } catch (e) {
        // ignore
    }
}

api.interceptors.response.use(
    (res) => res,
    async (error) => {
        const original = error.config;
        const originalUrl = original?.url || '';
        const isAuthRoute = originalUrl.includes('/login') || originalUrl.includes('/signup');

        if (!original) {
            return Promise.reject(error);
        }

        if (error.response?.status === 401 && !original._retry && !isAuthRoute) {
            if (_refreshing) {
                // لو في ريكويست بيعمل ريفريش، الباقي يستنى في الطابور
                return new Promise((resolve, reject) => {
                    _queue.push({ resolve, reject });
                }).then(() => api(original)).catch(() => Promise.reject(error));
            }
            original._retry = true;
            _refreshing = true;
            
            try {
                // Backend reads cookie and rotates tokens as needed
                await axios.post(`${API_BASE}/token/refresh`, {}, { withCredentials: true, timeout: OWNER_API_TIMEOUT_MS });

                // Verify /me to ensure session is valid and get updated user info.
                // Use rawClient to avoid invoking this interceptor again (prevents deadlock).
                try {
                    await rawClient.get('/me');
                // eslint-disable-next-line unused-imports/no-unused-vars
                } catch (_) {
                    throw new Error('me_failed');
                }

                // Resolve queued requests
                _queue.forEach(({ resolve }) => resolve());
                _queue = [];
                _refreshing = false;
                return api(original);
            } catch (err) {
                // Refresh failed -> reject queued promises and perform graceful logout
                _queue.forEach(({ reject }) => reject(err));
                _queue = [];
                _refreshing = false;
                clearAuthStorage();
                // redirect to login preserving current path for UX
                // eslint-disable-next-line unused-imports/no-unused-vars
                try { window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`; } catch (e) { window.location.href = '/login'; }
                return Promise.reject(err);
            }
        }
        return Promise.reject(error);
    }
);

// ── Auth ──────────────────────────────────────────
export const logout = () => api.post('/logout');
export const login = (data) => api.post('/login', data);
export const signup = (data) => api.post('/signup', data);
export const googleAuth = (data) => api.post('/auth/google', data);
export const refreshToken = () => api.post('/token/refresh'); // اتعدلت عشان الكوكيز
export const revokeToken = () => api.post('/token/revoke'); 

// ── Company ───────────────────────────────────────
export const getMe = () => api.get('/me');
export const getCompaniesList = () => api.get('/companies-list');
export const rotateApiKey = () => api.post('/rotate-api-key'); // #4

// ── Dashboard ─────────────────────────────────────
export const getStats = (companyId) => api.get('/stats', { params: { company_id: companyId } });

// ── Leads (#9 pagination) ─────────────────────────
export const getLeads = (companyId, page = 1, pageSize = 20) =>
    api.get('/leads', { params: { company_id: companyId, page, page_size: pageSize } });

export const exportLeads = (companyId) =>
    api.get('/export-leads', { params: { company_id: companyId }, responseType: 'blob' });

// ── Conversations (#9 pagination) ─────────────────
export const getConversations = (companyId, page = 1, limit = 20, userId = null) => {
    const params = { company_id: companyId, page, limit };
    if (userId) params.user_id = userId;
    return api.get('/api/conversations', { params });
};

// ── Bot Knowledge ─────────────────────────────────
export const getBotKnowledge = () => api.get(`/whatsapp/settings`);
export const saveBotKnowledge = (data) => api.post(`/whatsapp/settings/update`, data);
export const generateWizardPrompt = (data) => api.post(`/api/wizard/generate`, data);

// ── Smart Alerts ──────────────────────────────────
export const getAlertSettings = () => api.get(`/whatsapp/settings/alerts`);
export const saveAlertSettings = (data) => api.put(`/whatsapp/settings/alerts`, data);

// ── Enterprise Features ───────────────────────────
export const getLatestLeads = (companyId) => api.get('/api/whatsapp/leads/latest', { params: { limit: 10, company_id: companyId } });
export const toggleAgentPause = (phone) => api.post(`/whatsapp/agent/toggle-pause`, { phone });
export const getAgentPauseStatus = (phone) => api.get('/whatsapp/agent/pause-status', { params: { phone } });

// ── Audit Logs ────────────────────────────────────
export const getAuditLogs = (page = 1, pageSize = 50) => api.get('/audit-logs', { params: { page, page_size: pageSize } });

// ── Intelligence Center ─────────────────────────────
export const getBusinessInsights = ({ days, channel, signal } = {}) => {
    const params = {};
    if (days !== null && days !== undefined && days !== '') params.days = days;
    if (channel) params.channel = channel;
    return api.get('/api/v1/intelligence/business-insights', { params, signal });
};

export const getRecoveryImpact = ({ days, channel, signal } = {}) =>
    api.get('/api/v1/operations/recovery-impact', { params: { days, channel }, signal });

export const getFollowUps = ({ leadId, status = 'pending,snoozed', dueOnly = false, signal } = {}) =>
    api.get('/api/v1/operations/follow-ups', {
        params: { lead_id: leadId, status, due_only: dueOnly },
        signal,
    });

export const completeFollowUp = (taskId) => api.post(`/api/v1/operations/follow-ups/${taskId}/complete`);
export const dismissFollowUp = (taskId) => api.post(`/api/v1/operations/follow-ups/${taskId}/dismiss`);
export const snoozeFollowUp = (taskId, snoozedUntil) =>
    api.post(`/api/v1/operations/follow-ups/${taskId}/snooze`, { snoozed_until: snoozedUntil });

export const recordProductEvents = (events) =>
    api.post('/api/v1/operations/telemetry', { events });

export const createClientEventId = (prefix = 'event') => {
    const random = typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    return `${prefix}:${random}`;
};

export default api;
