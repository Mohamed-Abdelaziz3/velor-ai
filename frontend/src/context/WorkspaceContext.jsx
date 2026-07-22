import { createContext, useContext, useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import api, {
    completeFollowUp,
    createClientEventId,
    dismissFollowUp,
    getFollowUps,
    recordProductEvents,
    snoozeFollowUp,
} from '../services/api';
import { toast } from 'react-hot-toast';
import { useGlobalEvents } from '../contexts/GlobalEventContext';
import { buildManualOutboundMessage, deriveControlState } from '../components/workspace/workspaceUx';
import {
    replacementSuggestionGroup,
    shouldInvalidateSuggestionsForEvent,
    suggestionRegenerationError,
    suggestionRegenerationFeedback,
    suggestionTargetsLatestCustomerTurn,
} from '../components/workspace/workspacePresentation';

const WorkspaceContext = createContext();
const IDLE_SUGGESTION_REGENERATION = { status: 'idle', responsePath: null, message: '' };

// eslint-disable-next-line react-refresh/only-export-components
export const useWorkspace = () => {
    const context = useContext(WorkspaceContext);
    if (!context) {
        throw new Error('useWorkspace must be used within a WorkspaceProvider');
    }
    return context;
};

// Safe version that returns null when used outside WorkspaceProvider (e.g. Dashboard)
// eslint-disable-next-line react-refresh/only-export-components
export const useWorkspaceSafe = () => {
    return useContext(WorkspaceContext);
};

export const WorkspaceProvider = ({ children, leadId }) => {
    const location = useLocation();
    const [currentLead, setCurrentLead] = useState(null);
    const [messages, setMessages] = useState([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState(null);
    const [isSending, setIsSending] = useState(false);
    const [suggestedReplies, setSuggestedReplies] = useState([]);
    const [suggestionRegeneration, setSuggestionRegeneration] = useState(IDLE_SUGGESTION_REGENERATION);
    const [followUps, setFollowUps] = useState([]);
    const [followUpLifecycle, setFollowUpLifecycle] = useState({});
    const [companyAutoReplyEnabled, setCompanyAutoReplyEnabled] = useState(null);
    const [whatsAppStatus, setWhatsAppStatus] = useState({ available: false, status: 'unknown' });
    const [composerInsertion, setComposerInsertion] = useState({ text: '', token: 0 });
    const [messageNavigation, setMessageNavigation] = useState({ messageId: null, token: 0 });
    const [retryVersion, setRetryVersion] = useState(0);
    const { lastEvent } = useGlobalEvents();

    // Robust Dossier Structure
    // eslint-disable-next-line react-hooks/exhaustive-deps
    const permanentContext = currentLead?.permanent_context || {
        identity: {},
        decision: {},
        memory: {}
    };

    const controlState = useMemo(
        () => deriveControlState({ currentLead, companyAutoReplyEnabled, whatsAppStatus }),
        [currentLead, companyAutoReplyEnabled, whatsAppStatus]
    );
    const isCopilotActive = Boolean(controlState?.velorActive);

    // Decouple dependencies for pure functional updates
    const leadContactRef = useRef(null);
    const workspaceRequestRef = useRef(0);
    const suggestionRequestRef = useRef(0);
    const messagesRef = useRef([]);
    const ownerActionRecordedRef = useRef(new Set());
    const invalidateSuggestionPresentation = useCallback(() => {
        suggestionRequestRef.current += 1;
        setSuggestedReplies([]);
        setSuggestionRegeneration(IDLE_SUGGESTION_REGENERATION);
    }, []);

    useEffect(() => {
        messagesRef.current = messages;
    }, [messages]);

    useEffect(() => {
        leadContactRef.current = currentLead?.contact_identifier
            || currentLead?.external_customer_id
            || currentLead?.phone
            || currentLead?.whatsapp_number
            || currentLead?.whatsapp_jid;
    }, [
        currentLead?.contact_identifier,
        currentLead?.external_customer_id,
        currentLead?.phone,
        currentLead?.whatsapp_number,
        currentLead?.whatsapp_jid,
    ]);

    const fetchWorkspaceData = useCallback(async (abortController) => {
        const requestId = ++workspaceRequestRef.current;
        setIsLoading(true);
        setError(null);
        try {
            const res = await api.get(`/api/v1/crm/customers/${leadId}`, {
                signal: abortController.signal
            });
            if (requestId !== workspaceRequestRef.current) return;
            if (res.data?.success) {
                const crmData = res.data.customer;
                setCurrentLead(crmData);
                setSuggestedReplies(crmData.suggested_replies || []);
                setFollowUps(crmData.follow_ups || []);
                if (crmData.timeline) {
                    messagesRef.current = crmData.timeline;
                    setMessages(crmData.timeline);
                }

                const [autoReplyResult, whatsappResult] = await Promise.allSettled([
                    api.get('/api/company/bot/auto-reply', { signal: abortController.signal }),
                    api.get('/whatsapp/status', { signal: abortController.signal }),
                ]);

                if (autoReplyResult.status === 'fulfilled') {
                    setCompanyAutoReplyEnabled(autoReplyResult.value.data?.bot_auto_reply_enabled ?? null);
                } else {
                    setCompanyAutoReplyEnabled(null);
                }

                if (whatsappResult.status === 'fulfilled') {
                    setWhatsAppStatus({
                        available: true,
                        ...(whatsappResult.value.data || {}),
                    });
                } else {
                    setWhatsAppStatus({ available: false, status: 'unknown' });
                }
            } else {
                setError('تعذر تحميل بيانات مساحة العميل.');
            }
        } catch (err) {
            if (requestId !== workspaceRequestRef.current) return;
            if (err.name === 'CanceledError' || err.code === 'ERR_CANCELED') return;
            console.error("Workspace init error:", err);
            setError('تعذر الاتصال بخدمة مساحة العميل.');
        } finally {
            if (requestId === workspaceRequestRef.current) setIsLoading(false);
        }
    }, [leadId]);

    const retryWorkspace = useCallback(() => {
        setRetryVersion((version) => version + 1);
    }, []);

    useEffect(() => {
        if (!lastEvent) return;
        
        try {
            const eventData = lastEvent;
            const currentPhone = leadContactRef.current;

            const leadMatches = eventData.lead_id !== null
                && eventData.lead_id !== undefined
                && String(eventData.lead_id) === String(leadId);
            const phoneMatches = Boolean(currentPhone && (
                eventData.user_id === currentPhone ||
                eventData.user_id?.includes(currentPhone) ||
                eventData.phone === currentPhone ||
                eventData.phone?.includes(currentPhone)
            ));
            const isForCurrentLead = leadMatches || phoneMatches;

            if (!isForCurrentLead) return;

            if (eventData.type === 'lead.updated' || eventData.status || eventData.stage) {
                setCurrentLead(prev => prev ? ({
                    ...prev,
                    status: eventData.status || prev.status,
                    is_paused: eventData.is_paused ?? prev.is_paused
                }) : prev);
            }

            if (eventData.type === 'workspace.suggested_reply') {
                const replacement = replacementSuggestionGroup(eventData);
                if (replacement.length && suggestionTargetsLatestCustomerTurn(eventData, messagesRef.current)) {
                    setSuggestedReplies(replacement);
                    setSuggestionRegeneration(eventData.response_path
                        ? suggestionRegenerationFeedback(eventData.response_path)
                        : IDLE_SUGGESTION_REGENERATION
                    );
                }
            } else if (eventData.type === 'message.updated') {
                setMessages(prev => {
                    const next = prev.map(m =>
                        m.internal_message_id === eventData.message_id
                        ? { ...m, delivery_status: eventData.delivery_status } 
                        : m
                    );
                    messagesRef.current = next;
                    return next;
                });
            } else if (eventData.type === 'message.received' || eventData.type === 'message.sent' || eventData.text) {
                if (shouldInvalidateSuggestionsForEvent(eventData)) {
                    invalidateSuggestionPresentation();
                }
                setMessages(prev => {
                    if (prev.some(m => m.internal_message_id === eventData.message_id)) {
                        messagesRef.current = prev;
                        return prev;
                    }
                    const next = [...prev, {
                        internal_message_id: eventData.message_id,
                        type: 'message',
                        sender: eventData.sender,
                        direction: eventData.direction || (eventData.sender === 'user' ? 'incoming' : 'outgoing'),
                        source: eventData.source || 'whatsapp',
                        is_ai: eventData.is_ai ?? eventData.sender === 'assistant',
                        message: eventData.text,
                        delivery_status: eventData.delivery_status,
                        status: eventData.delivery_status,
                        timestamp: eventData.timestamp || eventData._ts || new Date().toISOString()
                    }];
                    messagesRef.current = next;
                    return next;
                });
            } else if (eventData.type === 'canonical_commercial.updated') {
                const abortController = new AbortController();
                fetchWorkspaceData(abortController);
            } else if (eventData.type === 'intelligence.updated' || eventData.type === 'legacy_intelligence.updated') {
                // Ignore advisory intelligence
            }
        } catch(e) {
            console.error("Event processing error in Workspace", e);
        }
    }, [lastEvent, fetchWorkspaceData, invalidateSuggestionPresentation, leadId]);
    useEffect(() => {
        if (!leadId) {
            workspaceRequestRef.current += 1;
            setCurrentLead(null);
            setMessages([]);
            setIsLoading(false);
            setError('لم يتم تحديد العميل المطلوب لهذه المساحة.');
            return;
        }
        
        // Prevent bleed across customers
        setCurrentLead(null);
        setMessages([]);
        setFollowUps([]);
        setFollowUpLifecycle({});
        invalidateSuggestionPresentation();
        setCompanyAutoReplyEnabled(null);
        setWhatsAppStatus({ available: false, status: 'unknown' });
        setComposerInsertion({ text: '', token: 0 });
        setMessageNavigation({ messageId: null, token: 0 });

        const abortController = new AbortController();
        fetchWorkspaceData(abortController);

        return () => {
            abortController.abort();
        };
    }, [leadId, fetchWorkspaceData, invalidateSuggestionPresentation, retryVersion]);

    const getReplyTarget = useCallback((lead) => (
        lead?.contact_identifier
        || lead?.external_customer_id
        || null
    ), []);

    const sendMessage = useCallback(async (messageText, options = {}) => {
        const replyTarget = getReplyTarget(currentLead);
        if (!replyTarget) return false;
        if (!controlState.manualEnabled) {
            toast.error(controlState.message || 'لا يمكن الإرسال اليدوي في هذه الحالة.');
            return false;
        }
        setIsSending(true);
        try {
            const response = await api.post('/api/agent/outbound/send', {
                phone: replyTarget,
                message: messageText,
                ...(options.sourceMessageInternalId
                    ? { source_message_internal_id: options.sourceMessageInternalId }
                    : {}),
                ...(options.suggestionId ? { suggestion_id: options.suggestionId } : {}),
                ...(options.variantStyle ? { variant_style: options.variantStyle } : {}),
                ...(typeof options.suggestionEdited === 'boolean'
                    ? { suggestion_edited: options.suggestionEdited }
                    : {}),
            });
            
            if (response.data.success || response.data.status === "Message Sent") {
                const clientMessageId = globalThis.crypto?.randomUUID?.() || `workspace-manual-${Date.now()}`;
                const sentMessage = buildManualOutboundMessage({
                    responseData: response.data,
                    messageText,
                    clientMessageId,
                });
                setMessages(prev => prev.some(m => m.internal_message_id && m.internal_message_id === sentMessage.internal_message_id)
                    ? prev
                    : [...prev, sentMessage]
                );
                setCurrentLead(prev => prev ? ({ ...prev, is_paused: true }) : prev);
                if (options.sourceMessageInternalId) {
                    setFollowUps((current) => current.filter(
                        (task) => task.source_message_internal_id !== options.sourceMessageInternalId
                    ));
                }
                getFollowUps({ leadId: currentLead.id })
                    .then((result) => setFollowUps(result.data?.follow_ups || []))
                    .catch(() => {});
                invalidateSuggestionPresentation();
                return true;
            } else {
                toast.error('تعذر إرسال الرسالة');
                return false;
            }
        } catch (err) {
            console.error("Send message error:", err);
            toast.error(err.response?.status === 409
                ? 'المسودة قديمة لأن المحادثة تقدمت. تم الاحتفاظ بالنص لمراجعته.'
                : 'تعذر إرسال الرسالة. راجع اتصال القناة وحاول مرة أخرى.');
            return false;
        } finally {
            setIsSending(false);
        }
    }, [currentLead, controlState.manualEnabled, controlState.message, getReplyTarget, invalidateSuggestionPresentation]);

    const updateSuggestedReplyStatus = useCallback(async (suggestionId, status) => {
        if (!currentLead?.id || !suggestionId) return;
        setSuggestedReplies(prev => status === 'suggested'
            ? prev
            : prev.filter(item => item.id !== suggestionId)
        );
        if (status !== 'suggested') setSuggestionRegeneration(IDLE_SUGGESTION_REGENERATION);
        try {
            await api.patch(`/api/v1/crm/customers/${currentLead.id}/suggested-replies/${suggestionId}`, { status });
        } catch (err) {
            console.error("Suggestion status update error:", err);
            toast.error('تعذر تحديث حالة الرد المقترح');
            try {
                const res = await api.get(`/api/v1/crm/customers/${currentLead.id}/suggested-replies`);
                setSuggestedReplies((res.data?.suggested_replies || []).filter(item => item.status === 'suggested').slice(0, 5));
            } catch (refreshErr) {
                console.error("Suggestion refresh error:", refreshErr);
            }
        }
    }, [currentLead?.id]);

    const toggleCopilot = useCallback(async () => {
        if (!currentLead?.id) return false;
        try {
            const requestedPause = !currentLead.is_paused;
            const res = await api.post(`/api/leads/${currentLead.id}/human-takeover/toggle`, { enabled: requestedPause });
            if (res.data?.success) {
                const responsePaused = res.data.is_paused ?? res.data.human_takeover_active;
                if (typeof responsePaused !== 'boolean') {
                    toast.error('تعذر التحقق من حالة المحادثة بعد التحديث');
                    return false;
                }
                const isPaused = responsePaused;
                setCurrentLead(prev => ({ ...prev, is_paused: isPaused }));
                invalidateSuggestionPresentation();
                toast.success(isPaused ? 'تم تولي المحادثة يدويا' : 'تم تفعيل VELOR');
                return true;
            }
            return false;
        // eslint-disable-next-line unused-imports/no-unused-vars
        } catch (err) {
            toast.error('تعذر تغيير حالة VELOR');
            return false;
        }
    }, [currentLead?.id, currentLead?.is_paused, invalidateSuggestionPresentation]);

    const regenerateSuggestedReplies = useCallback(async () => {
        if (!currentLead?.id) {
            setSuggestionRegeneration(suggestionRegenerationError(null));
            return false;
        }

        const requestId = ++suggestionRequestRef.current;
        setSuggestionRegeneration({
            status: 'loading',
            responsePath: null,
            message: 'جاري إنشاء صيغ جديدة مرتبطة بآخر رسالة من العميل...',
        });
        try {
            const response = await api.post(`/api/v1/crm/customers/${currentLead.id}/suggested-replies/regenerate`);
            if (requestId !== suggestionRequestRef.current) return false;
            const suggestion = response.data?.suggested_reply;
            const replacement = response.data?.success ? replacementSuggestionGroup(suggestion) : [];
            const targetsLatestTurn = suggestionTargetsLatestCustomerTurn(suggestion, messagesRef.current);
            if (!replacement.length || !targetsLatestTurn) {
                setSuggestionRegeneration(suggestionRegenerationError(!targetsLatestTurn ? 409 : response.status));
                return false;
            }

            setSuggestedReplies(replacement);
            setSuggestionRegeneration(suggestionRegenerationFeedback(suggestion.response_path));
            return true;
        } catch (err) {
            if (requestId !== suggestionRequestRef.current) return false;
            console.error('Suggestion regeneration error:', err);
            setSuggestionRegeneration(suggestionRegenerationError(err.response?.status));
            return false;
        }
    }, [currentLead?.id]);

    const recordSuggestionInserted = useCallback((suggestion) => {
        if (!currentLead?.id || !suggestion?.suggestionId) return;
        recordProductEvents([{
            event_name: 'suggestion_inserted',
            client_event_id: createClientEventId('suggestion-inserted'),
            metadata: {
                lead_id: currentLead.id,
                suggestion_id: suggestion.suggestionId,
                source_message_internal_id: suggestion.sourceMessageInternalId || suggestion.answersMessageId || null,
                variant_style: suggestion.style,
                surface: 'workspace',
            },
        }]).catch(() => {});
    }, [currentLead?.id]);

    const transitionFollowUp = useCallback(async (taskId, action) => {
        if (!taskId) return false;
        setFollowUpLifecycle((current) => ({ ...current, [taskId]: { status: 'loading', action } }));
        try {
            const response = action === 'complete'
                ? await completeFollowUp(taskId)
                : action === 'dismiss'
                    ? await dismissFollowUp(taskId)
                    : await snoozeFollowUp(taskId, new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString());
            const updated = response.data?.follow_up;
            setFollowUps((current) => action === 'snooze'
                ? current.map((task) => task.task_id === taskId ? updated : task)
                : current.filter((task) => task.task_id !== taskId));
            setFollowUpLifecycle((current) => ({ ...current, [taskId]: { status: 'success', action } }));
            return true;
        } catch (err) {
            const stale = err.response?.status === 409;
            setFollowUpLifecycle((current) => ({
                ...current,
                [taskId]: { status: stale ? 'stale' : 'error', action },
            }));
            toast.error(stale ? 'تغيّرت حالة المتابعة. تم تحديث القائمة.' : 'تعذر تحديث المتابعة.');
            try {
                const refreshed = await getFollowUps({ leadId: currentLead?.id });
                setFollowUps(refreshed.data?.follow_ups || []);
            } catch {
                // Keep the visible failure state; never replace it with guessed data.
            }
            return false;
        }
    }, [currentLead?.id]);

    useEffect(() => {
        const queueItemId = location.state?.recoveryQueueItemId;
        if (!currentLead?.id || !queueItemId || String(currentLead.id) !== String(leadId)) return;
        if (ownerActionRecordedRef.current.has(queueItemId)) return;
        ownerActionRecordedRef.current.add(queueItemId);
        recordProductEvents([{
            event_name: 'owner_action_started',
            client_event_id: createClientEventId('workspace-action'),
            metadata: {
                lead_id: currentLead.id,
                queue_item_id: queueItemId,
                surface: location.state?.recoverySurface || 'workspace',
            },
        }]).catch(() => {});
    }, [currentLead?.id, leadId, location.state]);

    const insertComposerText = useCallback((text) => {
        const value = String(text || '').trim();
        if (!value) return;
        setComposerInsertion((current) => ({ text: value, token: current.token + 1 }));
    }, []);

    const requestComposerFocus = useCallback(() => {
        setComposerInsertion((current) => ({ ...current, token: current.token + 1 }));
    }, []);

    const navigateToMessage = useCallback((messageId) => {
        if (!messageId) return;
        setMessageNavigation((current) => ({ messageId: String(messageId), token: current.token + 1 }));
    }, []);

    // Heavily memoized context value to completely eradicate re-render bleeding
    const contextValue = useMemo(() => ({
        currentLead,
        messages,
        isLoading,
        error,
        isSending,
        suggestedReplies,
        suggestionRegeneration,
        followUps,
        followUpLifecycle,
        permanentContext,
        isCopilotActive,
        companyAutoReplyEnabled,
        whatsAppStatus,
        controlState,
        composerInsertion,
        messageNavigation,
        retryWorkspace,
        sendMessage,
        updateSuggestedReplyStatus,
        recordSuggestionInserted,
        transitionFollowUp,
        regenerateSuggestedReplies,
        toggleCopilot,
        insertComposerText,
        requestComposerFocus,
        navigateToMessage
    }), [currentLead, messages, isLoading, error, isSending, suggestedReplies, suggestionRegeneration, followUps, followUpLifecycle, permanentContext, isCopilotActive, companyAutoReplyEnabled, whatsAppStatus, controlState, composerInsertion, messageNavigation, retryWorkspace, sendMessage, updateSuggestedReplyStatus, recordSuggestionInserted, transitionFollowUp, regenerateSuggestedReplies, toggleCopilot, insertComposerText, requestComposerFocus, navigateToMessage]);

    return (
        <WorkspaceContext.Provider value={contextValue}>
            {children}
        </WorkspaceContext.Provider>
    );
};
