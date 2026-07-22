import { FiAlertTriangle, FiCheckCircle, FiPlus, FiRefreshCw, FiTrash2, FiUploadCloud } from 'react-icons/fi';

const inputClass = 'min-h-11 w-full rounded-xl border border-white/[0.09] bg-[#0b0d15] px-3 py-2 text-sm text-white outline-none placeholder:text-velor-muted focus:border-velor-purple/70 focus:ring-2 focus:ring-velor-purple/10';

export const CatalogEditor = ({
    products,
    validation,
    onAdd,
    onRemove,
    onChange,
    onImportSelect,
    onImportCommit,
    importPreview,
    importError,
    importing,
    committing,
    importDisabled = false,
}) => (
    <section className="space-y-5" aria-labelledby="catalog-heading" dir="rtl" lang="ar">
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
            <div>
                <h2 id="catalog-heading" className="text-base font-semibold text-white">كتالوج المنتجات والخدمات</h2>
                <p className="mt-1 max-w-3xl text-xs leading-5 text-velor-muted">السجلات المحفوظة هنا هي المصدر الموثوق للأسماء والأسعار التي يستخدمها VELOR. يحتاج السجل النشط اسمًا وفئة وسعرًا غير سالب وعملة.</p>
            </div>
            <button type="button" onClick={onAdd} className="inline-flex min-h-11 w-fit items-center gap-2 rounded-xl bg-velor-purple px-4 py-2 text-xs font-semibold text-white transition hover:bg-velor-purple-hi"><FiPlus /> إضافة منتج</button>
        </div>

        <div className="rounded-2xl border border-velor-purple/20 bg-velor-purple/[0.045] p-4">
            <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
                <div>
                    <h3 className="inline-flex items-center gap-2 text-xs font-semibold text-white"><FiUploadCloud /> استيراد كتالوج منظّم</h3>
                    <p className="mt-1 max-w-2xl text-[11px] leading-5 text-velor-muted">ارفع ملف CSV أو XLSX للتحقق منه أولًا. لن يتم حفظ شيء حتى توافق على المعاينة.</p>
                </div>
                <label className={`inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-xl border border-white/10 px-4 text-xs font-semibold text-velor-secondary transition hover:bg-white/[0.05] hover:text-white ${(importing || committing || importDisabled) ? 'pointer-events-none opacity-45' : ''}`}>
                    {importing ? <FiRefreshCw className="animate-spin" /> : <FiUploadCloud />}
                    {importing ? 'جاري التحقق من الملف…' : 'اختر CSV أو XLSX'}
                    <input type="file" className="sr-only" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" disabled={importing || committing || importDisabled} onChange={onImportSelect} />
                </label>
            </div>
            {importDisabled && <p className="mt-3 text-[11px] text-velor-muted">احفظ التعديلات اليدوية أو تجاهلها قبل الاستيراد حتى لا يدمج الخادم الملف مع إصدار أقدم من الكتالوج.</p>}
            {importError && <p className="mt-3 rounded-xl border border-rose-400/20 bg-rose-500/10 p-3 text-xs leading-5 text-rose-100" role="alert">{importError}</p>}
            {importPreview && <div className="mt-4 space-y-3" aria-live="polite">
                <div className="flex flex-wrap gap-2 text-[11px]">
                    <span className="rounded-full border border-white/10 bg-black/15 px-3 py-1.5 text-velor-secondary">الملف: <bdi dir="auto">{importPreview.fileName}</bdi></span>
                    <span className="rounded-full border border-white/10 bg-black/15 px-3 py-1.5 text-velor-secondary">الصفوف المقروءة: {importPreview.stats?.total_rows ?? importPreview.records?.length ?? 0}</span>
                    <span className="rounded-full border border-white/10 bg-black/15 px-3 py-1.5 text-velor-secondary">السجلات الصالحة: {importPreview.stats?.valid_records ?? importPreview.records?.length ?? 0}</span>
                    {importPreview.truncated && <span className="rounded-full border border-velor-amber/20 bg-velor-amber/10 px-3 py-1.5 text-[#f9d28a]">المعاينة محدودة إلى 200 صف</span>}
                </div>
                {(importPreview.issues || []).length > 0 && <div className="max-h-40 overflow-y-auto rounded-xl border border-velor-amber/20 bg-velor-amber/10 p-3 text-[11px] leading-5 text-[#f9d28a]">
                    <p className="font-semibold">نتائج التحقق</p>
                    <ul className="mt-1 list-inside list-disc">{importPreview.issues.slice(0, 12).map((issue, index) => <li key={`${issue.code || 'issue'}-${issue.row || index}`}>{issue.row ? `الصف ${issue.row}: ` : ''}{issue.message || 'سجل كتالوج غير صالح'}</li>)}</ul>
                    {importPreview.issues.length > 12 && <p className="mt-1 text-velor-muted">هناك {importPreview.issues.length - 12} ملاحظات إضافية غير معروضة هنا.</p>}
                </div>}
                {importPreview.canCommit ? <button type="button" onClick={onImportCommit} disabled={committing} className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-velor-purple px-4 text-xs font-semibold text-white disabled:opacity-50">
                    {committing ? <FiRefreshCw className="animate-spin" /> : <FiCheckCircle />}
                    {committing ? 'جاري حفظ الكتالوج…' : 'حفظ السجلات الصالحة'}
                </button> : <p className="text-xs font-semibold text-[#f9d28a]">أصلح الأخطاء المانعة في الملف ثم ارفعه مرة أخرى.</p>}
            </div>}
        </div>

        <div className="flex flex-wrap gap-2 text-[11px]">
            <span className="rounded-full border border-white/10 bg-white/[0.035] px-3 py-1.5 text-velor-secondary">سجلات قابلة للتعديل: {products.length}</span>
            <span className="rounded-full border border-velor-green/20 bg-velor-green/10 px-3 py-1.5 text-[#9df1d1]">نشط وصالح: {validation.activeValidCount}</span>
            {validation.duplicateIds.length > 0 && <span className="inline-flex items-center gap-1 rounded-full border border-velor-amber/20 bg-velor-amber/10 px-3 py-1.5 text-[#f9d28a]"><FiAlertTriangle /> {validation.duplicateIds.length} صفوف مكررة</span>}
        </div>

        {!products.length ? (
            <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.02] p-7 text-center">
                <p className="text-sm font-semibold text-white">لا توجد سجلات كتالوج محفوظة في المحرر.</p>
                <p className="mt-1 text-xs text-velor-muted">أضف منتجًا يدويًا أو استورد ملف CSV أو XLSX.</p>
            </div>
        ) : <div className="space-y-3">
            {products.map((product, index) => {
                const errors = validation.errorsById[product.id] || [];
                return (
                    <article key={product.id} className={`rounded-2xl border p-4 ${errors.length ? 'border-velor-amber/25 bg-velor-amber/[0.035]' : 'border-white/[0.08] bg-white/[0.02]'}`}>
                        <div className="mb-4 flex items-center justify-between gap-3">
                            <h3 className="text-xs font-semibold text-white">السجل {index + 1}</h3>
                            <div className="flex items-center gap-2">
                                <button type="button" role="switch" aria-checked={product.active} onClick={() => onChange(product.id, 'active', !product.active)} className={`relative h-7 w-12 rounded-full border transition-colors ${product.active ? 'border-velor-green/30 bg-velor-green' : 'border-white/10 bg-white/10'}`} aria-label={`${product.active ? 'تعطيل' : 'تفعيل'} ${product.name || `السجل ${index + 1}`}`}>
                                    <span className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-transform ${product.active ? 'right-6' : 'right-1'}`} />
                                </button>
                                <button type="button" onClick={() => onRemove(product.id)} className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 text-velor-muted transition hover:border-rose-400/30 hover:bg-rose-500/10 hover:text-rose-200" aria-label={`حذف ${product.name || `السجل ${index + 1}`}`}><FiTrash2 /></button>
                            </div>
                        </div>
                        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-12">
                            <label className="space-y-1 lg:col-span-4"><span className="text-[11px] font-semibold text-velor-secondary">الاسم</span><input className={inputClass} value={product.name} onChange={(event) => onChange(product.id, 'name', event.target.value)} placeholder="مثال: كرسي إرجو وان" /></label>
                            <label className="space-y-1 lg:col-span-3"><span className="text-[11px] font-semibold text-velor-secondary">الفئة</span><input className={inputClass} value={product.category} onChange={(event) => onChange(product.id, 'category', event.target.value)} placeholder="مثال: كراسي مكتب" /></label>
                            <label className="space-y-1 lg:col-span-3"><span className="text-[11px] font-semibold text-velor-secondary">السعر</span><input className={inputClass} inputMode="decimal" dir="ltr" value={product.price} onChange={(event) => onChange(product.id, 'price', event.target.value)} placeholder="6900" /></label>
                            <label className="space-y-1 lg:col-span-2"><span className="text-[11px] font-semibold text-velor-secondary">العملة</span><select className={inputClass} dir="ltr" value={product.currency} onChange={(event) => onChange(product.id, 'currency', event.target.value)}><option value="EGP">ج.م</option><option value="USD">USD</option><option value="EUR">EUR</option></select></label>
                            <label className="space-y-1 sm:col-span-2 lg:col-span-12"><span className="text-[11px] font-semibold text-velor-secondary">وصف موثوق</span><textarea className={`${inputClass} min-h-20 resize-y`} value={product.description} onChange={(event) => onChange(product.id, 'description', event.target.value)} placeholder="أضف فقط المواصفات أو المزايا التي تستطيع التحقق منها." /></label>
                        </div>
                        {errors.length > 0 && <ul className="mt-3 list-inside list-disc text-[11px] leading-5 text-[#f9d28a]" aria-live="polite">{errors.map((error) => <li key={error}>{error}</li>)}</ul>}
                    </article>
                );
            })}
        </div>}
    </section>
);
