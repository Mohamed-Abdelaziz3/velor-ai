import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
    buildManualOutboundMessage,
    deriveControlState,
    deriveCustomerBrief,
    getLeadChannelPresentation,
} from '../src/components/workspace/workspaceUx.js';
import {
    canonicalEvidenceRef,
    replacementSuggestionGroup,
    shouldInvalidateSuggestionsForEvent,
    suggestionRegenerationError,
    suggestionRegenerationFeedback,
    suggestionTargetsLatestCustomerTurn,
    suggestionVariants,
} from '../src/components/workspace/workspacePresentation.js';

test('decision brief is a presentation adapter over canonical backend fields', () => {
    const brief = deriveCustomerBrief({
        backendBrief: {
            customer_state: 'Waiting for a factual answer',
            what_customer_wants: 'Confirm whether Ergo One is available',
            latest_signal: 'The latest customer turn asks about availability',
            missing_data: ['quantity'],
            best_next_step: 'Confirm quantity before quoting',
            evidence: [{ label: 'Latest customer turn', message_internal_id: 'msg-9' }],
        },
        currentLead: {
            timeline: [{ message: 'This local message must not become a commercial claim' }],
            owner_intelligence: {
                customer_understanding: {
                    product_interest: ['Ergo One'],
                    budget: '7000 EGP',
                },
                commercial_fit: {
                    known_catalog_matches: [{ name: 'Ergo One', price: 6900, currency: 'EGP' }],
                },
            },
        },
    });

    assert.equal(brief.customer_state, 'Waiting for a factual answer');
    assert.equal(brief.what_customer_wants, 'Confirm whether Ergo One is available');
    assert.equal(brief.best_next_step, 'Confirm quantity before quoting');
    assert.equal(brief.missing_data.length, 1);
    assert.notEqual(brief.missing_data[0], 'quantity');
    assert.ok(brief.known_facts.some((fact) => fact.value === 'Ergo One'));
    assert.ok(brief.known_facts.some((fact) => fact.value === '7000 EGP'));
    assert.equal(JSON.stringify(brief).includes('local message'), false);
});

test('decision brief exposes evidence and uncertainty before action', () => {
    const source = readFileSync(new URL('../src/components/workspace/DecisionBrief.jsx', import.meta.url), 'utf8');
    assert.match(source, /useState\(true\)/);
    assert.match(source, /الأدلة التي بُني عليها القرار/);
    assert.match(source, /تحتاج تدخّلًا بشريًا/);
    assert.match(source, /معلومة ناقصة — راجع قبل الرد/);
});

test('workspace channel truth comes only from the canonical channel_type field', () => {
    assert.deepEqual(getLeadChannelPresentation({ channel_type: 'VELOR_WEB_CHAT', phone: '+201000000000' }), {
        key: 'web_chat',
        label: 'دردشة الموقع',
    });
    assert.equal(getLeadChannelPresentation({ channel_type: 'WHATSAPP_QR' }).key, 'whatsapp');
    assert.equal(getLeadChannelPresentation({ phone: '+201000000000' }).key, 'unknown');
    assert.equal(getLeadChannelPresentation(null).key, 'unknown');

    assert.equal(deriveControlState({
        currentLead: { channel_type: '', phone: '+201000000000' },
        companyAutoReplyEnabled: true,
        whatsAppStatus: { available: true, status: 'connected' },
    }).key, 'channel_unknown');
    assert.equal(deriveControlState({
        currentLead: { channel_type: 'WHATSAPP_QR' },
        companyAutoReplyEnabled: true,
        whatsAppStatus: { available: false, status: 'unknown' },
    }).key, 'whatsapp_status_unknown');
});

test('manual outbound presentation never inserts a string response as a message record', () => {
    const message = buildManualOutboundMessage({
        responseData: { success: true, message: 'Message Sent', internal_message_id: 'msg-owner-7' },
        messageText: 'Actual owner reply',
        clientMessageId: 'client-fallback',
        now: '2026-07-15T01:00:00.000Z',
    });
    assert.equal(typeof message, 'object');
    assert.equal(message.internal_message_id, 'msg-owner-7');
    assert.equal(message.message, 'Actual owner reply');
    assert.equal(message.sender, 'owner');
    assert.equal(message.direction, 'outgoing');
    assert.equal(message.delivery_status, 'pending');
});

test('suggestion variants preserve backend styles and expose at most three active drafts', () => {
    const variants = suggestionVariants([{
        id: 'suggestion-1',
        status: 'suggested',
        stale_status: false,
        answers_message_id: 'msg-3',
        source_message_internal_id: 'internal-msg-3',
        variants: [
            { style: 'natural', text: 'Natural answer', goal: 'answer_in_customer_voice', context_signals: { history_turn_count: 4 } },
            { style: 'concise', text: 'Concise answer' },
            { style: 'commercially_helpful', text: 'Helpful answer' },
            { style: 'extra', text: 'Fourth answer' },
        ],
    }]);

    assert.equal(variants.length, 3);
    assert.deepEqual(variants.map((variant) => variant.style), ['natural', 'concise', 'commercially_helpful']);
    assert.ok(variants.every((variant) => variant.answersMessageId === 'msg-3'));
    assert.ok(variants.every((variant) => variant.label));
    assert.equal(variants[0].sourceMessageInternalId, 'internal-msg-3');
    assert.equal(variants[0].goal, 'answer_in_customer_voice');
    assert.equal(variants[0].contextSignals.history_turn_count, 4);
});

test('stale suggestion visibility is invalidated by customer and owner turns', () => {
    assert.equal(shouldInvalidateSuggestionsForEvent({ type: 'message.received' }), true);
    assert.equal(shouldInvalidateSuggestionsForEvent({ type: 'message.sent' }), true);
    assert.equal(shouldInvalidateSuggestionsForEvent({ text: 'owner reply', sender: 'owner', direction: 'outgoing' }), true);
    assert.equal(shouldInvalidateSuggestionsForEvent({ text: 'VELOR reply', sender: 'assistant', is_ai: true }), false);
    assert.equal(shouldInvalidateSuggestionsForEvent({ type: 'lead.updated', status: 'open' }), false);
});

test('evidence references retain the backend message navigation target', () => {
    assert.deepEqual(canonicalEvidenceRef({
        label: 'Customer asked for the price',
        message_internal_id: 'message-42',
    }), {
        label: 'Customer asked for the price',
        messageId: 'message-42',
    });
});

test('regeneration replaces the visible draft group atomically', () => {
    const replacement = {
        id: 'regenerated-2',
        status: 'suggested',
        stale_status: false,
        source_message_internal_id: 'customer-turn-2',
        variants: [
            { style: 'natural', text: 'New natural draft' },
            { style: 'concise', text: 'New concise draft' },
        ],
    };
    assert.deepEqual(replacementSuggestionGroup(replacement), [replacement]);
    assert.deepEqual(replacementSuggestionGroup({ ...replacement, stale_status: true }), []);
    assert.deepEqual(replacementSuggestionGroup({ ...replacement, variants: [] }), []);
});

test('regenerated drafts must target the latest customer turn', () => {
    const messages = [
        { internal_message_id: 'customer-turn-1', sender: 'customer', direction: 'incoming' },
        { internal_message_id: 'owner-turn-1', sender: 'owner', direction: 'outgoing' },
        { internal_message_id: 'customer-turn-2', sender: 'customer', direction: 'incoming' },
    ];
    assert.equal(suggestionTargetsLatestCustomerTurn({ source_message_internal_id: 'customer-turn-2' }, messages), true);
    assert.equal(suggestionTargetsLatestCustomerTurn({ source_message_internal_id: 'customer-turn-1' }, messages), false);
    assert.equal(suggestionTargetsLatestCustomerTurn(
        { source_message_internal_id: 'customer-turn-2' },
        [...messages, { internal_message_id: 'owner-turn-2', sender: 'owner', direction: 'outgoing' }]
    ), false);
});

test('regeneration feedback distinguishes verified model, safe fallback, and failure', () => {
    assert.equal(suggestionRegenerationFeedback('MODEL').status, 'success');
    assert.equal(suggestionRegenerationFeedback('FALLBACK').status, 'fallback');
    assert.match(suggestionRegenerationFeedback('FALLBACK').message, /مسودة آمنة/);
    assert.match(suggestionRegenerationError(409).message, /لا توجد رسالة/);
    assert.match(suggestionRegenerationError(500).message, /دون تغيير/);
});

test('takeover SSE suggestions remain visible and stale inserted drafts are cleared', () => {
    const contextSource = readFileSync(new URL('../src/context/WorkspaceContext.jsx', import.meta.url), 'utf8');
    const chatSource = readFileSync(new URL('../src/components/workspace/WorkspaceChat.jsx', import.meta.url), 'utf8');

    assert.doesNotMatch(contextSource, /!leadPausedRef\.current\s*&&\s*replacement\.length/);
    assert.match(contextSource, /suggestionTargetsLatestCustomerTurn\(eventData, messagesRef\.current\)/);
    assert.match(contextSource, /suggestionTargetsLatestCustomerTurn\(suggestion, messagesRef\.current\)/);
    assert.match(chatSource, /draftSourceMessageId/);
    assert.match(chatSource, /draftIsFresh/);
    assert.match(chatSource, /suggestionTargetsLatestCustomerTurn\(/);
    assert.match(chatSource, /تم حذف المسودة القديمة/);
    assert.match(chatSource, /const canSend = manualEnabled && !isSending && draftIsFresh/);
    assert.match(chatSource, /sourceMessageInternalId: draftSourceMessageId/);
    assert.match(contextSource, /source_message_internal_id: options\.sourceMessageInternalId/);
});

test('recovery workspace preserves verified send and durable follow-up boundaries', () => {
    const contextSource = readFileSync(new URL('../src/context/WorkspaceContext.jsx', import.meta.url), 'utf8');
    const chatSource = readFileSync(new URL('../src/components/workspace/WorkspaceChat.jsx', import.meta.url), 'utf8');

    assert.match(contextSource, /suggestion_id: options\.suggestionId/);
    assert.match(contextSource, /variant_style: options\.variantStyle/);
    assert.match(contextSource, /suggestion_edited: options\.suggestionEdited/);
    assert.match(contextSource, /owner_action_started/);
    assert.match(contextSource, /completeFollowUp\(taskId\)/);
    assert.match(contextSource, /dismissFollowUp\(taskId\)/);
    assert.match(contextSource, /snoozeFollowUp\(taskId/);
    assert.match(chatSource, /suggestionId: activeVariant\?\.suggestionId/);
    assert.match(chatSource, /recordSuggestionInserted\(suggestion\)/);
    assert.match(chatSource, /المتابعات النشطة/);
    assert.doesNotMatch(chatSource, /updateSuggestedReplyStatus\(activeVariant\.suggestionId, 'used'\)/);
});
