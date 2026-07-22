export const EMPTY = 'لا توجد بيانات كافية بعد.';
export const NO_SIGNALS = 'لا توجد إشارات كافية من المحادثة بعد.';

const INTERNAL_LABELS = {
    price_question: 'سأل عن السعر',
    product_mention: 'ذكر منتجًا أو خدمة',
    objection_price: 'اعترض على السعر',
    hesitation: 'يحتاج طمأنة قبل القرار',
    urgency: 'طلب ردًا سريعًا',
    start_intent: 'سأل عن طريقة البدء',
    buying_signal: 'أظهر نية شراء',
    quantity: 'الكمية',
    budget: 'الميزانية',
    price: 'السعر',
    currency: 'العملة',
    product: 'المنتج أو الخدمة',
    latest_customer_message: 'آخر رسالة من العميل',
};

export const validValue = (value) => {
    if (value === null || value === undefined) return '';
    if (typeof value === 'string' && ['', 'N/A', 'null', 'undefined'].includes(value.trim())) return '';
    return value;
};

export const isInternalKey = (value) => {
    const text = String(value || '').trim();
    return Boolean(text && (/^[a-z]+(?:_[a-z0-9]+)+$/i.test(text) || /internal|confidence|source_|metadata|lead_/i.test(text)));
};

export const isMojibakeLike = (value) => /[�]|[ØÙÐÑÃÂ]/.test(String(value || ''));

export const safeText = (value, fallback = EMPTY) => {
    if (value === null || value === undefined) return fallback;
    if (Array.isArray(value)) {
        const rendered = value.map((item) => safeText(item, '')).filter(Boolean);
        return rendered.length ? rendered.join('، ') : fallback;
    }
    if (typeof value === 'object') {
        return safeText(value.label || value.summary || value.value || value.normalized_value || value.source_text || value.text || value.message, fallback);
    }
    if (typeof value === 'number') return Number.isFinite(value) ? String(value) : fallback;
    if (typeof value !== 'string') return fallback;
    const text = value.trim();
    if (!text || ['N/A', 'null', 'undefined'].includes(text)) return fallback;
    if ((text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']'))) return fallback;
    if (isMojibakeLike(text)) return fallback;
    if (INTERNAL_LABELS[text]) return INTERNAL_LABELS[text];
    if (isInternalKey(text)) return fallback;
    return text;
};

export const getMessageOwner = (message = {}) => {
    const sender = String(message.sender || '').toLowerCase();
    const direction = String(message.direction || '').toLowerCase();
    if (sender === 'system' || sender === 'internal') return 'system';
    if (direction === 'incoming' || sender === 'user' || sender === 'customer') return 'customer';
    if (message.is_ai || ['assistant', 'bot', 'velor'].includes(sender)) return 'velor';
    if (direction === 'outgoing' || ['owner', 'agent', 'human', 'manual'].includes(sender)) return 'human';
    return 'system';
};

const WEB_CHAT_CHANNELS = new Set(['VELOR_WEB_CHAT', 'WEB_CHAT', 'HOSTED_WEB_CHAT']);
const WHATSAPP_CHANNELS = new Set(['WHATSAPP_QR', 'WHATSAPP', 'WHATSAPP_CLOUD']);

export const getLeadChannelPresentation = (lead = {}) => {
    const channelType = String(lead?.channel_type || '').trim().toUpperCase();
    if (WEB_CHAT_CHANNELS.has(channelType)) return { key: 'web_chat', label: 'دردشة الموقع' };
    if (WHATSAPP_CHANNELS.has(channelType)) return { key: 'whatsapp', label: 'واتساب' };
    return { key: 'unknown', label: 'قناة غير معروفة' };
};

export const buildManualOutboundMessage = ({ responseData = {}, messageText = '', clientMessageId, now } = {}) => {
    const serverMessage = responseData?.message && typeof responseData.message === 'object'
        ? responseData.message
        : {};
    const internalMessageId = serverMessage.internal_message_id
        || responseData.internal_message_id
        || responseData.message_id
        || clientMessageId;

    return {
        ...serverMessage,
        internal_message_id: internalMessageId ? String(internalMessageId) : null,
        type: 'message',
        sender: 'owner',
        direction: 'outgoing',
        source: serverMessage.source || 'workspace_manual',
        is_ai: false,
        message: String(serverMessage.message || messageText || '').trim(),
        delivery_status: serverMessage.delivery_status || responseData.delivery_status || 'pending',
        status: serverMessage.status || responseData.delivery_status || 'pending',
        timestamp: serverMessage.timestamp || responseData.timestamp || now || new Date().toISOString(),
    };
};

export const cleanPhone = (value) => {
    const cleaned = String(value || '').replace(/[^\d+]/g, '');
    return cleaned.replace(/\D/g, '').length >= 7 ? cleaned : '';
};

export const getCleanCustomerDisplay = (currentLead = {}, identity = {}) => {
    const phone = cleanPhone(currentLead.customer_provided_phone || currentLead.display_phone || currentLead.phone || currentLead.whatsapp_number || currentLead.whatsapp_jid);
    const rawName = validValue(currentLead.display_name) || validValue(identity.name) || validValue(currentLead.name);
    const safeName = rawName && !isMojibakeLike(rawName) && !['عميل محتمل', 'Unknown', 'غير معروف'].includes(String(rawName).trim()) ? safeText(rawName, '') : '';
    return {
        displayName: safeName || (currentLead.id ? `زائر ${currentLead.id}` : 'العميل'),
        contactValue: phone,
        usedPhoneFallback: false,
    };
};

export const evidenceLabel = (item) => {
    const type = typeof item === 'string' ? item : item?.type || item?.evidence_type || item?.label;
    return INTERNAL_LABELS[type] || (isInternalKey(type) ? 'دليل من المحادثة' : safeText(type, 'دليل من المحادثة'));
};

export const evidenceSummary = (item) => {
    if (!item) return NO_SIGNALS;
    const label = evidenceLabel(item);
    const source = safeText(item.source_text || item.normalized_value || item.value, '');
    return source ? `${label}: ${source}` : label;
};

const compact = (values, limit = 6) => {
    const source = Array.isArray(values) ? values : (values ? [values] : []);
    return [...new Set(source.map((value) => safeText(value, '')).filter(Boolean))].slice(0, limit);
};

const canonicalKnownFacts = (backendBrief = {}, currentLead = {}) => {
    const owner = currentLead.owner_intelligence || {};
    const understanding = owner.customer_understanding || {};
    const fit = owner.commercial_fit || {};
    const explicit = Array.isArray(backendBrief.known_facts) ? backendBrief.known_facts : [];
    const facts = [...explicit];
    compact(understanding.product_interest, 3).forEach((value) => facts.push({ label: 'المنتج', value }));
    if (validValue(understanding.budget)) facts.push({ label: 'الميزانية', value: understanding.budget });
    (fit.known_catalog_matches || []).slice(0, 3).forEach((product) => {
        if (!product?.name) return;
        const price = product.price !== null && product.price !== undefined ? `${product.price} ${product.currency || ''}`.trim() : '';
        facts.push({ label: 'مطابقة الكتالوج', value: price ? `${product.name} · ${price}` : product.name });
    });
    return facts
        .map((fact) => ({ label: safeText(fact.label, 'معلومة موثقة'), value: safeText(fact.value, '') }))
        .filter((fact) => fact.value)
        .filter((fact, index, rows) => rows.findIndex((candidate) => candidate.label === fact.label && candidate.value === fact.value) === index)
        .slice(0, 6);
};

// Presentation adapter only: every commercial statement originates from the
// backend customer_brief/owner_intelligence contracts. Message regexes and
// local intent inference intentionally do not participate.
export const deriveCustomerBrief = ({ backendBrief = {}, currentLead = {} } = {}) => {
    const evidence = Array.isArray(backendBrief.evidence) ? backendBrief.evidence : [];
    const missing = compact(backendBrief.missing_data, 8);
    const importantSignals = compact(backendBrief.important_signals || backendBrief.evidence_summary, 6);
    return {
        what_customer_wants: safeText(backendBrief.what_customer_wants, EMPTY),
        customer_state: safeText(backendBrief.customer_state, EMPTY),
        business_meaning: safeText(backendBrief.business_meaning, EMPTY),
        latest_signal: safeText(backendBrief.latest_signal, EMPTY),
        missing_data: missing,
        known_facts: canonicalKnownFacts(backendBrief, currentLead),
        best_next_step: safeText(backendBrief.best_next_step, EMPTY),
        suggested_reply: safeText(backendBrief.suggested_reply, ''),
        expected_next: safeText(backendBrief.expected_next, EMPTY),
        human_takeover: Boolean(backendBrief.human_takeover),
        latest_message_sender: backendBrief.latest_message_sender || null,
        important_signals: importantSignals,
        evidence,
        insufficient_data: Boolean(backendBrief.insufficient_data),
    };
};

export const deriveNextBestMove = ({ brief }) => safeText(brief?.best_next_step, '');

export const deriveControlState = ({ currentLead, companyAutoReplyEnabled, whatsAppStatus }) => {
    const rawStatus = String(whatsAppStatus?.status || whatsAppStatus?.state || '').toLowerCase();
    const statusKnown = Boolean(whatsAppStatus?.available && rawStatus);
    const isConnected = ['connected', 'open', 'ready'].includes(rawStatus);
    const isDisconnected = statusKnown && !isConnected && !['checking', 'loading'].includes(rawStatus);
    const channel = getLeadChannelPresentation(currentLead);
    if (channel.key === 'unknown') return { key: 'channel_unknown', manualEnabled: false, velorActive: false, tone: 'danger', label: 'قناة المحادثة غير معروفة', message: 'تعذّر التحقق من قناة هذه المحادثة، لذلك تم إيقاف الإرسال.', cta: null };
    if (channel.key === 'whatsapp' && !statusKnown) return { key: 'whatsapp_status_unknown', manualEnabled: false, velorActive: false, tone: 'danger', label: 'حالة واتساب غير متاحة', message: 'تعذّر التحقق من اتصال واتساب، لذلك تم إيقاف الإرسال مؤقتًا.', cta: null };
    if (companyAutoReplyEnabled !== true && companyAutoReplyEnabled !== false) return { key: 'auto_reply_status_unknown', manualEnabled: false, velorActive: false, tone: 'danger', label: 'حالة الرد التلقائي غير متاحة', message: 'تعذّر التحقق من إعداد الرد التلقائي، لذلك لا يتم افتراض أن VELOR نشط.', cta: null };
    const isWebChat = channel.key === 'web_chat';
    if (isDisconnected && !isWebChat) return { key: 'whatsapp_disconnected', manualEnabled: false, velorActive: false, tone: 'danger', label: 'واتساب غير متصل', message: 'وصّل جلسة واتساب قبل إرسال الرسائل.', cta: null };
    if (companyAutoReplyEnabled === false) return { key: 'company_auto_reply_off', manualEnabled: true, velorActive: false, tone: 'human', label: 'الرد التلقائي متوقف', message: 'يمكنك الرد يدويًا لأن الرد التلقائي متوقف للشركة.', cta: null };
    if (currentLead?.is_paused) return { key: 'human_takeover', manualEnabled: true, velorActive: false, tone: 'human', label: 'المحادثة اليدوية', message: 'أنت تدير المحادثة يدويًا. VELOR يقترح فقط ولا يرسل تلقائيًا.', cta: 'إعادة VELOR للمحادثة' };
    return { key: 'velor_active', manualEnabled: false, velorActive: true, tone: 'velor', label: 'VELOR يدير المحادثة', message: 'لإرسال رد يدوي، تولَّ المحادثة أولًا.', cta: 'تولّي المحادثة' };
};
