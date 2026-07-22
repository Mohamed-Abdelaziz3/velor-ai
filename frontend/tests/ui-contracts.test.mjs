import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { resolveRuntimeApiBase } from '../src/services/apiBase.js';
import {
    getConversationMode,
    getProductActions,
    MAX_PRODUCT_ATTRIBUTES,
    MAX_PRODUCT_CARDS,
    MAX_QUICK_REPLIES,
    mergeConversationMessages,
    normalizePresentation,
} from '../src/pages/publicChatUi.js';
import { getKnownQueueFacts, getQueueCounts, getQueueEvidenceLabel, getQueueStateContent, QUEUE_BUCKETS } from '../src/pages/dashboard/dashboardUi.js';
import {
    getAttentionLabel,
    getIntentLabel,
    getLatestMeaningfulMessage,
    getStableCustomerLabel,
    sanitizeMerchantSummary,
} from '../src/pages/dashboard/customerListUi.js';
import {
    formatRelativeTime,
    groupMessagesByDate,
    normalizeApiTimestamp,
    parseApiTimestamp,
} from '../src/utils/timeUtils.js';

test('API base prefers explicit configuration and otherwise stays on the current origin', () => {
    assert.equal(resolveRuntimeApiBase('https://api.example.com///', { origin: 'https://app.example.com' }), 'https://api.example.com');
    assert.equal(resolveRuntimeApiBase('', { origin: 'https://app.example.com' }), 'https://app.example.com');
    assert.equal(resolveRuntimeApiBase('', { origin: 'null', protocol: 'https:', host: 'app.example.com' }), 'https://app.example.com');
    assert.equal(resolveRuntimeApiBase('', null), '');
});

test('Public Chat presentation enforces progressive-disclosure limits', () => {
    const presentation = normalizePresentation({
        product_cards: Array.from({ length: 6 }, (_, index) => ({
            id: index,
            display_name: `Product ${index}`,
            attributes: ['one', 'two', 'three', 'four'],
        })),
        quick_replies: Array.from({ length: 8 }, (_, index) => ({ label: `Q${index}`, message: `M${index}` })),
    });
    assert.equal(presentation.product_cards.length, MAX_PRODUCT_CARDS);
    assert.equal(presentation.product_cards[0].attributes.length, MAX_PRODUCT_ATTRIBUTES);
    assert.equal(presentation.quick_replies.length, MAX_QUICK_REPLIES);
    assert.equal(normalizePresentation(JSON.stringify({ product_cards: [{ display_name: 'Persisted' }] })).product_cards[0].display_name, 'Persisted');

    const deduplicated = normalizePresentation({
        product_cards: [{ display_name: 'Ergo One', primary_action: { label: 'اعرف التفاصيل', message: 'عايز تفاصيل Ergo One' } }],
        quick_replies: [
            { label: 'اعرف التفاصيل', message: 'عايز تفاصيل Ergo One' },
            { label: 'قارن', message: 'قارن Ergo One' },
        ],
    });
    assert.deepEqual(deduplicated.quick_replies, [{ label: 'قارن', message: 'قارن Ergo One' }]);
});

test('Product cards always have a safe details action when a product name exists', () => {
    const actions = getProductActions({
        display_name: 'Arvena Ergo One',
        action: { label: 'اختيار', message: 'اختار Arvena Ergo One' },
    });
    assert.deepEqual(actions.primary, { label: 'اختيار', message: 'اختار Arvena Ergo One' });
    assert.deepEqual(actions.secondary, { label: 'اعرف التفاصيل', message: 'عايز تفاصيل Arvena Ergo One' });

    const duplicate = getProductActions({
        display_name: 'Arvena Ergo One',
        primary_action: { label: 'اعرف التفاصيل', message: 'عايز تفاصيل Arvena Ergo One' },
    });
    assert.equal(duplicate.secondary, null);
});

test('Session merging retains local presentation and prefers persisted server presentation', () => {
    const local = [{ id: 10, message: 'reply', sender: 'assistant', presentation: { product_cards: [{ display_name: 'Local' }] } }];
    const retained = mergeConversationMessages(local, [{ id: 10, message: 'reply', sender: 'assistant' }]);
    assert.equal(retained[0].presentation.product_cards[0].display_name, 'Local');

    const persisted = mergeConversationMessages(local, [{
        id: 10,
        message: 'reply',
        sender: 'assistant',
        delivery_status: 'delivered',
        presentation: { product_cards: [{ display_name: 'Server' }] },
    }]);
    assert.equal(persisted[0].presentation.product_cards[0].display_name, 'Server');
    assert.equal(persisted[0].status, 'delivered');
});

test('Public Chat exposes customer-safe degraded and human modes', () => {
    assert.equal(getConversationMode({ online: false }).key, 'offline');
    const fallback = getConversationMode({ online: true, messages: [{ sender: 'assistant', responseMeta: { response_path: 'FALLBACK', provider: 'secret-provider' } }] });
    assert.equal(fallback.key, 'fallback');
    assert.equal(fallback.label.includes('provider'), false);
    assert.equal(getConversationMode({ online: true, messages: [{ sender: 'owner' }] }).key, 'human');
});

test('Commercial Queue exposes five operational buckets and honest state copy', () => {
    assert.deepEqual(QUEUE_BUCKETS.map((bucket) => bucket.key), [
        'NEEDS_ACTION',
        'PURCHASE_HANDOFF',
        'FOLLOW_UP',
        'WAITING_FOR_CUSTOMER',
        'RESOLVED_TODAY',
    ]);
    const counts = getQueueCounts([{ status: 'NEEDS_ACTION' }, { status: 'NEEDS_ACTION' }, { status: 'PURCHASE_HANDOFF' }]);
    assert.equal(counts.NEEDS_ACTION, 2);
    assert.equal(counts.PURCHASE_HANDOFF, 1);
    assert.equal(counts.RESOLVED_TODAY, 0);
    assert.equal(getQueueStateContent('STALE').tone, 'warning');
});

test('Queue facts omit unknown values instead of displaying zero or placeholders', () => {
    assert.deepEqual(getKnownQueueFacts({ current_product: 'Ergo One', budget: null, waiting_duration: 'منذ ساعة' }), [
        { label: 'المنتج', value: 'Ergo One' },
        { label: 'مدة الانتظار', value: 'منذ ساعة' },
    ]);
    assert.equal(getQueueEvidenceLabel({ label: 'product_mention' }), 'ذكر منتجًا أو خدمة');
    assert.equal(getQueueEvidenceLabel({ label: 'internal_unknown_code' }), 'رسالة موثقة');
});

test('Customer presentation blocks diagnostic prose and unknown enums', () => {
    const fallback = 'لا توجد معلومات كافية لتحديد الاهتمام بعد.';
    assert.equal(sanitizeMerchantSummary('Summary: Fallback analysis: customer message preserved. Intent score 75'), fallback);
    assert.equal(sanitizeMerchantSummary('{"decision_json":true}'), fallback);
    assert.equal(sanitizeMerchantSummary('العميل يسأل عن كرسي مكتب.'), 'العميل يسأل عن كرسي مكتب.');
    assert.equal(getIntentLabel(['PRICE_INQUIRY', 'INTERNAL_UNKNOWN']), 'استفسار عن السعر');
    assert.equal(getIntentLabel(['INTERNAL_UNKNOWN']), 'غير محدد بعد');
});

test('Customer labels are stable and privacy-safe', () => {
    assert.equal(getStableCustomerLabel({ id: 28, name: 'عميل محتمل' }), 'زائر 28');
    assert.equal(getStableCustomerLabel({ id: 2, phone: '+201234567890', name: 'Unknown' }), 'عميل واتساب ••••7890');
    assert.equal(getStableCustomerLabel({ id: 2, display_name: '+201234567890' }), 'عميل واتساب ••••7890');
    assert.equal(getStableCustomerLabel({ id: 3, display_name: 'سارة' }), 'سارة');
});

test('Customer attention and latest-message helpers remain plain-language and sanitized', () => {
    assert.deepEqual(getAttentionLabel({ needs_human_intervention: true }), { label: 'يحتاج إجراء', tone: 'danger' });
    assert.equal(getLatestMeaningfulMessage({ latest_message: 'Fallback analysis: raw model output' }), 'لا توجد رسالة حديثة متاحة.');
    assert.equal(getLatestMeaningfulMessage({ latest_message: 'عايز أعرف السعر' }), 'عايز أعرف السعر');
});

test('API timestamps without offsets are treated as UTC and retain millisecond precision', () => {
    assert.equal(normalizeApiTimestamp('2026-07-14 18:38:56.444615'), '2026-07-14T18:38:56.444Z');
    assert.equal(parseApiTimestamp('2026-07-14 18:38:56.444615').toISOString(), '2026-07-14T18:38:56.444Z');
    assert.equal(parseApiTimestamp('2026-07-14T18:38:56+03:00').toISOString(), '2026-07-14T15:38:56.000Z');
});

test('Relative conversation time uses hours and days instead of an unbounded minute count', () => {
    const now = Date.parse('2026-07-14T23:15:00Z');
    assert.equal(formatRelativeTime('2026-07-14 18:38:56.444615', { now }), '5 hours ago');
    assert.equal(formatRelativeTime('2026-07-12T23:15:00Z', { now }), '2 days ago');
});

test('Message grouping preserves persisted local calendar boundaries and unknown dates', () => {
    const groups = groupMessagesByDate([
        { id: 1, timestamp: '2026-07-12T00:00:00Z' },
        { id: 2, timestamp: '2026-07-12T00:05:00Z' },
        { id: 3, timestamp: '2026-07-15T00:00:00Z' },
        { id: 4 },
    ]);
    assert.deepEqual(groups.map((group) => group.items.map((item) => item.id)), [[1, 2], [3], [4]]);
    assert.equal(groups.at(-1).key, 'unknown');
});

test('Truth UI contracts prevent optimistic stream, identity, and intent presentation', () => {
    const eventsSource = readFileSync(new URL('../src/contexts/GlobalEventContext.jsx', import.meta.url), 'utf8');
    const sidebarSource = readFileSync(new URL('../src/components/Sidebar.jsx', import.meta.url), 'utf8');
    const inboxSource = readFileSync(new URL('../src/pages/velor/Inbox.jsx', import.meta.url), 'utf8');
    const dashboardSource = readFileSync(new URL('../src/pages/velor/Dashboard.jsx', import.meta.url), 'utf8');

    assert.match(eventsSource, /connectionState/);
    assert.match(eventsSource, /connectedAt/);
    assert.match(eventsSource, /lastEventAt/);
    assert.match(eventsSource, /setConnectionState\('reconnecting'\)/);
    assert.match(eventsSource, /setConnectionState\('disconnected'\)/);

    assert.match(sidebarSource, /useGlobalEvents\(\)/);
    assert.doesNotMatch(sidebarSource, /AI is active|Watching every connected sales conversation|>Live<\/Badge>/);

    assert.match(inboxSource, /lead\.contact_identifier/);
    assert.match(inboxSource, /if \(!conversation\.contactIdentifier\)/);
    assert.match(inboxSource, /groupMessagesByDate\(messages\)/);
    assert.match(inboxSource, /DeliveryStatus/);
    assert.match(inboxSource, /navigate\(`\/inbox\/\$\{selected\.id\}`\)/);
    assert.match(inboxSource, /هذه معاينة للقراءة فقط/);
    assert.match(inboxSource, /dir="rtl" lang="ar"/);
    assert.doesNotMatch(inboxSource, /RingGauge|label="intent"|conversation\.unread|selected\.online|`\/customers\/\$\{|sendMessage|toggleTakeover|<textarea|routeConversationId/);

    assert.match(dashboardSource, /getGreeting\(\)/);
    assert.match(dashboardSource, /connectionState/);
    assert.match(dashboardSource, /`\/inbox\/\$\{item\.leadId\}`/);
    assert.doesNotMatch(dashboardSource, /SegmentedControl|const \[range|Daily confirmed outcomes|Observing/);
});

test('merchant dashboard and billing surfaces are Arabic-first RTL and never synthesize business data', () => {
    const dashboardSource = readFileSync(new URL('../src/pages/velor/Dashboard.jsx', import.meta.url), 'utf8');
    const billingSource = readFileSync(new URL('../src/pages/velor/Billing.jsx', import.meta.url), 'utf8');

    assert.match(dashboardSource, /dir="rtl" lang="ar"/);
    assert.match(dashboardSource, /نسب الإيراد متوقّف عمدًا/);
    assert.match(dashboardSource, /مش إجمالي طلبات أو مدفوعات مؤكدة/);
    assert.doesNotMatch(dashboardSource, /velorPreviewData|isPreviewMode|previewStats|previewActions|previewTrend|previewHeatmap/);
    assert.doesNotMatch(dashboardSource, /Sales intelligence overview|Priority queue unavailable|AI-attributed sales|Good morning/);

    assert.match(billingSource, /dir="rtl" lang="ar"/);
    assert.match(billingSource, /الدفع غير متصل/);
    assert.match(billingSource, /الاستخدام الحي غير متاح/);
    assert.match(billingSource, /الفواتير غير متاحة/);
    assert.doesNotMatch(billingSource, /velorPreviewData|isPreviewMode|previewInvoices|معاينة فوترة تجريبية/);
    assert.doesNotMatch(billingSource, /Plan and usage|Checkout not connected|Synthetic billing preview|Current plan/);
});

test('secondary workspace surfaces fail closed when their sources are unavailable', () => {
    const layoutSource = readFileSync(new URL('../src/components/Layout.jsx', import.meta.url), 'utf8');
    const analyticsSource = readFileSync(new URL('../src/pages/velor/Analytics.jsx', import.meta.url), 'utf8');
    const automationSource = readFileSync(new URL('../src/pages/velor/AutomationBuilder.jsx', import.meta.url), 'utf8');
    const workspaceSource = readFileSync(new URL('../src/context/WorkspaceContext.jsx', import.meta.url), 'utf8');
    const workspaceChatSource = readFileSync(new URL('../src/components/workspace/WorkspaceChat.jsx', import.meta.url), 'utf8');
    const sidebarSource = readFileSync(new URL('../src/components/Sidebar.jsx', import.meta.url), 'utf8');
    const onboardingSource = readFileSync(new URL('../src/pages/velor/Onboarding.jsx', import.meta.url), 'utf8');
    const apiSource = readFileSync(new URL('../src/services/api.js', import.meta.url), 'utf8');

    assert.doesNotMatch(layoutSource, /No unread items|Nothing to show yet/);
    assert.match(layoutSource, /المصدر غير متصل/);
    assert.doesNotMatch(layoutSource, /\/preview|Preview dataset|Search or jump to|Protected workspace/);

    assert.doesNotMatch(analyticsSource, /Source linked/);
    assert.match(analyticsSource, /intelligenceError[\s\S]*المصدر غير متاح/);
    assert.match(analyticsSource, /trustedOutcome && !isNumber\(value\)/);

    assert.doesNotMatch(automationSource, /Live configuration|>Validated</);
    assert.match(automationSource, /settingsAvailable/);
    assert.match(automationSource, /الإعدادات غير متاحة/);
    assert.match(automationSource, /api\.get\('\/api\/company\/bot\/auto-reply'\)/);

    assert.match(workspaceSource, /post\(`\/api\/leads\/\$\{currentLead\.id\}\/human-takeover\/toggle`/);
    assert.doesNotMatch(workspaceSource, /api\/v1\/crm\/customers\/\$\{currentLead\.id\}\/toggle-ai/);
    assert.match(workspaceSource, /retryWorkspace/);
    assert.match(workspaceChatSource, /formatClockTime/);

    assert.match(sidebarSource, /activePath\.startsWith\('\/inbox\/'\)/);
    assert.match(sidebarSource, /مركز المتابعة/);
    assert.doesNotMatch(sidebarSource, /Command Center|Conversations|AI Behavior|Setup & channels|Current plan|Sign out/);
    assert.match(onboardingSource, /setWhatsapp\(\{ status: 'unknown', qrCode: '', reason: 'تعذر التحقق من حالة القناة\.'/);

    assert.match(apiSource, /OWNER_API_TIMEOUT_MS = 15_000/);
    assert.match(apiSource, /PUBLIC_CHAT_TIMEOUT_MS = 25_000/);
    assert.match(apiSource, /timeout: OWNER_API_TIMEOUT_MS/);
    assert.match(apiSource, /timeout: PUBLIC_CHAT_TIMEOUT_MS/);
});
