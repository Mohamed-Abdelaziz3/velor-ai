import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { FiCpu, FiX } from 'react-icons/fi';
import { WorkspaceProvider, useWorkspace } from '../../context/WorkspaceContext';
import { DecisionBrief } from '../../components/workspace/DecisionBrief';
import { WorkspaceChat } from '../../components/workspace/WorkspaceChat';
import { VelorChatInterface } from '../../components/workspace/VelorChatInterface';

const FOCUSABLE_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled])',
    'textarea:not([disabled])',
    'select:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
].join(',');

const useAccessibleDialog = ({ isOpen, onClose, dialogRef, initialFocusRef }) => {
    const restoreFocusRef = useRef(null);

    useEffect(() => {
        if (!isOpen) return undefined;

        restoreFocusRef.current = document.activeElement;
        const previousOverflow = document.body.style.overflow;
        const focusDialog = window.requestAnimationFrame(() => {
            (initialFocusRef.current || dialogRef.current)?.focus();
        });
        const handleKeyDown = (event) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                onClose();
                return;
            }
            if (event.key !== 'Tab' || !dialogRef.current) return;

            const focusable = [...dialogRef.current.querySelectorAll(FOCUSABLE_SELECTOR)]
                .filter((element) => !element.hasAttribute('disabled'));
            if (!focusable.length) {
                event.preventDefault();
                dialogRef.current.focus();
                return;
            }

            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        };

        document.body.style.overflow = 'hidden';
        document.addEventListener('keydown', handleKeyDown);
        return () => {
            window.cancelAnimationFrame(focusDialog);
            document.body.style.overflow = previousOverflow;
            document.removeEventListener('keydown', handleKeyDown);
            restoreFocusRef.current?.focus?.();
        };
    }, [dialogRef, initialFocusRef, isOpen, onClose]);
};

const LoadingState = () => (
    <div
        className="flex h-full min-h-[420px] flex-1 flex-col items-center justify-center bg-velor-bg"
        dir="rtl"
        lang="ar"
        role="status"
        aria-live="polite"
    >
        <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-velor-purple/25 bg-velor-purple/10 shadow-velor-glow">
            <FiCpu className="h-6 w-6 animate-pulse text-velor-purple" aria-hidden="true" />
        </span>
        <p className="text-sm font-medium text-velor-secondary">جاري تجهيز مساحة العميل...</p>
    </div>
);

const ErrorState = ({ onRetry }) => {
    const navigate = useNavigate();
    return (
        <div
            className="flex h-full min-h-[420px] flex-1 flex-col items-center justify-center bg-velor-bg px-5 text-center"
            dir="rtl"
            lang="ar"
            role="alert"
        >
            <FiCpu className="mb-4 h-12 w-12 text-velor-red" aria-hidden="true" />
            <p className="mb-2 text-sm font-bold text-white">حصلت مشكلة في تحميل مساحة العميل</p>
            <p className="mb-6 max-w-lg text-xs leading-5 text-velor-muted">
                بيانات المحادثة غير متاحة حاليًا، ولم يتم عرض أي بيانات افتراضية بدلًا منها.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
                <button type="button" onClick={onRetry} className="velor-button-primary">حاول تاني</button>
                <button type="button" onClick={() => navigate('/inbox')} className="velor-button-secondary">رجوع للمحادثات</button>
            </div>
        </div>
    );
};

const WorkspaceContent = () => {
    const { isLoading, error, currentLead: lead, retryWorkspace } = useWorkspace();
    const [askVelorOpen, setAskVelorOpen] = useState(false);
    const [briefOpen, setBriefOpen] = useState(false);
    const askDialogRef = useRef(null);
    const askCloseRef = useRef(null);
    const briefDialogRef = useRef(null);
    const briefCloseRef = useRef(null);

    const closeAskVelor = useCallback(() => setAskVelorOpen(false), []);
    const closeBrief = useCallback(() => setBriefOpen(false), []);
    const openAskVelor = () => {
        setBriefOpen(false);
        setAskVelorOpen(true);
    };
    const openBrief = () => {
        setAskVelorOpen(false);
        setBriefOpen(true);
    };

    useAccessibleDialog({
        isOpen: askVelorOpen,
        onClose: closeAskVelor,
        dialogRef: askDialogRef,
        initialFocusRef: askCloseRef,
    });
    useAccessibleDialog({
        isOpen: briefOpen,
        onClose: closeBrief,
        dialogRef: briefDialogRef,
        initialFocusRef: briefCloseRef,
    });

    if (isLoading) return <LoadingState />;
    if (error) return <ErrorState onRetry={retryWorkspace} />;

    return (
        <section className="relative flex h-full min-h-0 flex-1 overflow-hidden bg-velor-bg p-3 text-velor-text md:p-5" dir="rtl" lang="ar" aria-label="مساحة عمل محادثة العميل">
            <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
                <div className="absolute -right-44 -top-52 h-[420px] w-[420px] rounded-full bg-velor-purple/[0.07] blur-[130px]" />
                <div className="absolute -bottom-56 left-1/4 h-[380px] w-[380px] rounded-full bg-velor-blue/[0.035] blur-[140px]" />
            </div>

            <div className="relative z-10 mx-auto flex h-full min-h-0 w-full max-w-[1620px] flex-col gap-3 overflow-hidden xl:grid xl:grid-cols-[minmax(0,1fr)_340px] xl:gap-4">
                <div className="flex shrink-0 items-center justify-between gap-3 xl:hidden">
                    <button
                        type="button"
                        onClick={openBrief}
                        aria-expanded={briefOpen}
                        aria-controls="mobile-decision-brief"
                        aria-label="فتح ملخص القرار"
                        className="velor-button-secondary px-4 text-xs"
                    >
                        ملخص القرار
                    </button>
                    <button
                        type="button"
                        onClick={openAskVelor}
                        aria-expanded={askVelorOpen}
                        aria-controls="ask-velor-dialog"
                        aria-label="فتح مساعد VELOR لهذه المحادثة"
                        className="velor-button-primary px-4 text-xs"
                    >
                        اسأل VELOR
                    </button>
                </div>

                <motion.div
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="velor-card flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[1.25rem] border border-white/[0.08] bg-[#0d0f18]/95 shadow-[0_24px_80px_rgba(0,0,0,.35)]"
                >
                    <WorkspaceChat onOpenAskVelor={openAskVelor} />
                </motion.div>

                <motion.div
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="velor-card hidden min-h-0 overflow-hidden rounded-[1.25rem] border border-white/[0.08] bg-[#0b0d15]/95 shadow-velor-card xl:block"
                >
                    <DecisionBrief />
                </motion.div>
            </div>

            {briefOpen && (
                <div className="fixed inset-0 z-[70] flex items-end bg-black/72 backdrop-blur-sm xl:hidden" onMouseDown={(event) => event.target === event.currentTarget && closeBrief()}>
                    <motion.section
                        id="mobile-decision-brief"
                        ref={briefDialogRef}
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="mobile-decision-brief-title"
                        tabIndex={-1}
                        initial={{ opacity: 0, y: 40 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="flex max-h-[calc(100dvh-4.5rem)] w-full flex-col overflow-hidden rounded-t-[24px] border border-velor-border bg-velor-panel shadow-[0_-24px_100px_rgba(0,0,0,.7)]"
                        style={{ marginBottom: 'max(0px, env(safe-area-inset-bottom))' }}
                    >
                        <div className="flex shrink-0 items-center justify-between border-b border-white/10 px-4 py-3">
                            <h2 id="mobile-decision-brief-title" className="text-sm font-bold text-white">ملخص القرار</h2>
                            <button ref={briefCloseRef} type="button" onClick={closeBrief} className="flex h-10 w-10 items-center justify-center rounded-lg text-white/60 hover:bg-white/10 hover:text-white" aria-label="إغلاق ملخص القرار"><FiX /></button>
                        </div>
                        <div className="min-h-0 flex-1 overflow-hidden"><DecisionBrief onDismiss={closeBrief} /></div>
                    </motion.section>
                </div>
            )}

            <div
                className={`fixed inset-0 z-50 flex justify-end bg-black/55 p-0 backdrop-blur-[2px] transition-[opacity,visibility] duration-200 md:p-5 ${askVelorOpen ? 'visible opacity-100' : 'invisible pointer-events-none opacity-0'}`}
                aria-hidden={!askVelorOpen}
                onMouseDown={(event) => event.target === event.currentTarget && closeAskVelor()}
            >
                <motion.aside
                    id="ask-velor-dialog"
                    ref={askDialogRef}
                    role="dialog"
                    aria-modal={askVelorOpen ? 'true' : undefined}
                    aria-labelledby="ask-velor-title"
                    tabIndex={-1}
                    animate={{ x: askVelorOpen ? 0 : -24 }}
                    className="flex h-full w-full flex-col overflow-hidden border border-velor-border bg-velor-panel shadow-2xl md:max-w-[430px] md:rounded-[18px]"
                >
                    <div className="flex shrink-0 items-center justify-between border-b border-white/10 p-3">
                        <h2 id="ask-velor-title" className="text-sm font-bold text-white">اسأل VELOR عن المحادثة دي</h2>
                        <button ref={askCloseRef} type="button" onClick={closeAskVelor} className="flex h-10 w-10 items-center justify-center rounded-lg text-white/60 hover:bg-white/10 hover:text-white" aria-label="إغلاق مساعد VELOR"><FiX aria-hidden="true" /></button>
                    </div>
                    <div className="min-h-0 flex-1">
                        <VelorChatInterface
                            companyId={lead?.company_id}
                            leadId={lead?.id || lead?.lead_id}
                            onNavigateEvidence={closeAskVelor}
                        />
                    </div>
                </motion.aside>
            </div>
        </section>
    );
};

const CustomerWorkspace = () => {
    const { id } = useParams();
    return (
        <WorkspaceProvider leadId={id}>
            <WorkspaceContent />
        </WorkspaceProvider>
    );
};

export default CustomerWorkspace;
