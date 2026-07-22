import { FiFileText, FiRefreshCw, FiTrash2, FiUploadCloud } from 'react-icons/fi';
import { sourceStatus } from './settingsUi';

const formatDate = (value) => {
    if (!value) return 'غير مُبلغ';
    const text = String(value).trim();
    const normalized = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(text) ? `${text}Z` : text;
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return 'توقيت غير صالح';
    return new Intl.DateTimeFormat('ar-EG', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Africa/Cairo' }).format(date);
};

const toneClasses = {
    ready: 'border-velor-green/20 bg-velor-green/10 text-[#9df1d1]',
    error: 'border-rose-400/20 bg-rose-500/10 text-rose-200',
    disabled: 'border-white/10 bg-white/[0.035] text-velor-muted',
    processing: 'border-velor-amber/20 bg-velor-amber/10 text-[#f9d28a]',
};

const toneLabels = {
    ready: 'نشط وقابل للاسترجاع',
    error: 'خطأ في المعالجة',
    disabled: 'معطّل',
    processing: 'جاري المعالجة',
};

const sourceTypeLabel = (value) => {
    const type = String(value || 'file').trim().toLowerCase();
    if (type === 'file') return 'ملف';
    if (type === 'policy') return 'سياسة';
    if (type === 'faq') return 'أسئلة شائعة';
    return type.toUpperCase();
};

export const KnowledgeSourcesPanel = ({ sources, loading, error, uploading, busySourceId, onUpload, onToggle, onReprocess, onDelete, onRetry }) => (
    <section className="space-y-5" aria-labelledby="knowledge-heading" dir="rtl" lang="ar">
        <div>
            <h2 id="knowledge-heading" className="text-base font-semibold text-white">السياسات ومصادر المعرفة</h2>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-velor-muted">ارفع مستندات التوصيل أو الاسترجاع أو الضمان أو الأسئلة الشائعة أو سياسة البيع. الحالة أدناه هي حالة الاسترجاع الحالية التي أبلغ بها الخادم، وليست مجرد إثبات لاختيار ملف.</p>
        </div>

        <label className={`flex min-h-32 cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed p-5 text-center transition-colors ${uploading ? 'cursor-wait border-velor-purple/40 bg-velor-purple/10' : 'border-white/15 bg-white/[0.02] hover:border-velor-purple/40'}`}>
            <input type="file" className="sr-only" accept=".pdf,.docx,.csv,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/csv,text/plain" disabled={uploading} onChange={onUpload} />
            {uploading ? <FiRefreshCw className="h-7 w-7 animate-spin text-velor-purple" /> : <FiUploadCloud className="h-7 w-7 text-velor-purple" />}
            <span className="mt-3 text-xs font-semibold text-white">{uploading ? 'جاري رفع المصدر ومعالجته…' : 'اختر ملف معرفة أو سياسة واحدًا'}</span>
            <span className="mt-1 text-[11px] text-velor-muted">PDF أو DOCX أو CSV أو TXT بترميز UTF-8 · الحد الأقصى 5 ميجابايت حسب عقد الواجهة الحالي</span>
        </label>

        {error && <div className="flex flex-col items-start justify-between gap-3 rounded-xl border border-rose-400/20 bg-rose-500/10 p-4 text-xs leading-5 text-rose-100 sm:flex-row sm:items-center" role="alert"><span>{error}</span><button type="button" onClick={onRetry} className="min-h-11 rounded-lg border border-white/15 px-3 py-2 text-[11px] font-semibold text-white">إعادة التحميل</button></div>}

        {loading ? (
            <div className="flex min-h-40 items-center justify-center" role="status" aria-label="جاري تحميل مصادر المعرفة"><FiRefreshCw className="animate-spin text-velor-purple" /></div>
        ) : !sources.length ? (
            <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6 text-center"><FiFileText className="mx-auto h-7 w-7 text-velor-muted" /><p className="mt-3 text-xs font-semibold text-white">لم تتم إضافة مصادر معرفة</p><p className="mt-1 text-[11px] text-velor-muted">تظل السياسات الناقصة غير معروفة؛ لا ينشئ VELOR سياسة افتراضية بدلًا منها.</p></div>
        ) : (
            <div className="space-y-3">
                {sources.map((source) => {
                    const status = sourceStatus(source);
                    const busy = busySourceId === source.id;
                    return (
                        <article key={source.id} className="rounded-2xl border border-white/[0.08] bg-white/[0.02] p-4">
                            <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                                <div className="min-w-0"><h3 className="truncate text-xs font-semibold text-white">{source.source_name}</h3><p className="mt-1 text-[11px] text-velor-muted">{sourceTypeLabel(source.source_type)} · {source.extracted_char_count ?? 'غير معروف'} حرفًا · {source.chunk_count ?? 'غير معروف'} مقطعًا</p></div>
                                <span className={`w-fit rounded-full border px-2.5 py-1 text-[10px] font-semibold ${toneClasses[status.tone]}`}>{toneLabels[status.tone] || status.label}</span>
                            </div>
                            <dl className="mt-4 grid gap-2 text-[11px] text-velor-secondary sm:grid-cols-2"><div><dt className="text-velor-muted">آخر معالجة</dt><dd className="mt-1">{formatDate(source.last_processed)}</dd></div><div><dt className="text-velor-muted">آخر مزامنة</dt><dd className="mt-1">{formatDate(source.last_synced)}</dd></div></dl>
                            {source.error_category && <p className="mt-3 rounded-lg bg-rose-500/10 p-2 text-[11px] text-rose-100">أبلغ الخادم عن خطأ في معالجة هذا المصدر.</p>}
                            <div className="mt-4 flex flex-wrap gap-2">
                                <button type="button" disabled={busy} onClick={() => onToggle(source)} className="min-h-11 rounded-lg border border-white/10 px-3 py-2 text-[11px] font-semibold text-velor-secondary transition hover:bg-white/[0.06] hover:text-white disabled:opacity-50">{source.active ? 'تعطيل' : 'تفعيل'}</button>
                                <button type="button" disabled={busy} onClick={() => onReprocess(source)} className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-[11px] font-semibold text-velor-secondary transition hover:bg-white/[0.06] hover:text-white disabled:opacity-50"><FiRefreshCw className={busy ? 'animate-spin' : ''} /> إعادة المعالجة</button>
                                <button type="button" disabled={busy} onClick={() => onDelete(source)} className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-rose-400/20 px-3 py-2 text-[11px] font-semibold text-rose-200 transition hover:bg-rose-500/10 disabled:opacity-50"><FiTrash2 /> حذف</button>
                            </div>
                        </article>
                    );
                })}
            </div>
        )}
    </section>
);
