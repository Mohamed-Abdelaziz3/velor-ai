import { useCallback, useState, useEffect, useMemo, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { FiSend, FiAlertCircle, FiRefreshCw, FiMessageCircle, FiWifiOff } from 'react-icons/fi';
import { publicClient } from '../services/api';
import { VelorLogo, VelorMark } from '../components/velor/VelorLogo';
import {
    getConversationMode,
    getProductActions,
    getTextDirection,
    mergeConversationMessages,
    normalizePresentation,
} from './publicChatUi';

const REQUEST_TIMEOUT_MS = 45000;

const formatMessageTime = (value) => {
    if (!value) return '';
    const explicitZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
    const date = new Date(explicitZone ? value : `${value}Z`);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat('ar-EG', {
        hour: 'numeric',
        minute: '2-digit',
        timeZone: 'Africa/Cairo',
    }).format(date);
};

const PublicChat = () => {
    const { slug } = useParams();
    const tokenKey = `velor_webchat_token_${slug}`;
    const freshSessionRequested = new URLSearchParams(window.location.search).get('fresh') === '1';

    // States
    const [messages, setMessages] = useState([]);
    const [inputText, setInputText] = useState('');
    const [companyName, setCompanyName] = useState('مساعد المبيعات');
    const [welcomeMessage, setWelcomeMessage] = useState('');
    const [suggestedQuestions, setSuggestedQuestions] = useState([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState(null);
    const [isBotTyping, setIsBotTyping] = useState(false);
    const [isSending, setIsSending] = useState(false);
    const [isSlowReply, setIsSlowReply] = useState(false);
    const [isChatDisabled, setIsChatDisabled] = useState(false);
    const [isHandoffActive, setIsHandoffActive] = useState(false);
    const [sendError, setSendError] = useState('');
    const [isOnline, setIsOnline] = useState(() => typeof navigator === 'undefined' || navigator.onLine);
    const [isChatReady, setIsChatReady] = useState(false);

    const messagesEndRef = useRef(null);
    const slowReplyTimerRef = useRef(null);
    const hasResetFreshSession = useRef(false);
    const sessionLoadInFlightRef = useRef(null);

    const handleSessionError = useCallback((err) => {
        if (err.response && (err.response.status === 400 || err.response.status === 404)) {
            setIsChatDisabled(true);
        } else if (err.response?.status === 429) {
            setError('تم إنشاء جلسات كثيرة في وقت قصير. انتظر دقيقة ثم أعد المحاولة.');
        } else {
            setError('خطأ في الاتصال بالخادم. يرجى التحقق من الشبكة.');
        }
        setIsChatReady(false);
    }, []);

    const startNewSession = useCallback(async () => {
        const res = await publicClient.post(`/api/public/companies/${slug}/session`);
        localStorage.setItem(tokenKey, res.data.token);
        setCompanyName(res.data.company_name);
        setWelcomeMessage(res.data.welcome_message);
        setSuggestedQuestions(res.data.suggested_questions || []);
        setMessages([]);
    }, [slug, tokenKey]);

    // Load session info & messages
    const fetchSession = useCallback((showLoading = false) => {
        if (sessionLoadInFlightRef.current) {
            if (showLoading) setIsLoading(true);
            return sessionLoadInFlightRef.current;
        }

        if (showLoading) setIsLoading(true);
        const request = (async () => {
            if (freshSessionRequested && !hasResetFreshSession.current) {
                localStorage.removeItem(tokenKey);
                hasResetFreshSession.current = true;

                // A clean session is one action, not a URL that creates a new
                // visitor every time the page is refreshed.
                const params = new URLSearchParams(window.location.search);
                params.delete('fresh');
                const query = params.toString();
                window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`);
            }
            const token = localStorage.getItem(tokenKey);

            try {
                if (token) {
                    const res = await publicClient.get(`/api/public/companies/${slug}/session`, {
                        headers: { Authorization: `Bearer ${token}` }
                    });
                    setCompanyName(res.data.company_name);
                    setWelcomeMessage(res.data.welcome_message);
                    setSuggestedQuestions(res.data.suggested_questions || []);
                    setIsHandoffActive(Boolean(res.data.is_paused));
                    setMessages(prev => mergeConversationMessages(prev, res.data.conversations || []));
                    setIsChatDisabled(false);
                } else {
                    await startNewSession();
                }
                setIsChatReady(true);
                setError(null);
            } catch (err) {
                const status = err.response?.status;
                if (token && (status === 401 || status === 403 || status === 404)) {
                    localStorage.removeItem(tokenKey);
                    try {
                        await startNewSession();
                        setIsChatDisabled(false);
                        setIsChatReady(true);
                        setError(null);
                    } catch (retryErr) {
                        handleSessionError(retryErr);
                    }
                } else {
                    handleSessionError(err);
                }
            } finally {
                setIsLoading(false);
            }
        })();

        sessionLoadInFlightRef.current = request;
        request.finally(() => {
            if (sessionLoadInFlightRef.current === request) {
                sessionLoadInFlightRef.current = null;
            }
        });
        return request;
    }, [freshSessionRequested, handleSessionError, slug, startNewSession, tokenKey]);

    // Initial session load
    useEffect(() => {
        fetchSession(true);
    }, [fetchSession]);

    useEffect(() => {
        const previousTitle = document.title;
        document.title = `${companyName} — محادثة عبر VELOR`;
        return () => { document.title = previousTitle; };
    }, [companyName]);

    useEffect(() => {
        const handleOnline = () => {
            setIsOnline(true);
            setSendError('');
            fetchSession(false);
        };
        const handleOffline = () => {
            setIsOnline(false);
            setSendError('لا يوجد اتصال بالإنترنت. ستتمكن من المتابعة عند عودة الاتصال.');
        };
        window.addEventListener('online', handleOnline);
        window.addEventListener('offline', handleOffline);
        return () => {
            window.removeEventListener('online', handleOnline);
            window.removeEventListener('offline', handleOffline);
        };
    }, [fetchSession]);

    // Short-polling sync loop. Poll faster while the customer is waiting for a reply.
    useEffect(() => {
        const delay = (isBotTyping || isSending) ? 2000 : 5000;
        const interval = setInterval(() => {
            if (isOnline) fetchSession(false);
        }, delay);

        return () => clearInterval(interval);
    }, [fetchSession, isBotTyping, isSending, isOnline]);

    // Auto scroll to bottom
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, isBotTyping]);

    // Message Send logic
    const sendMessage = async (text, customClientMsgId = null) => {
        if (!text.trim() || isSending || !isOnline || !isChatReady) return;

        const clientMsgId = customClientMsgId || Math.random().toString(36).substring(2, 15);
        const token = localStorage.getItem(tokenKey);

        // Check message length
        if (text.length > 1000) {
            alert('الرسالة طويلة جداً. الحد الأقصى 1000 حرف.');
            return;
        }

        // Add message locally in "sending" state
        const localNewMsg = {
            client_message_id: clientMsgId,
            message: text,
            sender: 'user',
            direction: 'incoming',
            status: 'sending',
            created_at: new Date().toISOString()
        };

        if (customClientMsgId) {
            // Update existing message state back to sending
            setMessages(prev => prev.map(m => m.client_message_id === clientMsgId ? { ...m, status: 'sending' } : m));
        } else {
            setMessages(prev => [...prev, localNewMsg]);
            setInputText('');
        }

        setIsSending(true);
        setIsBotTyping(true);
        setIsSlowReply(false);
        setSendError('');
        clearTimeout(slowReplyTimerRef.current);
        slowReplyTimerRef.current = setTimeout(() => setIsSlowReply(true), 10000);

        try {
            const res = await publicClient.post('/api/public/chat', {
                message: text,
                client_message_id: clientMsgId
            }, {
                headers: { Authorization: `Bearer ${token}` },
                timeout: REQUEST_TIMEOUT_MS
            });

            // Mark sent
            setMessages(prev => prev.map(m => m.client_message_id === clientMsgId ? { ...m, status: 'sent' } : m));

            // If server returned an assistant reply immediately, add it
            if (res.data && res.data.status === 'completed' && res.data.reply) {
                setMessages(prev => [
                    ...prev,
                    {
                        id: res.data.id || res.data.internal_message_id,
                        message: res.data.reply,
                        sender: 'assistant',
                        direction: 'outgoing',
                        status: 'sent',
                        created_at: new Date().toISOString(),
                        presentation: normalizePresentation(res.data.response?.presentation),
                        responseMeta: res.data.response?.meta || null,
                    }
                ]);
            }
        } catch (err) {
            console.error('Send error:', err);
            // Mark failed
            setMessages(prev => prev.map(m => m.client_message_id === clientMsgId ? { ...m, status: 'failed' } : m));
            const status = err.response?.status;
            if (status === 429) {
                setSendError('تم إرسال رسائل كثيرة بسرعة. انتظر لحظة قصيرة ثم أعد المحاولة.');
            } else if (status === 504 || err.code === 'ECONNABORTED') {
                setSendError('الرد اتأخر أو الاتصال انقطع. أعد المحاولة من نفس الرسالة بدون تكرارها.');
            } else {
                setSendError('تعذر إرسال الرسالة. تحقق من الاتصال ثم أعد المحاولة.');
            }
        } finally {
            clearTimeout(slowReplyTimerRef.current);
            setIsSlowReply(false);
            setIsSending(false);
            setIsBotTyping(false);
            fetchSession(false);
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent?.isComposing) {
            e.preventDefault();
            sendMessage(inputText);
        }
    };

    const visibleError = sendError || error;
    const isSendUnavailable = isSending || !isOnline || !isChatReady;
    const conversationMode = useMemo(
        () => getConversationMode({ online: isOnline, messages, isHandoffActive }),
        [isOnline, messages, isHandoffActive]
    );

    if (isLoading) {
        return (
            <div className="min-h-screen bg-velor-deep velor-grid-bg flex flex-col items-center justify-center font-sans" role="status" aria-live="polite" dir="rtl">
                <span className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl border border-velor-purple/20 bg-velor-purple/10"><VelorMark size={28} decorative /></span>
                <div className="mb-4 h-8 w-8 animate-spin rounded-full border-2 border-velor-border border-t-velor-purple" />
                <p className="text-velor-secondary text-sm font-semibold">جاري فتح المحادثة الآمنة...</p>
            </div>
        );
    }

    if (isChatDisabled) {
        return (
            <div className="min-h-screen bg-velor-deep velor-grid-bg flex flex-col items-center justify-center font-sans p-6 text-center" dir="rtl">
                <div className="w-20 h-20 rounded-2xl border border-velor-border bg-velor-panel flex items-center justify-center mb-6">
                    <FiMessageCircle className="w-9 h-9 text-velor-purple" />
                </div>
                <h2 className="text-2xl font-bold text-white mb-2">المحادثة غير متوفرة</h2>
                <p className="text-velor-secondary text-sm max-w-sm leading-relaxed font-medium">
                    عذراً، هذه المحادثة غير مفعلة حالياً أو الرابط غير صحيح. يرجى مراجعة صاحب العمل.
                </p>
                <Link to="/" className="mt-7 text-xs font-semibold text-velor-purple hover:text-velor-violet">اعرف المزيد عن VELOR</Link>
            </div>
        );
    }

    return (
        <div className="min-h-[100dvh] bg-velor-deep velor-grid-bg flex items-stretch justify-center font-sans overflow-hidden p-0 md:p-6" dir="rtl">
            <div className="flex min-h-[100dvh] w-full max-w-5xl flex-col overflow-hidden border-x border-velor-border bg-velor-canvas shadow-velor-card md:min-h-0 md:h-[min(820px,calc(100dvh-3rem))] md:rounded-[1.4rem] md:border">
                {/* Header */}
                <header className="bg-velor-panel/90 backdrop-blur-md py-4 px-5 sm:px-6 border-b border-velor-border flex items-center justify-between gap-4 relative z-10 shrink-0">
                    <div className="flex min-w-0 items-center gap-3.5">
                    <div className="w-11 h-11 rounded-xl border border-velor-purple/20 bg-velor-purple/10 flex items-center justify-center relative shrink-0">
                        <VelorMark size={23} decorative />
                    </div>
                    <div className="min-w-0">
                        <h1 className="truncate text-sm sm:text-base font-bold text-white mb-0.5" dir={getTextDirection(companyName)}><bdi>{companyName}</bdi></h1>
                        <div
                            className={`text-[11px] font-semibold flex items-center gap-1.5 ${conversationMode.tone === 'warning'
                                    ? 'text-amber-300'
                                    : conversationMode.tone === 'human'
                                        ? 'text-cyan-300'
                                        : conversationMode.tone === 'neutral'
                                            ? 'text-white/60'
                                            : 'text-emerald-400'
                                }`}
                            role="status"
                            aria-live="polite"
                        >
                            <span className={`w-1.5 h-1.5 rounded-full ${conversationMode.tone === 'warning' ? 'bg-amber-300' : conversationMode.tone === 'human' ? 'bg-cyan-300' : conversationMode.tone === 'neutral' ? 'bg-white/50' : 'bg-emerald-400'}`}></span>
                            {conversationMode.label}
                        </div>
                    </div>
                    </div>
                    <Link to="/" className="hidden shrink-0 opacity-70 transition hover:opacity-100 sm:block" aria-label="VELOR"><VelorLogo size={25} wordmarkClassName="text-xs" /></Link>
                </header>

                {/* Chat Area */}
                <div className="flex-1 overflow-y-auto p-4 sm:p-5 md:p-7 space-y-4 custom-scrollbar bg-velor-canvas/70 relative">
                    {visibleError && (
                        <div role="alert" className={`mx-auto flex max-w-2xl flex-col items-center justify-between gap-2 rounded-xl border px-4 py-3 text-center text-sm font-bold leading-6 sm:flex-row sm:text-right ${isOnline ? 'border-red-500/25 bg-red-500/10 text-red-100' : 'border-amber-400/25 bg-amber-500/10 text-amber-100'}`}>
                            <span>{visibleError}</span>
                            {error && isOnline && (
                                <button type="button" onClick={() => fetchSession(true)} className="min-h-11 shrink-0 rounded-lg border border-red-200/20 px-3 py-2 text-xs text-white hover:bg-white/10">
                                    إعادة المحاولة
                                </button>
                            )}
                        </div>
                    )}

                    {/* Welcome Message */}
                    <div dir={getTextDirection(welcomeMessage)} className="self-start bg-velor-panel border border-velor-border text-white font-medium text-sm px-4 py-3.5 rounded-2xl rounded-tl-sm max-w-[min(88%,680px)] shadow-md leading-relaxed relative mb-6">
                        <bdi className="text-bidi">{welcomeMessage || 'مرحباً بك! كيف يمكنني مساعدتك اليوم؟'}</bdi>
                    </div>

                    {/* Message Bubble Streams */}
                    <AnimatePresence initial={false}>
                        {messages.map((msg, index) => {
                            const isOwnerMsg = msg.sender === 'owner';
                            const isUserMsg = msg.sender === 'user';

                            return (
                                <motion.div
                                    key={msg.id || msg.client_message_id || index}
                                    initial={{ opacity: 0, y: 10 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    className={`flex flex-col ${isUserMsg ? 'items-end' : 'items-start'} gap-1.5`}
                                >
                                    <div className="flex items-center gap-2 max-w-[min(84%,680px)] relative group">
                                        {/* Bubble Body */}
                                        <div
                                            dir={getTextDirection(msg.message)}
                                            className={`px-4 py-3 rounded-2xl text-sm font-semibold leading-relaxed shadow-md ${isUserMsg
                                                    ? 'bg-gradient-to-br from-velor-purple to-[#7138d8] text-white rounded-tr-sm'
                                                    : isOwnerMsg
                                                        ? 'bg-velor-amber text-[#17110a] rounded-tl-sm'
                                                        : 'bg-velor-panel border border-velor-border text-white rounded-tl-sm'
                                                }`}
                                        >
                                            <bdi className="text-bidi whitespace-pre-wrap break-words">{msg.message}</bdi>
                                        </div>

                                        {/* Action Buttons for failed messages */}
                                        {msg.status === 'failed' && (
                                            <button
                                                onClick={() => sendMessage(msg.message, msg.client_message_id)}
                                                className="text-red-500 hover:text-red-400 p-1.5 bg-red-500/10 rounded-full transition-colors self-center flex items-center justify-center shrink-0 border border-red-500/20"
                                                title="أعد الإرسال"
                                                aria-label="أعد إرسال الرسالة"
                                            >
                                                <FiRefreshCw className="w-3.5 h-3.5" />
                                            </button>
                                        )}
                                    </div>

                                    {!isUserMsg && msg.presentation?.product_cards?.length > 0 && (
                                        <div className="mr-0 mt-1 grid w-full max-w-[min(100%,680px)] gap-2 sm:grid-cols-2 lg:grid-cols-3">
                                            {msg.presentation.product_cards.map((product, productIndex) => {
                                                const actions = getProductActions(product);
                                                return (
                                                    <article key={product.id || `${product.display_name}-${productIndex}`} dir={getTextDirection(product.display_name)} className="flex min-w-0 flex-col rounded-xl border border-velor-purple/25 bg-velor-panel p-3 text-right">
                                                        <p className="text-sm font-bold text-white" dir={getTextDirection(product.display_name)}><bdi className="text-bidi">{product.display_name}</bdi></p>
                                                        {product.price && <p className="mt-1 text-xs font-bold text-velor-violet" dir="ltr"><bdi>{product.price}</bdi></p>}
                                                        <div className="mt-1 flex-1">
                                                            {product.attributes?.map((attribute, attributeIndex) => (
                                                                <p key={attributeIndex} dir={getTextDirection(attribute)} className="mt-1 line-clamp-2 text-xs leading-5 text-white/70"><bdi className="text-bidi">{attribute}</bdi></p>
                                                            ))}
                                                        </div>
                                                        <div className="mt-3 flex flex-wrap gap-2">
                                                            {actions.primary && (
                                                                <button type="button" onClick={() => sendMessage(actions.primary.message)} disabled={isSendUnavailable} className="min-h-11 flex-1 rounded-lg bg-velor-purple px-3 py-2 text-xs font-bold text-white hover:bg-velor-violet disabled:opacity-50">
                                                                    {actions.primary.label}
                                                                </button>
                                                            )}
                                                            {actions.secondary && (
                                                                <button type="button" onClick={() => sendMessage(actions.secondary.message)} disabled={isSendUnavailable} className="min-h-11 flex-1 rounded-lg border border-white/15 bg-white/[0.04] px-3 py-2 text-xs font-bold text-white hover:bg-white/[0.08] disabled:opacity-50">
                                                                    {actions.secondary.label}
                                                                </button>
                                                            )}
                                                        </div>
                                                    </article>
                                                );
                                            })}
                                        </div>
                                    )}

                                    {!isUserMsg && msg.presentation?.quick_replies?.length > 0 && (
                                        <div className="mt-1 flex max-w-[min(100%,680px)] flex-wrap gap-2">
                                            {msg.presentation.quick_replies.map((quickReply, quickIndex) => (
                                                <button
                                                    key={`${quickReply.label}-${quickIndex}`}
                                                    type="button"
                                                    onClick={() => sendMessage(quickReply.message)}
                                                    disabled={isSendUnavailable}
                                                    dir={getTextDirection(quickReply.label)}
                                                    className="min-h-11 rounded-full border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-bold text-white transition-colors hover:border-velor-purple/50 hover:bg-velor-purple/10 disabled:opacity-60"
                                                >
                                                    {quickReply.label}
                                                </button>
                                            ))}
                                        </div>
                                    )}

                                    {!isUserMsg && msg.presentation?.primary_action?.label && msg.presentation?.primary_action?.message && (
                                        <div className="mt-1 max-w-[min(100%,680px)]">
                                            <button
                                                type="button"
                                                onClick={() => sendMessage(msg.presentation.primary_action.message)}
                                                disabled={isSendUnavailable}
                                                dir={getTextDirection(msg.presentation.primary_action.label)}
                                                className="min-h-11 rounded-xl bg-cyan-500/15 px-4 py-2 text-xs font-bold text-cyan-100 ring-1 ring-cyan-300/30 hover:bg-cyan-500/25 disabled:opacity-60"
                                            >
                                                {msg.presentation.primary_action.label}
                                            </button>
                                        </div>
                                    )}

                                    {!isUserMsg && msg.presentation?.conversation_action?.status === 'executed' && (
                                        <div className="mt-1 rounded-lg border border-cyan-300/20 bg-cyan-500/10 px-3 py-2 text-xs font-bold text-cyan-100" role="status">
                                            تم تسجيل طلبك للفريق.
                                        </div>
                                    )}

                                    {/* Status details underneath */}
                                    <div className="text-[9px] text-velor-muted px-2 flex items-center gap-1.5 font-sans font-semibold">
                                        {msg.status === 'sending' && <span className="text-velor-muted animate-pulse">جاري الإرسال...</span>}
                                        {msg.status === 'failed' && (
                                            <span className="text-red-400 flex items-center gap-1">
                                                <FiAlertCircle className="inline" /> فشل الإرسال
                                            </span>
                                        )}
                                        {msg.status !== 'sending' && msg.status !== 'failed' && formatMessageTime(msg.created_at) && (
                                            <time dateTime={msg.created_at}>{formatMessageTime(msg.created_at)}</time>
                                        )}
                                    </div>
                                </motion.div>
                            );
                        })}

                        {/* Bot is preparing reply animation */}
                        {isBotTyping && (
                            <motion.div
                                initial={{ opacity: 0 }}
                                animate={{ opacity: 1 }}
                                exit={{ opacity: 0 }}
                                aria-label={isSlowReply ? 'الرد بياخد وقت أطول شوية' : 'يجهز الرد'}
                                role="status"
                                aria-live="polite"
                                className="self-start bg-velor-panel border border-velor-border px-4 py-3.5 rounded-2xl rounded-tl-sm flex items-center gap-1.5 shadow-md w-fit max-w-[min(84%,680px)]"
                            >
                                <span className="w-1.5 h-1.5 rounded-full bg-velor-purple animate-bounce"></span>
                                <span className="w-1.5 h-1.5 rounded-full bg-velor-purple animate-bounce" style={{ animationDelay: '0.15s' }}></span>
                                <span className="w-1.5 h-1.5 rounded-full bg-velor-purple animate-bounce" style={{ animationDelay: '0.3s' }}></span>
                                <span className="text-[11px] text-velor-muted font-bold mr-1.5">
                                    {isSlowReply ? 'الرد بياخد وقت أطول... هنظهره هنا أول ما يجهز.' : 'يجهز الرد...'}
                                </span>
                            </motion.div>
                        )}
                    </AnimatePresence>
                    <div ref={messagesEndRef} />
                </div>

                {/* Quick replies for new sessions */}
                {messages.length === 0 && suggestedQuestions.length > 0 && (
                    <div className="p-4 shrink-0 bg-velor-canvas/70 border-t border-velor-border space-y-2 max-h-40 overflow-y-auto">
                        <p className="text-[10px] text-velor-muted font-bold block mb-1">ابدأ بسؤال:</p>
                        <div className="flex flex-wrap gap-2">
                            {suggestedQuestions.map((q, idx) => (
                                <button
                                    key={idx}
                                    onClick={() => sendMessage(q)}
                                    disabled={isSendUnavailable}
                                    className="min-h-11 text-xs bg-white/5 border border-velor-border hover:bg-velor-purple/10 hover:border-velor-purple/30 text-white font-medium px-3.5 py-2 rounded-xl transition-all disabled:opacity-50"
                                >
                                    {q}
                                </button>
                            ))}
                        </div>
                    </div>
                )}

                {/* Footer Form Input */}
                <div className="bg-velor-panel p-3 sm:p-4 border-t border-velor-border shrink-0">
                    <div className="flex items-center gap-3">
                    {!isOnline && <FiWifiOff className="shrink-0 text-amber-300" aria-hidden="true" />}
                    <div className="flex-1 relative flex items-center bg-velor-elevated border border-velor-border rounded-xl focus-within:border-velor-purple/60 transition-colors">
                        <input
                            type="text"
                            value={inputText}
                            onChange={(e) => setInputText(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder={isOnline ? 'اكتب رسالتك هنا...' : 'بانتظار عودة الاتصال...'}
                            disabled={isSendUnavailable}
                            maxLength={1000}
                            dir="auto"
                            aria-label="رسالتك"
                            autoComplete="off"
                            className="w-full bg-transparent border-none text-white text-xs font-semibold px-4 py-3.5 focus:outline-none placeholder:text-velor-muted disabled:opacity-50"
                        />
                    </div>
                    <button
                        onClick={() => sendMessage(inputText)}
                        disabled={!inputText.trim() || isSendUnavailable}
                        aria-label="إرسال الرسالة"
                        className="w-11 h-11 bg-gradient-to-tr from-velor-purple to-velor-blue hover:scale-105 active:scale-95 disabled:opacity-50 disabled:scale-100 rounded-xl flex items-center justify-center shadow-lg shadow-velor-purple/10 transition-all cursor-pointer shrink-0 border border-white/10"
                    >
                        <FiSend className="text-white text-sm -rotate-45 ml-0.5" />
                    </button>
                    </div>
                    <p className="mt-2.5 text-center text-[9px] leading-4 text-velor-muted">
                        بإرسال رسالتك أنت توافق على استخدامها للرد ومتابعة طلبك لدى {companyName}. <Link to="/privacy" className="text-velor-secondary underline-offset-2 hover:text-white hover:underline">الخصوصية</Link>
                    </p>
                </div>
            </div>
        </div>
    );
};

export default PublicChat;
