import { useEffect, useMemo, useRef, useState } from 'react';
import {
    FiAlertTriangle,
    FiCheck,
    FiCpu,
    FiLock,
    FiRefreshCw,
    FiSend,
    FiUser,
    FiX,
} from 'react-icons/fi';
import { useWorkspace } from '../../context/WorkspaceContext';
import { formatClockTime } from '../../utils/timeUtils';
import { getMessageOwner, safeText } from './workspaceUx';
import { suggestionTargetsLatestCustomerTurn, suggestionVariants } from './workspacePresentation';

const LABELS = {
    customer: 'العميل',
    velor: 'VELOR',
    human: 'أنت',
};

const statusLabel = (status) => {
    if (status === 'failed') return 'فشل الإرسال';
    if (status === 'delivered') return 'تم التسليم';
    if (status === 'sent') return 'تم الإرسال';
    if (status === 'pending' || status === 'sending') return 'جاري الإرسال';
    return null;
};

const controlTone = (tone) => {
    if (tone === 'danger') return {
        shell: 'border-red-400/25 bg-red-500/10',
        icon: 'bg-red-500/10 text-red-200',
        text: 'text-red-100',
        accent: 'text-red-200',
    };
    if (tone === 'human') return {
        shell: 'border-emerald-400/25 bg-emerald-500/10',
        icon: 'bg-emerald-500/10 text-emerald-200',
        text: 'text-emerald-50',
        accent: 'text-emerald-200',
    };
    return {
        shell: 'border-[#A855F7]/30 bg-[#7C3AED]/10',
        icon: 'bg-[#7C3AED]/25 text-[#E9D5FF]',
        text: 'text-white',
        accent: 'text-[#D8B4FE]',
    };
};

const messageTone = (owner) => {
    if (owner === 'customer') {
        return {
            avatar: 'border-white/10 bg-white/[0.06] text-white/60',
            bubble: 'rounded-tr-sm border border-white/10 bg-white/[0.065] text-white',
        };
    }
    if (owner === 'human') {
        return {
            avatar: 'border-cyan-300/25 bg-cyan-500/10 text-cyan-100',
            bubble: 'rounded-tl-sm border border-cyan-300/20 bg-[#0E3445] text-cyan-50',
        };
    }
    return {
        avatar: 'border-[#A855F7]/30 bg-[#7C3AED]/25 text-[#F3E8FF] shadow-[0_0_18px_rgba(124,58,237,0.22)]',
        bubble: 'rounded-tl-sm border border-[#A855F7]/30 bg-[#31154A] text-[#F8F4FF] shadow-[0_0_18px_rgba(124,58,237,0.12)]',
    };
};

const EmptyConversation = () => (
    <div className="flex h-full min-h-[260px] items-center justify-center px-6 text-center">
        <div className="max-w-sm rounded-[16px] border border-white/10 bg-white/[0.035] px-5 py-4">
            <p className="text-sm font-bold text-white">لا توجد رسائل في هذه المحادثة بعد.</p>
            <p className="mt-1 text-xs leading-6 text-white/50">ستظهر الرسائل الحقيقية هنا عند وصولها من واتساب.</p>
        </div>
    </div>
);

export const WorkspaceChat = ({ onOpenAskVelor }) => {
    const {
        messages,
        isLoading,
        isSending,
        sendMessage,
        toggleCopilot,
        isCopilotActive,
        controlState,
        suggestedReplies,
        suggestionRegeneration,
        followUps,
        updateSuggestedReplyStatus,
        recordSuggestionInserted,
        transitionFollowUp,
        regenerateSuggestedReplies,
        composerInsertion,
        messageNavigation,
    } = useWorkspace();

    const [input, setInput] = useState('');
    const [activeVariant, setActiveVariant] = useState(null);
    const [draftSourceMessageId, setDraftSourceMessageId] = useState(null);
    const [draftFreshnessNotice, setDraftFreshnessNotice] = useState('');
    const chatEndRef = useRef(null);
    const composerRef = useRef(null);
    const messageRefs = useRef(new Map());

    const chatMessages = useMemo(
        () => (messages || [])
            .map((msg) => ({ ...msg, displayText: safeText(msg.message, '') }))
            .filter((msg) => (msg.type === 'message' || !msg.type) && msg.displayText && getMessageOwner(msg) !== 'system'),
        [messages]
    );

    const visibleSuggestions = useMemo(() => suggestionVariants(suggestedReplies || []), [suggestedReplies]);
    const draftIsFresh = !draftSourceMessageId || suggestionTargetsLatestCustomerTurn(
        { source_message_internal_id: draftSourceMessageId },
        chatMessages
    );

    useEffect(() => {
        if (!activeVariant) return;
        if (!visibleSuggestions.some((suggestion) => suggestion.id === activeVariant.id)) {
            setActiveVariant(null);
        }
    }, [activeVariant, visibleSuggestions]);

    useEffect(() => {
        if (!draftSourceMessageId || draftIsFresh) return;
        setInput('');
        setActiveVariant(null);
        setDraftSourceMessageId(null);
        setDraftFreshnessNotice('وصلت رسالة جديدة من العميل، فتم حذف المسودة القديمة حتى لا تُرسل خارج سياقها.');
    }, [draftIsFresh, draftSourceMessageId]);

    useEffect(() => {
        chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }, [chatMessages.length, isCopilotActive, isSending]);

    useEffect(() => {
        if (!composerInsertion?.token) return;
        if (composerInsertion.text) setInput(composerInsertion.text);
        setActiveVariant(null);
        setDraftSourceMessageId(null);
        setDraftFreshnessNotice('');
        requestAnimationFrame(() => composerRef.current?.focus());
    }, [composerInsertion]);

    useEffect(() => {
        if (!messageNavigation?.messageId || !messageNavigation.token) return;
        const target = messageRefs.current.get(String(messageNavigation.messageId));
        if (!target) return;
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        target.focus({ preventScroll: true });
    }, [messageNavigation]);

    const manualEnabled = Boolean(controlState?.manualEnabled);
    const isDisconnected = controlState?.key === 'whatsapp_disconnected';
    const tone = controlTone(controlState?.tone);
    const canSend = manualEnabled && !isSending && draftIsFresh && Boolean(input.trim());
    const isRegenerating = suggestionRegeneration?.status === 'loading';
    const composerPlaceholder = manualEnabled
        ? 'اكتب ردك اليدوي للعميل...'
        : isDisconnected
            ? 'واتساب غير متصل - الإرسال متوقف'
            : 'المحادثة اليدوية معطلة بينما VELOR نشط';

    const onSubmit = async (event) => {
        event.preventDefault();
        const text = input.trim();
        if (!text || isSending || !manualEnabled) return;
        if (!draftIsFresh) {
            setDraftFreshnessNotice('راجع آخر رسالة من العميل وأنشئ ردًا جديدًا قبل الإرسال.');
            return;
        }

        const sent = await sendMessage(text, {
            sourceMessageInternalId: draftSourceMessageId,
            suggestionId: activeVariant?.suggestionId,
            variantStyle: activeVariant?.style,
            suggestionEdited: activeVariant ? text !== activeVariant.text.trim() : undefined,
        });
        if (!sent) return;

        setActiveVariant(null);
        setDraftSourceMessageId(null);
        setDraftFreshnessNotice('');
        setInput('');
    };

    const insertSuggestion = (suggestion) => {
        if (!manualEnabled) return;
        setInput(suggestion.text);
        setActiveVariant(suggestion);
        setDraftSourceMessageId(suggestion.sourceMessageInternalId || suggestion.answersMessageId || null);
        setDraftFreshnessNotice('');
        recordSuggestionInserted(suggestion);
        requestAnimationFrame(() => composerRef.current?.focus());
    };

    const copySuggestion = async (suggestion) => {
        try {
            await navigator.clipboard?.writeText(suggestion.text);
        } catch (err) {
            console.error('Copy suggestion failed:', err);
        }
    };

    const dismissSuggestion = (suggestion) => {
        if (activeVariant?.suggestionId === suggestion.suggestionId) {
            setActiveVariant(null);
        }
        updateSuggestedReplyStatus(suggestion.suggestionId, 'dismissed');
    };

    if (isLoading) return null;

    return (
        <div className="flex h-full min-h-0 flex-col bg-transparent" dir="rtl">
            <header className="flex h-14 shrink-0 items-center justify-between border-b border-white/[0.07] px-4 md:px-6">
                <div className="flex min-w-0 items-center gap-3">
                    <span className={`inline-flex items-center gap-2 rounded-xl border px-3 py-1 text-xs font-semibold ${tone.shell} ${tone.accent}`}>
                        <FiCpu className="h-3.5 w-3.5" />
                        {safeText(controlState?.label, 'حالة المحادثة')}
                    </span>
                    <span className="hidden truncate text-xs text-white/45 sm:inline-flex">
                        {safeText(controlState?.message, '')}
                    </span>
                </div>
                {onOpenAskVelor && (
                    <button
                        type="button"
                        onClick={onOpenAskVelor}
                        className="inline-flex items-center gap-2 rounded-xl border border-[#A855F7]/30 bg-[#7C3AED]/15 px-3.5 py-1.5 text-xs font-semibold text-[#E9D5FF] transition hover:bg-[#7C3AED]/25"
                    >
                        <FiCpu className="h-3.5 w-3.5 text-[#D8B4FE]" />
                        <span>اسأل VELOR</span>
                    </button>
                )}
            </header>

            <div className="flex-1 min-h-0 overflow-y-auto px-4 py-5 custom-scrollbar md:px-6">
                {chatMessages.length ? (
                    <div className="space-y-5">
                        {chatMessages.map((msg, index) => {
                            const owner = getMessageOwner(msg);
                            const isCustomer = owner === 'customer';
                            const isVelor = owner === 'velor';
                            const deliveryText = !isCustomer ? statusLabel(msg.delivery_status || msg.status) : null;
                            const sentAt = formatClockTime(msg.timestamp || msg.created_at, 'ar-EG');
                            const colors = messageTone(owner);

                            return (
                                <div
                                    key={msg.internal_message_id || msg.id || `${owner}-${index}`}
                                    ref={(node) => {
                                        [msg.internal_message_id, msg.id].filter(Boolean).forEach((id) => {
                                            if (node) messageRefs.current.set(String(id), node);
                                            else messageRefs.current.delete(String(id));
                                        });
                                    }}
                                    tabIndex={-1}
                                    className={`flex w-full ${isCustomer ? 'justify-start' : 'justify-end'}`}
                                >
                                    <div className={`flex max-w-[82%] gap-3 ${isCustomer ? 'flex-row' : 'flex-row-reverse'}`}>
                                        <div className={`mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs ${colors.avatar}`}>
                                            {isVelor ? <FiCpu className="h-4 w-4" /> : <FiUser className="h-4 w-4" />}
                                        </div>

                                        <div className={`flex min-w-0 flex-col ${isCustomer ? 'items-start' : 'items-end'}`}>
                                            <div className="mb-1 flex items-center gap-2 px-1">
                                                <span className="text-[11px] font-bold text-white/50">{LABELS[owner]}</span>
                                                {sentAt && <span className="text-[10px] text-white/40">{sentAt}</span>}
                                                {deliveryText && (
                                                    <span className={`inline-flex items-center gap-1 text-[10px] ${msg.delivery_status === 'failed' ? 'text-red-300' : 'text-white/40'}`}>
                                                        {msg.delivery_status === 'delivered' && <FiCheck className="h-3 w-3" />}
                                                        {deliveryText}
                                                    </span>
                                                )}
                                            </div>

                                            <div className={`rounded-2xl px-4 py-2.5 text-sm font-medium leading-6 ${colors.bubble}`}>
                                                <span className="whitespace-pre-wrap break-words">{msg.displayText}</span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            );
                        })}

                        {isCopilotActive && chatMessages.length > 0 && getMessageOwner(chatMessages[chatMessages.length - 1]) === 'customer' && (
                            <div className="flex w-full justify-end">
                                <div className="flex max-w-[78%] flex-row-reverse gap-3">
                                    <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[#A855F7]/30 bg-[#7C3AED]/25 text-[#F3E8FF]">
                                        <FiCpu className="h-4 w-4 animate-pulse" />
                                    </div>
                                    <div className="flex items-center gap-1.5 rounded-2xl rounded-tl-sm border border-white/10 bg-white/[0.04] px-4 py-3 text-white/50">
                                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-white/50" />
                                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-white/50" style={{ animationDelay: '150ms' }} />
                                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-white/50" style={{ animationDelay: '300ms' }} />
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                ) : (
                    <EmptyConversation />
                )}
                <div ref={chatEndRef} className="h-1" />
            </div>

            <div className="shrink-0 border-t border-white/[0.07] bg-[#080B13]/95 p-3 md:p-4">
                {followUps?.length > 0 && (
                    <div className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-amber-400/20 bg-amber-500/10 p-2.5 text-xs text-amber-100" aria-label="المتابعات النشطة">
                        <div className="flex min-w-0 items-center gap-2">
                            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-500/20 text-[10px] font-bold text-amber-300">!</span>
                            <span className="truncate text-xs font-semibold">المتابعات النشطة: {followUps[0].reason || 'متابعة موثّقة'}</span>
                        </div>
                        <div className="flex shrink-0 items-center gap-1.5">
                            {followUps[0].source_message_internal_id && (
                                <button type="button" onClick={() => messageRefs.current.get(String(followUps[0].source_message_internal_id))?.scrollIntoView({ behavior: 'smooth', block: 'center' })} className="rounded-lg bg-amber-500/20 px-2 py-1 text-[10px] font-semibold text-amber-200 hover:bg-amber-500/30">عرض الدليل</button>
                            )}
                            <button type="button" onClick={() => transitionFollowUp(followUps[0].task_id, 'complete')} className="rounded-lg bg-emerald-500/20 px-2 py-1 text-[10px] font-semibold text-emerald-200 hover:bg-emerald-500/30">اكتملت</button>
                            <button type="button" onClick={() => transitionFollowUp(followUps[0].task_id, 'snooze')} className="rounded-lg bg-white/10 px-2 py-1 text-[10px] font-semibold text-white/75 hover:bg-white/20">تأجيل</button>
                        </div>
                    </div>
                )}

                {(visibleSuggestions.length > 0 || isRegenerating) && (
                    <div className="mb-3 space-y-1.5">
                        <div className="flex items-center justify-between px-1 text-[11px]">
                            <span className="flex items-center gap-1.5 font-semibold text-[#D8B4FE]">
                                <FiCpu className="h-3 w-3" /> اقتراحات VELOR الذكية
                            </span>
                            <button
                                type="button"
                                onClick={regenerateSuggestedReplies}
                                disabled={isRegenerating}
                                className="flex items-center gap-1 text-[10px] font-medium text-white/50 transition hover:text-white"
                            >
                                <FiRefreshCw className={`h-3 w-3 ${isRegenerating ? 'animate-spin' : ''}`} />
                                {isRegenerating ? 'جاري الإنشاء' : 'إعادة توليد'}
                            </button>
                        </div>

                        {visibleSuggestions.length > 0 && (
                            <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide">
                                {visibleSuggestions.map((suggestion) => (
                                    <div key={suggestion.id} className="flex shrink-0 max-w-[340px] items-center justify-between gap-2.5 rounded-xl border border-white/10 bg-white/[0.04] p-2 text-xs">
                                        <div className="min-w-0 flex-1">
                                            <span className="rounded-md bg-[#7C3AED]/25 px-1.5 py-0.5 text-[9px] font-semibold text-[#E9D5FF]">{suggestion.label}</span>
                                            <p className="mt-1 truncate text-[11px] font-medium text-white/90" title={suggestion.text}>{suggestion.text}</p>
                                        </div>
                                        <div className="flex shrink-0 items-center gap-1">
                                            <button
                                                type="button"
                                                onClick={() => insertSuggestion(suggestion)}
                                                disabled={!manualEnabled}
                                                className="rounded-lg bg-[#7C3AED] px-2.5 py-1 text-[10px] font-bold text-white hover:bg-[#8B5CF6] disabled:opacity-40"
                                            >
                                                إدراج
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => copySuggestion(suggestion)}
                                                className="rounded-lg bg-white/10 px-2 py-1 text-[10px] font-medium text-white/70 hover:bg-white/20"
                                            >
                                                نسخ
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => dismissSuggestion(suggestion)}
                                                className="rounded-lg bg-white/5 px-1.5 py-1 text-[10px] text-white/40 hover:bg-white/10 hover:text-white"
                                            >
                                                <FiX className="h-3 w-3" />
                                            </button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}

                <div className={`rounded-2xl border p-3 ${tone.shell}`}>
                    {!manualEnabled ? (
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                            <div className="flex items-center gap-3 min-w-0">
                                <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${tone.icon}`}>
                                    {isDisconnected ? <FiAlertTriangle className="h-4 w-4" /> : <FiLock className="h-4 w-4" />}
                                </span>
                                <div className="min-w-0">
                                    <p className={`text-xs font-bold ${tone.text}`}>{safeText(controlState?.label, 'حالة المحادثة')}</p>
                                    <p className="truncate text-[11px] text-white/60">{safeText(controlState?.message, '')}</p>
                                </div>
                            </div>
                            {controlState?.cta && !isDisconnected && (
                                <button
                                    type="button"
                                    onClick={toggleCopilot}
                                    className="shrink-0 rounded-xl bg-[#7C3AED] px-4 py-2.5 text-xs font-bold text-white shadow-[0_0_15px_rgba(124,58,237,0.3)] transition-colors hover:bg-[#8B5CF6]"
                                >
                                    {controlState.cta}
                                </button>
                            )}
                        </div>
                    ) : (
                        <form onSubmit={onSubmit} className="flex flex-col gap-2">
                            <div className="flex items-center justify-between px-1 text-[11px]">
                                <span className="flex items-center gap-1 font-semibold text-emerald-400">
                                    <FiUser className="h-3 w-3" /> التحكم اليدوي مفعّل
                                </span>
                                <button type="button" onClick={toggleCopilot} className="text-[10px] text-white/50 underline hover:text-white">
                                    إعادة التحكم لـ VELOR
                                </button>
                            </div>
                            <div className="flex items-end gap-2 rounded-xl border border-white/10 bg-black/20 p-2 transition focus-within:border-[#A855F7]/40">
                                <textarea
                                    ref={composerRef}
                                    aria-label="محرر الرد اليدوي"
                                    value={input}
                                    onChange={(event) => {
                                        setInput(event.target.value);
                                        if (!event.target.value.trim()) {
                                            setActiveVariant(null);
                                            setDraftSourceMessageId(null);
                                        }
                                        setDraftFreshnessNotice('');
                                    }}
                                    onKeyDown={(event) => {
                                        if (event.key === 'Enter' && !event.shiftKey) {
                                            event.preventDefault();
                                            onSubmit(event);
                                        }
                                    }}
                                    placeholder={composerPlaceholder}
                                    className="custom-scrollbar max-h-[100px] min-h-[40px] flex-1 resize-none bg-transparent px-2 py-1.5 text-xs text-white outline-none placeholder-white/35 sm:text-sm"
                                    rows={1}
                                    dir="auto"
                                />
                                <button
                                    type="submit"
                                    disabled={!canSend}
                                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#7C3AED] text-white transition hover:bg-[#8B5CF6] disabled:bg-white/10 disabled:text-white/30"
                                    title="إرسال"
                                    aria-label="إرسال"
                                >
                                    <FiSend className="h-4 w-4" />
                                </button>
                            </div>
                            {draftFreshnessNotice && (
                                <p role="alert" className="mt-1 rounded-lg border border-amber-400/20 bg-amber-500/10 px-3 py-1.5 text-[10px] text-amber-100">
                                    {draftFreshnessNotice}
                                </p>
                            )}
                        </form>
                    )}
                </div>
            </div>
        </div>
    );
};
