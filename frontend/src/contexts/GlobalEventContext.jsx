import { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import api from '../services/api';
import { toast } from 'react-hot-toast';
import { useAuth } from './AuthContext';

const GlobalEventContext = createContext();
const MAX_RECONNECT_ATTEMPTS = 5;

// eslint-disable-next-line react-refresh/only-export-components
export const useGlobalEvents = () => {
    const context = useContext(GlobalEventContext);
    if (!context) {
        throw new Error('useGlobalEvents must be used within a GlobalEventProvider');
    }
    return context;
};

export const GlobalEventProvider = ({ children }) => {
    const { isAuthenticated, loading } = useAuth();
    const [lastEvent, setLastEvent] = useState(null);
    const [connectionState, setConnectionState] = useState('idle');
    const [connectedAt, setConnectedAt] = useState(null);
    const [lastEventAt, setLastEventAt] = useState(null);
    const eventSourceRef = useRef(null);
    const reconnectTimeoutRef = useRef(null);
    const reconnectAttempts = useRef(0);

    const connectSSE = useCallback(() => {
        if (eventSourceRef.current) {
            const previousSource = eventSourceRef.current;
            eventSourceRef.current = null;
            previousSource.close();
        }
        if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current);
            reconnectTimeoutRef.current = null;
        }

        setConnectionState(reconnectAttempts.current > 0 ? 'reconnecting' : 'connecting');
        const baseUrl = api.defaults.baseURL || globalThis.location?.origin || 'http://localhost:8000';
        let evtSource;
        try {
            evtSource = new EventSource(`${baseUrl}/api/v1/events/stream`, {
                withCredentials: true,
            });
        } catch {
            setConnectionState('disconnected');
            toast.error('تعذر بدء الاتصال اللحظي بالخادم.', { id: 'sse-error-fatal' });
            return;
        }
        
        eventSourceRef.current = evtSource;

        evtSource.onopen = () => {
            if (eventSourceRef.current !== evtSource) return;
            reconnectAttempts.current = 0;
            setConnectionState('connected');
            setConnectedAt(new Date().toISOString());
            toast.dismiss('sse-error-fatal');
        };

        evtSource.onerror = () => {
            if (eventSourceRef.current !== evtSource) return;
            evtSource.close();
            eventSourceRef.current = null;

            if (reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
                setConnectionState('reconnecting');
                const backoffTime = Math.min(1000 * (2 ** reconnectAttempts.current), 30000);
                reconnectTimeoutRef.current = setTimeout(() => {
                    reconnectTimeoutRef.current = null;
                    reconnectAttempts.current += 1;
                    connectSSE();
                }, backoffTime);
            } else {
                setConnectionState('disconnected');
                toast.error('انقطع الاتصال اللحظي بالخادم. يرجى تحديث الصفحة.', { id: 'sse-error-fatal' });
            }
        };

        const handleEvent = (type) => (event) => {
            if (eventSourceRef.current !== evtSource) return;
            try {
                const eventData = JSON.parse(event.data);
                const receivedAt = Date.now();
                setLastEvent({ ...eventData, type, _ts: receivedAt });
                setLastEventAt(new Date(receivedAt).toISOString());
            } catch(e) {
                console.error(`Global Event parse error for ${type}`, e);
            }
        };

        evtSource.onmessage = handleEvent('message');
        evtSource.addEventListener('message.received', handleEvent('message.received'));
        evtSource.addEventListener('message.sent', handleEvent('message.sent'));
        evtSource.addEventListener('message.updated', handleEvent('message.updated'));
        evtSource.addEventListener('lead.updated', handleEvent('lead.updated'));
        evtSource.addEventListener('lead.created', handleEvent('lead.created'));
        evtSource.addEventListener('intelligence.updated', handleEvent('intelligence.updated'));
        evtSource.addEventListener('workspace.suggested_reply', handleEvent('workspace.suggested_reply'));
    }, []);

    useEffect(() => {
        if (loading || !isAuthenticated) {
            if (eventSourceRef.current) {
                const source = eventSourceRef.current;
                eventSourceRef.current = null;
                source.close();
            }
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
                reconnectTimeoutRef.current = null;
            }
            reconnectAttempts.current = 0;
            setConnectionState('idle');
            setConnectedAt(null);
            setLastEventAt(null);
            setLastEvent(null);
            return;
        }

        setConnectionState('connecting');
        const timeout = setTimeout(() => {
            connectSSE();
        }, 500);

        return () => {
            clearTimeout(timeout);
            if (eventSourceRef.current) {
                const source = eventSourceRef.current;
                eventSourceRef.current = null;
                source.close();
            }
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
                reconnectTimeoutRef.current = null;
            }
        };
    }, [connectSSE, isAuthenticated, loading]);

    return (
        <GlobalEventContext.Provider value={{ lastEvent, connectionState, connectedAt, lastEventAt }}>
            {children}
        </GlobalEventContext.Provider>
    );
};
