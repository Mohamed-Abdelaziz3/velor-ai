const FORBIDDEN_SUMMARY_PATTERNS = [
    /fallback analysis/i,
    /intent score/i,
    /customer message preserved/i,
    /raw model output/i,
    /raw snapshot output/i,
    /decision_json/i,
    /\bsummary\s*:/i,
];

export const INTENT_LABELS = {
    GENERAL_INQUIRY: 'استفسار عام',
    PRODUCT_DISCOVERY: 'اكتشاف منتجات',
    PRODUCT_INFORMATION: 'معلومات عن منتج',
    PRICE_INQUIRY: 'استفسار عن السعر',
    AVAILABILITY_CHECK: 'تحقق من التوفر',
    PRODUCT_COMPARISON: 'مقارنة منتجات',
    RECOMMENDATION_REQUEST: 'طلب توصية',
    BULK_PURCHASE: 'طلب كمية',
    DISCOUNT_INQUIRY: 'استفسار عن خصم',
    NEGOTIATION: 'تفاوض',
    DELIVERY_INQUIRY: 'استفسار عن التوصيل',
    PAYMENT_INQUIRY: 'استفسار عن الدفع',
    PURCHASE_COMMITMENT: 'التزام بالشراء',
    ORDER_NEXT_STEP: 'خطوات الطلب',
    CANCELLATION_OR_REJECTION: 'إلغاء أو رفض',
    PRICE_OBJECTION: 'اعتراض على السعر',
    REACTIVATION: 'إعادة تنشيط',
    SUPPORT_OR_POST_SALE: 'دعم بعد البيع',
};

export const sanitizeMerchantSummary = (value, fallback = 'لا توجد معلومات كافية لتحديد الاهتمام بعد.') => {
    if (typeof value !== 'string') return fallback;
    const text = String(value || '').trim();
    if (!text || FORBIDDEN_SUMMARY_PATTERNS.some((pattern) => pattern.test(text))) return fallback;
    if ((text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']'))) return fallback;
    return text;
};

export const getIntentLabel = (intents) => {
    const values = Array.isArray(intents) ? intents : [];
    const labels = [...new Set(values.map((intent) => INTENT_LABELS[intent]).filter(Boolean))];
    return labels.length ? labels.join('، ') : 'غير محدد بعد';
};

const cleanPhone = (value) => String(value || '').replace(/\D/g, '');

export const getStableCustomerLabel = (lead = {}) => {
    const preferred = String(lead.display_name || lead.name || '').trim();
    const preferredPhone = cleanPhone(preferred);
    if (preferredPhone.length >= 7) return `عميل واتساب ••••${preferredPhone.slice(-4)}`;
    if (preferred && !/[ØÙ�]/.test(preferred) && !['عميل محتمل', 'Unknown', 'غير معروف', 'زائر غير معرّف'].includes(preferred)) return preferred;
    const phone = cleanPhone(lead.phone || lead.whatsapp_number);
    if (phone) return `عميل واتساب ••••${phone.slice(-4)}`;
    return `زائر ${lead.id || 'جديد'}`;
};

export const getAttentionLabel = (lead = {}) => {
    if (lead.needs_human_intervention) return { label: 'يحتاج إجراء', tone: 'danger' };
    const status = String(lead.attention_status || lead.status || '').toLowerCase();
    if (status.includes('risk') || status.includes('خطر')) return { label: 'يحتاج إجراء', tone: 'danger' };
    if (lead.is_paused) return { label: 'متابعة يدوية', tone: 'warning' };
    return { label: 'لا إجراء عاجل', tone: 'neutral' };
};

export const getLatestMeaningfulMessage = (lead = {}) => {
    const value = lead.latest_meaningful_message || lead.latest_message || lead.last_message_preview || lead.last_message;
    return sanitizeMerchantSummary(value, 'لا توجد رسالة حديثة متاحة.');
};
