import { useMemo, useState } from 'react';
import { FiChevronDown, FiCpu, FiMessageCircle, FiUser } from 'react-icons/fi';
import { useWorkspace } from '../../context/WorkspaceContext';
import { deriveCustomerBrief, evidenceSummary, getCleanCustomerDisplay, getLeadChannelPresentation, safeText } from './workspaceUx';
import { canonicalEvidenceRef } from './workspacePresentation';

const valueOrUnknown = (value) => safeText(value, 'غير معروف بعد');

export const DecisionBrief = ({ onDismiss }) => {
    const {
        currentLead,
        permanentContext,
        controlState,
        toggleCopilot,
        requestComposerFocus,
        navigateToMessage,
    } = useWorkspace();
    const [detailsOpen, setDetailsOpen] = useState(true);
    const brief = useMemo(() => deriveCustomerBrief({
        backendBrief: currentLead?.customer_brief,
        currentLead,
    }), [currentLead]);

    if (!currentLead) return null;

    const { displayName } = getCleanCustomerDisplay(currentLead, permanentContext?.identity || {});
    const channel = getLeadChannelPresentation(currentLead);
    const missing = brief.missing_data || [];
    const knownFacts = brief.known_facts || [];
    const evidence = (brief.evidence || []).map((item) => ({ ...canonicalEvidenceRef(item), summary: evidenceSummary(item) }));
    const canWriteNow = Boolean(controlState?.manualEnabled);
    const requiresManualControl = Boolean(brief.human_takeover || canWriteNow);
    const decisionState = brief.human_takeover
        ? { label: 'تحتاج تدخّلًا بشريًا', className: 'border-amber-300/25 bg-amber-300/[0.07] text-amber-100' }
        : brief.insufficient_data || missing.length
            ? { label: 'معلومة ناقصة — راجع قبل الرد', className: 'border-amber-300/20 bg-amber-300/[0.05] text-amber-100' }
            : { label: 'قرار مرتبط بدليل المحادثة', className: 'border-emerald-300/20 bg-emerald-300/[0.05] text-emerald-100' };

    const handleReplyAction = async () => {
        if (!canWriteNow) {
            const controlGranted = await toggleCopilot();
            if (!controlGranted) return;
        }
        requestComposerFocus();
        onDismiss?.();
    };

    const handleEvidenceNavigation = (messageId) => {
        navigateToMessage(messageId);
        onDismiss?.();
    };

    return (
        <aside className="flex h-full min-h-0 flex-col overflow-y-auto p-4 custom-scrollbar" dir="rtl">
            <div className="mb-4 flex items-center gap-3 border-b border-white/10 pb-4">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-[#A855F7]/35 bg-[#A855F7]/10 text-[#D8B4FE]">{channel.key === 'whatsapp' ? <FiMessageCircle /> : <FiUser />}</div>
                <div className="min-w-0"><h1 className="truncate text-lg font-bold text-white">{displayName}</h1><p className="truncate text-xs text-white/55">{channel.label} · {valueOrUnknown(controlState?.label)}</p></div>
            </div>

            <section className="rounded-2xl border border-[#A855F7]/30 bg-[radial-gradient(circle_at_top_right,rgba(168,85,247,0.15),transparent_48%),rgba(255,255,255,0.025)] p-4">
                <div className="mb-4 flex items-center gap-2 text-[#E9D5FF]"><FiCpu className="h-4 w-4" /><h2 className="text-sm font-bold">ملخص القرار</h2></div>
                <p className={`mb-4 rounded-xl border px-3 py-2 text-xs font-bold ${decisionState.className}`}>{decisionState.label}</p>
                <dl className="space-y-4">
                    <div><dt className="text-[11px] font-bold text-white/45">ما الذي حدث؟</dt><dd className="mt-1 text-sm font-bold leading-6 text-white">{valueOrUnknown(brief.customer_state)}</dd></div>
                    <div><dt className="text-[11px] font-bold text-white/45">ما الذي يريده العميل؟</dt><dd className="mt-1 text-sm leading-6 text-white/85">{valueOrUnknown(brief.what_customer_wants)}</dd></div>
                    <div><dt className="text-[11px] font-bold text-white/45">ما الذي نعرفه؟</dt><dd className="mt-2">{knownFacts.length ? <ul className="space-y-2">{knownFacts.map((fact, index) => <li key={`${fact.label}-${index}`} className="rounded-xl border border-white/10 bg-white/[0.035] p-2.5 text-xs leading-6 text-white/75"><span className="font-bold text-white/50">{fact.label}:</span> {fact.value}</li>)}</ul> : <span className="text-sm text-white/50">لا توجد حقيقة تجارية إضافية مؤكدة بعد.</span>}</dd></div>
                    <div><dt className="text-[11px] font-bold text-white/45">ما الذي ما زال ناقصًا؟</dt><dd className="mt-1 text-sm leading-6 text-amber-100">{missing.length ? missing.join('، ') : 'لا توجد معلومة حاسمة ناقصة ظاهرة الآن.'}</dd></div>
                    <div className="rounded-xl border border-[#A855F7]/25 bg-[#7C3AED]/10 p-3"><dt className="text-[11px] font-bold text-[#D8B4FE]">ما الذي تفعله الآن؟</dt><dd className="mt-1 text-sm font-bold leading-6 text-white">{valueOrUnknown(brief.best_next_step)}</dd></div>
                    <div><dt className="text-[11px] font-bold text-white/45">لماذا؟</dt><dd className="mt-1 text-sm leading-6 text-white/70">{valueOrUnknown(brief.latest_signal)}</dd></div>
                </dl>

                {requiresManualControl && (
                    <button type="button" onClick={handleReplyAction} className="mt-5 min-h-11 w-full rounded-xl bg-[#7C3AED] px-3 py-2.5 text-sm font-bold text-white hover:bg-[#8B5CF6]">
                        {canWriteNow ? 'اكتب الرد الآن' : 'تولَّ المحادثة واكتب الرد'}
                    </button>
                )}
                {canWriteNow && <button type="button" onClick={toggleCopilot} className="mt-2 min-h-11 w-full rounded-xl border border-white/10 px-3 py-2.5 text-xs font-bold text-white/70 hover:bg-white/[0.06]">إعادة التحكم إلى VELOR</button>}
            </section>

            <button type="button" onClick={() => setDetailsOpen((value) => !value)} className="mt-3 flex min-h-11 items-center justify-between rounded-xl border border-white/10 bg-white/[0.03] px-3 py-3 text-xs font-bold text-white/75 hover:bg-white/[0.06]" aria-expanded={detailsOpen}>
                <span>الأدلة التي بُني عليها القرار {evidence.length ? `(${evidence.length})` : ''}</span>
                <FiChevronDown className={`transition-transform ${detailsOpen ? 'rotate-180' : ''}`} />
            </button>
            {detailsOpen && (
                <div className="mt-2 space-y-3 rounded-xl border border-white/10 bg-white/[0.025] p-3 text-xs leading-6 text-white/65">
                    {brief.important_signals.length > 0 && <div><p className="font-bold text-white/80">الإشارات المهمة</p><p className="mt-1">{brief.important_signals.join('، ')}</p></div>}
                    <div><p className="font-bold text-white/80">الأدلة المصدرية</p><div className="mt-2 space-y-2">{evidence.length ? evidence.map((item, index) => item.messageId ? <button key={`${item.messageId}-${index}`} type="button" onClick={() => handleEvidenceNavigation(item.messageId)} className="min-h-11 w-full rounded-lg border border-white/10 p-2 text-right hover:border-[#A855F7]/35">{item.summary}</button> : <p key={index} className="rounded-lg border border-white/10 p-2">{item.summary}</p>) : <p>لا توجد إحالة رسالة قابلة للعرض بعد.</p>}</div></div>
                    <p><span className="font-bold text-white/80">المتوقع بعد الخطوة:</span> {valueOrUnknown(brief.expected_next)}</p>
                </div>
            )}
        </aside>
    );
};
