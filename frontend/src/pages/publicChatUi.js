export const MAX_PRODUCT_CARDS = 3;
export const MAX_PRODUCT_ATTRIBUTES = 3;
export const MAX_QUICK_REPLIES = 4;

export const getTextDirection = (value) => (
    /[\u0600-\u06FF]/.test(String(value || '')) ? 'rtl' : 'ltr'
);

const normalizeAction = (action) => {
    if (!action) return null;
    if (typeof action === 'string') return { label: action, message: action };
    const label = String(action.label || action.title || '').trim();
    const message = String(action.message || action.value || action.text || '').trim();
    return label && message ? { label, message } : null;
};

export const getProductActions = (product = {}) => {
    const primary = normalizeAction(product.action || product.primary_action);
    const secondaryCandidate = product.secondary_action
        || (Array.isArray(product.secondary_actions) ? product.secondary_actions[0] : null);
    const productName = String(product.display_name || product.name || '').trim();
    let secondary = normalizeAction(secondaryCandidate) || (productName
        ? { label: 'اعرف التفاصيل', message: `عايز تفاصيل ${productName}` }
        : null);
    if (primary && secondary) {
        const sameLabel = primary.label.localeCompare(secondary.label, undefined, { sensitivity: 'base' }) === 0;
        const sameMessage = primary.message.localeCompare(secondary.message, undefined, { sensitivity: 'base' }) === 0;
        if (sameLabel || sameMessage) secondary = null;
    }
    return { primary, secondary };
};

export const normalizePresentation = (presentation) => {
    if (typeof presentation === 'string') {
        try {
            return normalizePresentation(JSON.parse(presentation));
        } catch {
            return null;
        }
    }
    if (!presentation || typeof presentation !== 'object') return null;

    const productCards = Array.isArray(presentation.product_cards)
        ? presentation.product_cards.slice(0, MAX_PRODUCT_CARDS).map((product) => ({
            ...product,
            attributes: Array.isArray(product?.attributes)
                ? product.attributes.slice(0, MAX_PRODUCT_ATTRIBUTES)
                : [],
        }))
        : [];
    const cardActions = productCards.flatMap((product) => {
        const actions = getProductActions(product);
        return [actions.primary, actions.secondary].filter(Boolean);
    });
    const quickReplies = Array.isArray(presentation.quick_replies)
        ? presentation.quick_replies.filter((reply) => {
            const normalized = normalizeAction(reply);
            if (!normalized) return false;
            return !cardActions.some((action) => (
                action.label.localeCompare(normalized.label, undefined, { sensitivity: 'base' }) === 0
                || action.message.localeCompare(normalized.message, undefined, { sensitivity: 'base' }) === 0
            ));
        }).slice(0, MAX_QUICK_REPLIES)
        : [];

    if (!productCards.length && !quickReplies.length && !presentation.primary_action) return null;
    return {
        ...presentation,
        product_cards: productCards,
        quick_replies: quickReplies,
    };
};

const messageIdentities = (message = {}) => [
    message.id,
    message.internal_id,
    message.internal_message_id,
    message.client_message_id,
    message.wa_message_id ? String(message.wa_message_id).split(':').pop() : null,
].filter((value) => value !== null && value !== undefined && String(value).trim()).map(String);

const presentationFromServer = (message = {}) => normalizePresentation(
    message.presentation || message.response?.presentation || message.response_payload?.presentation || message.response_payload
);

export const mergeConversationMessages = (localMessages = [], serverMessages = []) => {
    const localByIdentity = new Map();
    localMessages.forEach((message) => {
        messageIdentities(message).forEach((identity) => localByIdentity.set(identity, message));
    });

    const serverClientIds = new Set(
        serverMessages.flatMap(messageIdentities)
    );
    const pending = localMessages.filter((message) => (
        (message.status === 'sending' || message.status === 'failed')
        && !messageIdentities(message).some((identity) => serverClientIds.has(identity))
    ));

    const mappedServer = serverMessages.map((message) => {
        const localMatch = messageIdentities(message)
            .map((identity) => localByIdentity.get(identity))
            .find(Boolean);
        return {
            id: message.id,
            internal_id: message.internal_message_id,
            client_message_id: message.client_message_id
                || (message.wa_message_id ? String(message.wa_message_id).split(':').pop() : null),
            message: message.message,
            sender: message.sender,
            direction: message.direction,
            status: message.delivery_status || message.status || localMatch?.status || 'recorded',
            created_at: message.created_at,
            presentation: presentationFromServer(message) || normalizePresentation(localMatch?.presentation),
            responseMeta: message.response_meta || message.meta || message.response?.meta || localMatch?.responseMeta || null,
        };
    });

    return [...mappedServer, ...pending];
};

export const getConversationMode = ({ online, messages = [], isHandoffActive = false }) => {
    if (!online) return { key: 'offline', label: 'لا يوجد اتصال بالإنترنت', tone: 'warning' };
    if (isHandoffActive) return { key: 'handoff', label: 'سيكمل معك أحد أفراد الفريق', tone: 'human' };
    const latestReply = [...messages].reverse().find((message) => message.sender !== 'user');
    if (latestReply?.sender === 'owner') {
        return { key: 'human', label: 'يتابع معك أحد أفراد الفريق', tone: 'human' };
    }
    const meta = latestReply?.responseMeta || {};
    const responsePath = String(meta.response_path || meta.response_mode || '').toUpperCase();
    if (meta.handoff_active || meta.human_takeover) {
        return { key: 'handoff', label: 'سيكمل معك أحد أفراد الفريق', tone: 'human' };
    }
    if (meta.fallback_active || responsePath === 'FALLBACK') {
        return { key: 'fallback', label: 'الإجابة مبنية على المعلومات المتاحة حاليًا', tone: 'neutral' };
    }
    return { key: 'ready', label: 'متاح للمحادثة', tone: 'ready' };
};
