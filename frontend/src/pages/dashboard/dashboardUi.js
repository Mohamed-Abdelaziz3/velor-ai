export const QUEUE_BUCKETS = [
    { key: 'NEEDS_ACTION', label: 'يحتاج إجراء' },
    { key: 'PURCHASE_HANDOFF', label: 'تسليم الشراء' },
    { key: 'FOLLOW_UP', label: 'متابعة متأخرة' },
    { key: 'WAITING_FOR_CUSTOMER', label: 'بانتظار العميل' },
    { key: 'RESOLVED_TODAY', label: 'تمت معالجته اليوم' },
];

export const getQueueCounts = (items = []) => Object.fromEntries(
    QUEUE_BUCKETS.map(({ key }) => [key, items.filter((item) => item.status === key).length])
);

export const getQueueStateContent = (state) => {
    const states = {
        ERROR: {
            title: 'تعذر تحميل قائمة العمل',
            description: 'تحقق من الاتصال ثم أعد المحاولة.',
            tone: 'error',
        },
        NO_ACTION_REQUIRED: {
            title: 'لا توجد إجراءات مطلوبة الآن',
            description: 'لا توجد حالة موثقة تحتاج تدخلًا في الوقت الحالي.',
            tone: 'success',
        },
        STALE: {
            title: 'تحتاج القائمة إلى تحديث',
            description: 'البيانات المعروضة قديمة. أعد التحميل قبل اتخاذ إجراء.',
            tone: 'warning',
        },
        NO_DATA: {
            title: 'لا توجد بيانات كافية بعد',
            description: 'ستظهر الحالات هنا بعد وصول رسائل وأدلة قابلة للمراجعة.',
            tone: 'neutral',
        },
    };
    return states[state] || states.NO_DATA;
};

export const getKnownQueueFacts = (item = {}) => [
    item.current_product ? { label: 'المنتج', value: item.current_product } : null,
    item.budget ? { label: 'الميزانية', value: item.budget } : null,
    item.waiting_duration ? { label: 'مدة الانتظار', value: item.waiting_duration } : null,
    item.channel ? { label: 'القناة', value: item.channel } : null,
].filter(Boolean);

const EVIDENCE_LABELS = {
    product_mention: 'ذكر منتجًا أو خدمة',
    price_question: 'سأل عن السعر',
    objection_price: 'اعترض على السعر',
    buying_signal: 'أظهر نية شراء',
    budget: 'ذكر ميزانية',
    quantity: 'ذكر كمية',
};

export const getQueueEvidenceLabel = (evidence = {}) => {
    const value = String(evidence.label || evidence.type || '').trim();
    return EVIDENCE_LABELS[value] || (/[a-z]+_[a-z_]+/i.test(value) ? 'رسالة موثقة' : value) || 'رسالة موثقة';
};
