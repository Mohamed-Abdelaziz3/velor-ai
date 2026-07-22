import { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { FiCopy, FiCpu, FiMaximize2, FiMinimize2, FiSend } from 'react-icons/fi';
import api from '../../services/api';
import { evidenceSummary, safeText } from './workspaceUx';
import { canonicalEvidenceRef } from './workspacePresentation';
import { useWorkspaceSafe } from '../../context/WorkspaceContext';

const COMPANY_STARTERS = [
    'ما أهم فرصة الآن؟',
    'ما أكثر اعتراض متكرر؟',
    'ما المنتج الأكثر سؤالًا؟',
    'ما الملاحظات المهمة؟',
];


const INSUFFICIENT_ANSWER = 'لا توجد بيانات كافية من المحادثة بعد.';
const EMPTY_CONTEXT_ANSWER = 'لا أرى رسائل مقروءة لهذا العميل داخل مساحة العمل بعد. لا أستطيع تحديد الاهتمام الرئيسي قبل ظهور رسالة واضحة من العميل.';

const EvidenceList = ({ evidence = [], onNavigate }) => {
    const evidenceItems = Array.isArray(evidence) ? evidence : [evidence];
    const items = evidenceItems.map((item) => ({ ...canonicalEvidenceRef(item), label: item?.label || evidenceSummary(item) })).filter((item) => item.label).slice(0, 3);
    if (!items.length) return null;

    return (
        <div className="mt-3 border-t border-white/10 pt-3">
            <p className="mb-2 text-[10px] font-bold text-white/50">إشارات مستخدمة</p>
            <div className="space-y-2">
                {items.map((item, index) => item.messageId ? (
                    <button type="button" onClick={() => onNavigate?.(item.messageId)} key={`${item.messageId}-${index}`} className="min-h-11 w-full rounded-[12px] border border-white/10 bg-black/[0.16] p-3 text-right hover:border-[#A855F7]/35"><span className="line-clamp-3 text-xs leading-6 text-white/75">{item.label}</span></button>
                ) : <div key={`${item.label}-${index}`} className="rounded-[12px] border border-white/10 bg-black/[0.16] p-3"><p className="line-clamp-3 text-xs leading-6 text-white/75">{item.label}</p></div>)}
            </div>
        </div>
    );
};

const StructuredAnswer = ({ payload, onInsertDraft, onNavigateEvidence }) => {
    const missing = payload?.unknowns || payload?.missing_data || [];
    const evidence = payload?.evidence || payload?.evidence_refs || [];
    const suggestedReply = safeText(payload?.draft_reply || payload?.suggested_reply, '');
    const reasoningSummary = safeText(payload?.reasoning_summary, '');
    const rawAnswer = safeText(payload?.answer || payload?.reply || payload?.content, INSUFFICIENT_ANSWER);
    const isEmptyContext = rawAnswer.includes(INSUFFICIENT_ANSWER) || rawAnswer.includes('لا توجد أدلة كافية');
    const answer = isEmptyContext ? EMPTY_CONTEXT_ANSWER : rawAnswer;
    const suggestedAction = isEmptyContext
        ? 'انتظر رسالة جديدة من العميل أو افتح محادثة تحتوي على رسائل قبل طلب التحليل.'
        : safeText(payload?.recommended_action || payload?.suggested_action, '');
    const missingItems = Array.isArray(missing) ? missing : [missing];
    const visibleMissing = isEmptyContext
        ? ['رسائل العميل داخل المحادثة', 'نوع الخدمة أو المنتج', 'الاحتياج']
        : missingItems.map((item) => safeText(item, '')).filter((item) => item && item !== INSUFFICIENT_ANSWER && !item.includes('إشارات كافية'));

    return (
        <div className="space-y-3">
            <p className="whitespace-pre-wrap">{answer}</p>
            {reasoningSummary && <p className="rounded-[12px] border border-white/10 bg-white/[0.035] p-3 text-xs leading-6 text-white/65"><span className="font-bold text-white/80">السبب المختصر:</span> {reasoningSummary}</p>}
            {suggestedAction && (
                <div className="rounded-[12px] border border-white/10 bg-white/[0.06] p-3">
                    <p className="mb-1 text-[10px] font-bold text-white/50">الإجراء المقترح</p>
                    <p className="text-xs leading-6 text-white/80">{suggestedAction}</p>
                </div>
            )}
            {visibleMissing.length > 0 && (
                <div className="rounded-[12px] border border-amber-400/20 bg-amber-500/10 p-3">
                    <p className="mb-1 text-[10px] font-bold text-amber-200">بيانات ناقصة</p>
                    <p className="text-xs leading-6 text-amber-100">{visibleMissing.join('، ')}</p>
                </div>
            )}
            {suggestedReply && (
                <div className="rounded-[12px] border border-[#A855F7]/25 bg-[#7C3AED]/10 p-3">
                    <div className="mb-2 flex items-center justify-between gap-3">
                        <p className="text-[10px] font-bold text-[#E9D5FF]">رد مقترح</p>
                        <button
                            type="button"
                            onClick={() => navigator.clipboard?.writeText(suggestedReply)}
                            className="flex h-7 w-7 items-center justify-center rounded-[9px] bg-white/[0.08] text-white hover:bg-white/[0.12]"
                            title="نسخ الرد المقترح"
                            aria-label="نسخ الرد المقترح"
                        >
                            <FiCopy className="h-3.5 w-3.5" />
                        </button>
                        <button type="button" onClick={() => onInsertDraft?.(suggestedReply)} className="min-h-9 rounded-[9px] bg-[#7C3AED] px-3 text-xs font-bold text-white hover:bg-[#8B5CF6]">إدراج في المحرر</button>
                    </div>
                    <p className="whitespace-pre-wrap text-xs leading-6 text-white/90">{suggestedReply}</p>
                </div>
            )}
            <EvidenceList evidence={evidence} onNavigate={onNavigateEvidence} />
        </div>
    );
};

export const VelorChatInterface = ({ companyId, leadId, onNavigateEvidence }) => {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [isFullscreen, setIsFullscreen] = useState(false);
    const messagesEndRef = useRef(null);

    const workspace = useWorkspaceSafe();
    const starters = useMemo(() => {
        if (!leadId) return COMPANY_STARTERS;
        const hasBudget = Boolean(workspace?.currentLead?.owner_intelligence?.customer_understanding?.budget);
        return [
            'ما اهتمامه الرئيسي؟',
            'ما آخر سؤال لم نجب عنه؟',
            hasBudget ? 'هل المنتج مناسب لميزانيته؟' : 'ما المعلومات الناقصة؟',
            'ليه محتاج تدخلي؟',
            'جهز لي رد طبيعي.',
        ];
    }, [leadId, workspace?.currentLead?.owner_intelligence?.customer_understanding?.budget]);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, isLoading]);

    useEffect(() => {
        setMessages([]);
        setInput('');
    }, [leadId]);

    useEffect(() => {
        if (!isFullscreen) return undefined;

        const previousOverflow = document.body.style.overflow;
        const handleKeyDown = (event) => {
            if (event.key === 'Escape') setIsFullscreen(false);
        };

        document.body.style.overflow = 'hidden';
        window.addEventListener('keydown', handleKeyDown);
        return () => {
            document.body.style.overflow = previousOverflow;
            window.removeEventListener('keydown', handleKeyDown);
        };
    }, [isFullscreen]);

    const sendQuestion = async (question) => {
        const userMsg = question.trim();
        if (!userMsg || isLoading) return;

        setInput('');
        setMessages((prev) => [...prev, { role: 'user', content: userMsg }]);
        setIsLoading(true);

        try {
            const endpoint = leadId
                ? `/api/v1/copilot/chat/lead/${leadId}${companyId ? `?company_id=${companyId}` : ''}`
                : `/api/v1/copilot/chat${companyId ? `?company_id=${companyId}` : ''}`;
            const res = await api.post(endpoint, {
                message: userMsg,
                scope: leadId ? 'lead' : 'company',
                lead_id: leadId || undefined,
            });
            const payload = res.data || {};
            setMessages((prev) => [...prev, {
                role: 'assistant',
                content: safeText(payload.answer || payload.reply, INSUFFICIENT_ANSWER),
                payload,
            }]);
        } catch (error) {
            console.error('Ask VELOR error:', error);
            setMessages((prev) => [...prev, {
                role: 'assistant',
                content: 'عذرًا، لم أستطع معالجة الطلب الآن.',
                isError: true,
            }]);
        } finally {
            setIsLoading(false);
        }
    };

    const handleSubmit = (event) => {
        event.preventDefault();
        sendQuestion(input);
    };

    const containerClassName = isFullscreen
        ? 'fixed inset-0 z-50 flex flex-col overflow-hidden border border-white/10 bg-[#080B13] font-sans shadow-2xl shadow-black/60 md:inset-5 md:rounded-[22px]'
        : 'flex h-full min-h-0 flex-col overflow-hidden bg-transparent font-sans';

    return (
        <div className={containerClassName} dir="rtl">
            <header className="flex shrink-0 items-center justify-between gap-3 border-b border-white/10 p-4">
                <div className="flex min-w-0 items-center gap-3">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-[#7C3AED] text-white shadow-[0_0_24px_rgba(124,58,237,0.45)]">
                        <FiCpu className="h-5 w-5" />
                    </div>
                    <div className="min-w-0">
                        <h3 className="truncate text-xl font-bold tracking-tight text-white">اسأل VELOR</h3>
                        <p className="truncate text-sm text-white/60">مساعد مبيعات موثوق</p>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={() => setIsFullscreen((value) => !value)}
                    className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] border border-white/10 bg-white/[0.04] text-white/60 transition-all hover:bg-white/[0.08] hover:text-white"
                    aria-label={isFullscreen ? 'إغلاق العرض الكامل' : 'فتح العرض الكامل'}
                    title={isFullscreen ? 'إغلاق العرض الكامل' : 'عرض كامل'}
                >
                    {isFullscreen ? <FiMinimize2 className="h-4 w-4" /> : <FiMaximize2 className="h-4 w-4" />}
                </button>
            </header>

            <div className="flex shrink-0 flex-wrap gap-2 border-b border-white/10 px-4 py-3">
                {starters.map((starter) => (
                    <button
                        key={starter}
                        type="button"
                        onClick={() => sendQuestion(starter)}
                        disabled={isLoading}
                        className="rounded-[12px] border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-bold text-white transition-colors hover:border-[#A855F7]/30 hover:bg-[#7C3AED]/10 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {starter}
                    </button>
                ))}
            </div>

            <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
                {!messages.length && (
                    <div className="rounded-[18px] border border-[#A855F7]/30 bg-[radial-gradient(circle_at_top_right,rgba(168,85,247,0.18),transparent_48%),rgba(124,58,237,0.08)] p-5 shadow-[0_0_26px_rgba(124,58,237,0.12)]">
                        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[#7C3AED]/25 text-[#E9D5FF]">
                            <FiCpu className="h-5 w-5" />
                        </div>
                        <h4 className="text-lg font-bold text-[#E9D5FF]">جاهز لمساعدتك</h4>
                        <p className="mt-3 text-sm leading-7 text-white/70">
                            اسأل أي سؤال عن هذا العميل وسأجيب فقط من المحادثة والبيانات المتاحة.
                        </p>
                    </div>
                )}

                <div className="mt-5 space-y-5">
                    <AnimatePresence initial={false}>
                        {messages.map((msg, index) => (
                            <motion.div
                                key={`${msg.role}-${index}`}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                className={`flex max-w-[94%] gap-3 ${msg.role === 'user' ? 'mr-auto flex-row-reverse' : 'ml-auto'}`}
                            >
                                {msg.role === 'assistant' && (
                                    <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#7C3AED]/25 text-[#E9D5FF]">
                                        <FiCpu className="h-4 w-4" />
                                    </div>
                                )}
                                <div
                                    className={`rounded-2xl p-4 text-sm font-bold leading-7 shadow-sm ${msg.role === 'user'
                                            ? 'rounded-tr-sm border border-white/10 bg-white/[0.06] text-white'
                                            : msg.isError
                                                ? 'rounded-tl-sm border border-red-400/20 bg-red-500/10 text-red-100'
                                                : 'rounded-tl-sm border border-[#A855F7]/25 bg-[#2A163F] text-white'
                                        }`}
                                >
                                    {msg.payload ? <StructuredAnswer payload={msg.payload} onInsertDraft={workspace?.insertComposerText} onNavigateEvidence={(messageId) => {
                                        workspace?.navigateToMessage(messageId);
                                        onNavigateEvidence?.(messageId);
                                    }} /> : <p className="whitespace-pre-wrap">{safeText(msg.content)}</p>}
                                </div>
                            </motion.div>
                        ))}
                        {isLoading && (
                            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="ml-auto flex max-w-[85%] gap-3">
                                <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#7C3AED]/25 text-[#E9D5FF]">
                                    <FiCpu className="h-4 w-4" />
                                </div>
                                <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm border border-white/10 bg-white/[0.04] p-4 text-white/50 shadow-sm">
                                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-white/50" />
                                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-white/50" style={{ animationDelay: '0.1s' }} />
                                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-white/50" style={{ animationDelay: '0.2s' }} />
                                </div>
                            </motion.div>
                        )}
                    </AnimatePresence>
                    <div ref={messagesEndRef} />
                </div>
            </div>

            <div className="shrink-0 border-t border-white/10 p-4">
                <form onSubmit={handleSubmit} className="flex items-end gap-2 rounded-[16px] border border-white/10 bg-white/[0.04] p-2 shadow-sm transition-colors focus-within:border-[#A855F7]/30">
                    <textarea
                        value={input}
                        onChange={(event) => setInput(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter' && !event.shiftKey) {
                                event.preventDefault();
                                handleSubmit(event);
                            }
                        }}
                        placeholder="اكتب سؤالك..."
                        className="max-h-32 min-h-[44px] flex-1 resize-none bg-transparent p-3 text-sm text-white outline-none placeholder-white/40 custom-scrollbar"
                        rows={1}
                        dir="auto"
                        disabled={isLoading}
                    />
                    <button
                        type="submit"
                        disabled={isLoading || !input.trim()}
                        className="mb-1 flex h-11 w-11 shrink-0 items-center justify-center rounded-[13px] bg-[#7C3AED] text-white transition-colors hover:bg-[#8B5CF6] disabled:cursor-not-allowed disabled:bg-white/[0.08] disabled:text-white/30"
                        title="إرسال السؤال"
                        aria-label="إرسال السؤال"
                    >
                        <FiSend size={16} />
                    </button>
                </form>
            </div>
        </div>
    );
};
