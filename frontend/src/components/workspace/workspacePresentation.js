import { getMessageOwner, safeText } from './workspaceUx.js';

const STYLE_LABELS = {
    natural: 'طبيعي',
    concise: 'مختصر',
    commercially_helpful: 'مساعد تجاريًا',
    commercial: 'مساعد تجاريًا',
};

export const suggestionVariants = (suggestions = []) => suggestions
    .filter((suggestion) => suggestion.status === 'suggested' && !suggestion.stale_status)
    .flatMap((suggestion) => {
        const variants = Array.isArray(suggestion.variants) && suggestion.variants.length
            ? suggestion.variants
            : [{ style: suggestion.style || 'natural', text: suggestion.suggested_reply }];
        return variants.map((variant, index) => ({
            id: `${suggestion.id}:${variant.style || index}`,
            suggestionId: suggestion.id,
            style: variant.style || suggestion.style || 'natural',
            label: safeText(variant.label, STYLE_LABELS[variant.style || suggestion.style] || 'رد مقترح'),
            text: safeText(variant.text || variant.suggested_reply, ''),
            reason: safeText(suggestion.why_this_reply, ''),
            answersMessageId: suggestion.answers_message_id || suggestion.source_message_id,
            sourceMessageInternalId: suggestion.source_message_internal_id || null,
            generatedAt: suggestion.generated_at || suggestion.created_at,
            goal: variant.goal || null,
            contextSignals: variant.context_signals || null,
        })).filter((variant) => variant.text);
    })
    .slice(0, 3);

export const replacementSuggestionGroup = (suggestion) => {
    if (!suggestion || suggestion.status !== 'suggested' || suggestion.stale_status) return [];
    return suggestionVariants([suggestion]).length ? [suggestion] : [];
};

export const suggestionTargetsLatestCustomerTurn = (suggestion = {}, messages = []) => {
    const latestConversationMessage = [...messages].reverse().find((message) => getMessageOwner(message) !== 'system');
    if (!latestConversationMessage || getMessageOwner(latestConversationMessage) !== 'customer') return false;
    const suggestionIds = [
        suggestion.source_message_internal_id,
        suggestion.answers_message_id,
        suggestion.source_message_id,
    ].filter((value) => value !== null && value !== undefined).map(String);
    const messageIds = [latestConversationMessage.internal_message_id, latestConversationMessage.id]
        .filter((value) => value !== null && value !== undefined).map(String);
    return suggestionIds.some((id) => messageIds.includes(id));
};

export const suggestionRegenerationFeedback = (responsePath) => {
    const normalizedPath = String(responsePath || '').toUpperCase();
    if (normalizedPath === 'FALLBACK') {
        return {
            status: 'fallback',
            responsePath: 'FALLBACK',
            message: 'تم إنشاء مسودة آمنة من الحقائق الموثقة لأن خدمة الصياغة المتقدمة غير متاحة الآن.',
        };
    }
    return {
        status: 'success',
        responsePath: normalizedPath || 'MODEL',
        message: 'تم إنشاء صيغ جديدة مرتبطة بآخر رسالة من العميل.',
    };
};

export const suggestionRegenerationError = (httpStatus) => ({
    status: 'error',
    responsePath: null,
    message: Number(httpStatus) === 409
        ? 'لا توجد رسالة حالية من العميل يمكن إنشاء رد موثوق لها.'
        : 'تعذر إنشاء صيغ جديدة الآن. بقيت المسودات الحالية دون تغيير.',
});

export const shouldInvalidateSuggestionsForEvent = (event = {}) => {
    if (event.type === 'lead.updated' || event.type === 'canonical_commercial.updated') return false;
    if (event.type === 'message.received') return true;
    if (event.type === 'message.sent') return true;
    const owner = getMessageOwner({ sender: event.sender, direction: event.direction, is_ai: event.is_ai });
    return Boolean(event.text && (owner === 'customer' || owner === 'human'));
};

export const canonicalEvidenceRef = (item = {}) => ({
    label: safeText(item.label || item.type || item.evidence_type, 'دليل من المحادثة'),
    messageId: item.message_internal_id || item.message_id || item.source_message_internal_id || null,
});
