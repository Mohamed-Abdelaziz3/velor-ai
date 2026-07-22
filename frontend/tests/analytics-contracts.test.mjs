import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

import { buildRevenueCockpitPresentation } from '../src/pages/velor/analyticsPresentation.js';

test('legacy commercial-intelligence data becomes an actionable revenue cockpit without sales claims', () => {
    const legacy = {
        window_days: 90,
        data_source: 'deterministic_commercial_events',
        summary: {
            confirmed_orders: null,
            paid_outcomes: null,
            outcome_coverage: { orders: 'not_connected', payments: 'not_connected' },
            outcome_note: 'Order and payment events are not connected.',
        },
        products: [
            {
                product: 'Ergo Pro',
                classification: 'LEAKAGE_CANDIDATE',
                classification_label: 'مرشح لتسرب الطلب',
                interest_conversations: 8,
                progressed_conversations: 1,
                event_counts: { PURCHASE_INTENT_EXPRESSED: 1, PRODUCT_MENTIONED: 8 },
                stage_counts: { PRICE: 5, PURCHASE_INTENT: 1 },
                source_lead_ids: [11],
            },
            {
                product: 'Ergo One',
                classification: 'STRONG_PERFORMER',
                interest_conversations: 6,
                progressed_conversations: 4,
                event_counts: { PRODUCT_MENTIONED: 6 },
                source_lead_ids: [22],
            },
        ],
        insights: [
            {
                id: 'product:leakage:ergo-pro',
                type: 'LEAKAGE_CANDIDATE',
                priority: 90,
                title: 'طلب بلا تقدم: Ergo Pro',
                product: 'Ergo Pro',
                observed: 'ظهر الاهتمام في 8 محادثات والتقدم في محادثة واحدة.',
                unknown: 'سبب التوقف غير مثبت.',
                recommendation: 'راجع عرض القيمة عند سؤال السعر.',
                experiment: 'اختبر شرحًا أقصر للقيمة.',
                measure: 'راقب أدلة التقدم اللاحقة.',
                do_not_conclude: 'لا تعتبر ذلك مبيعات مفقودة.',
                evidence: [{ event_id: 1, lead_id: 11, customer_name: 'سارة', product: 'Ergo Pro', source_text: 'السعر غالي', source_message_internal_id: 'msg-11' }],
            },
            {
                id: 'owner:waiting',
                type: 'OWNER_RESPONSE_LEAKAGE',
                priority: 100,
                title: 'عملاء ينتظرون ردنا',
                observed: 'محادثتان تنتظران تدخل الشركة.',
                unknown: 'لا نعرف أثر الانتظار على الطلب.',
                recommendation: 'راجع الحالتين الآن.',
                experiment: 'حد مراجعة مرتين يوميًا.',
                measure: 'مدة الانتظار.',
                evidence: [
                    { event_id: 2, lead_id: 31, customer_name: 'علي', source_text: 'مستني اللينك' },
                    { event_id: 3, lead_id: 32, customer_name: 'نور', source_text: 'هل متاح؟' },
                ],
            },
            {
                id: 'knowledge:warranty',
                type: 'KNOWLEDGE_GAP',
                priority: 85,
                title: 'معلومة ضمان ناقصة',
                observed: 'تكرر سؤال الضمان.',
                unknown: 'أثره على قرار الشراء غير معروف.',
                recommendation: 'أضف سياسة ضمان موثقة.',
                experiment: 'أضفها لأسبوع.',
                measure: 'عدد التصعيدات اللاحقة.',
                evidence: [{ event_id: 4, lead_id: 41, customer_name: 'محمود', source_text: 'الضمان كام؟' }],
            },
        ],
    };

    const presentation = buildRevenueCockpitPresentation(legacy, { days: 30, channel: 'all' });
    const metrics = Object.fromEntries(presentation.metrics.map((metric) => [metric.key, metric]));

    assert.equal(metrics.demand_without_progress.value, 7);
    assert.equal(metrics.demand_without_progress.subject, 'Ergo Pro');
    assert.equal(metrics.purchase_intent.value, 1);
    assert.equal(metrics.waiting_on_us.value, 2);
    assert.equal(metrics.knowledge_gaps.value, 1);
    assert.equal(presentation.products[0].classification, 'LEAKAGE_CANDIDATE');
    assert.equal(presentation.products[0].recommendedAction, 'راجع عرض القيمة عند سؤال السعر.');
    assert.ok(presentation.opportunities.some((item) => item.leadId === 11));
    assert.ok(presentation.opportunities.every((item) => item.leadId !== null));
    assert.equal(presentation.filters.days, 90);
    assert.equal(presentation.filters.windowMismatch, true);
    assert.equal(presentation.coverage.orders.value, null);
    assert.equal(presentation.coverage.payments.value, null);
    assert.match(presentation.executiveBrief.headline, /محادثتان|الاهتمام/);
});

test('expanded cockpit contract takes precedence and preserves explicit unknown values', () => {
    const expanded = {
        filters: { days: 7, channel: 'whatsapp' },
        summary: {
            actionable: {
                demand_without_progress: { count: 4, product: 'Ergo Pro', detail: '4 محادثات اهتمام لم تسجل تقدمًا.' },
                purchase_intent_conversations: { count: 3, detail: '3 محادثات بنية صريحة.' },
                waiting_on_us_conversations: 2,
                currently_unavailable_demand_conversations: null,
            },
            confirmed_orders: null,
            paid_outcomes: null,
            outcome_coverage: { orders: 'not_connected', payments: 'not_connected' },
        },
        executive_brief: {
            headline: 'ابدأ بحالات الانتظار قبل مراجعة تسرب Ergo Pro.',
            context: 'حالتان تنتظران رد الشركة.',
            recommended_action: 'افتح أول حالة وأكمل الخطوة الناقصة.',
            lead_id: 70,
        },
        opportunity_queue: {
            items: [{
                id: 'ready-70',
                lead_id: 70,
                customer_name: 'هدى',
                status: 'PURCHASE_HANDOFF',
                status_label: 'جاهز للخطوة التالية',
                reason: 'طلب رابط إتمام الخطوة.',
                recommended_action: 'أرسل الرابط الموثق.',
                score: 95,
            }],
        },
        products: [{
            product: 'Ergo Pro',
            interest_conversations: 9,
            progressed_conversations: 5,
            demand_without_progress: 4,
            classification: 'LEAKAGE_CANDIDATE',
            top_objections: [{ label: 'السعر', count: 3 }],
            recommended_action: 'اختبر شرح القيمة.',
            source_lead_ids: [70],
        }],
        daily_trend: {
            demand_without_progress: Array.from({ length: 8 }, (_, index) => ({ date: `2026-07-${String(index + 1).padStart(2, '0')}`, count: index + 1 })),
        },
        insights: [],
    };

    const presentation = buildRevenueCockpitPresentation(expanded, { days: 7, channel: 'whatsapp' });
    const metrics = Object.fromEntries(presentation.metrics.map((metric) => [metric.key, metric]));

    assert.equal(metrics.demand_without_progress.value, 4);
    assert.equal(metrics.purchase_intent.value, 3);
    assert.equal(metrics.waiting_on_us.value, 2);
    assert.equal(metrics.currently_unavailable_demand.value, null);
    assert.equal(presentation.opportunities[0].leadId, 70);
    assert.equal(presentation.executiveBrief.leadId, 70);
    assert.equal(presentation.filters.windowMismatch, false);
    assert.equal(presentation.trend.values.length, 8);
    assert.deepEqual(presentation.trend.values, [1, 2, 3, 4, 5, 6, 7, 8]);
    assert.equal(presentation.trend.label, 'الطلب بلا تقدم');
    assert.deepEqual(presentation.products[0].friction, ['السعر · 3']);
});

test('short trend series is hidden so the cockpit does not render a decorative line', () => {
    const presentation = buildRevenueCockpitPresentation({
        trend: { demand: Array.from({ length: 7 }, (_, index) => ({ label: `${index + 1}`, value: index })) },
    }, { days: 7, channel: 'all' });

    assert.equal(presentation.trend, null);
});

test('the fourth decision metric prefers an evidenced knowledge gap over zero unavailable demand', () => {
    const presentation = buildRevenueCockpitPresentation({
        summary: {
            current_unavailable_demand: 0,
            knowledge_gap: 3,
        },
        opportunity_queue: [{
            id: 'intent-1',
            lead_id: 91,
            reason: 'العميل طلب تنفيذ الخطوة التالية.',
            recommended_action: 'راجع الطلب وأرسل الخطوة الموثقة.',
            priority: 90,
        }],
    }, { days: 30, channel: 'all' });

    assert.equal(presentation.metrics[3].key, 'knowledge_gaps');
    assert.equal(presentation.metrics[3].value, 3);
    assert.equal(presentation.executiveBrief.leadId, 91);
    assert.match(presentation.executiveBrief.action, /الخطوة الموثقة/);
});

test('an explicitly empty canonical opportunity queue stays empty instead of reviving historical insight evidence', () => {
    const historicalInsight = {
        id: 'historical-leakage',
        type: 'LEAKAGE_CANDIDATE',
        priority: 90,
        title: 'نمط تاريخي',
        evidence: [{ lead_id: 77, source_text: 'دليل تاريخي تمت معالجته' }],
    };

    const canonical = buildRevenueCockpitPresentation({
        opportunity_queue: [],
        insights: [historicalInsight],
    });
    const legacy = buildRevenueCockpitPresentation({ insights: [historicalInsight] });

    assert.deepEqual(canonical.opportunities, []);
    assert.equal(legacy.opportunities[0].leadId, 77);
});

test('backend unavailable-demand and friction contracts are rendered without aliases or data loss', () => {
    const presentation = buildRevenueCockpitPresentation({
        summary: {
            current_unavailable_demand: 4,
            knowledge_gap: 0,
        },
        opportunity_queue: [],
        products: [{
            product: 'Out Chair',
            demand_conversations: 5,
            progressed_conversations: 1,
            classification: 'LEAKAGE_CANDIDATE',
            friction_counts: {
                objection: 3,
                stalled: 2,
                knowledge_gap: 0,
                unavailable_request: 1,
            },
        }],
    });

    assert.equal(presentation.metrics[3].key, 'currently_unavailable_demand');
    assert.equal(presentation.metrics[3].value, 4);
    assert.deepEqual(
        presentation.products[0].friction,
        ['اعتراضات · 3', 'محادثات متوقفة · 2', 'طلبات غير متاحة · 1']
    );
});

test('analytics client sends real filters and keeps cancellation wired through axios', () => {
    const apiSource = readFileSync(new URL('../src/services/api.js', import.meta.url), 'utf8');
    const analyticsSource = readFileSync(new URL('../src/pages/velor/Analytics.jsx', import.meta.url), 'utf8');

    assert.match(apiSource, /getBusinessInsights = \(\{ days, channel, signal \} = \{\}\)/);
    assert.match(apiSource, /params\.days = days/);
    assert.match(apiSource, /params\.channel = channel/);
    assert.match(apiSource, /\{ params, signal \}/);
    assert.match(analyticsSource, /new AbortController\(\)/);
    assert.match(analyticsSource, /requestId !== requestRef\.current/);
    assert.match(analyticsSource, /getBusinessInsights\(\{ days: Number\(range\), channel, signal: controller\.signal \}\)/);
    assert.doesNotMatch(analyticsSource, /UnavailableMetric|الإيراد المنسوب للذكاء الاصطناعي/);
});

test('analytics renders measured recovery impact while financial outcomes stay unavailable', () => {
    const apiSource = readFileSync(new URL('../src/services/api.js', import.meta.url), 'utf8');
    const analyticsSource = readFileSync(new URL('../src/pages/velor/Analytics.jsx', import.meta.url), 'utf8');
    const dashboardSource = readFileSync(new URL('../src/pages/velor/Dashboard.jsx', import.meta.url), 'utf8');

    assert.match(apiSource, /\/api\/v1\/operations\/recovery-impact/);
    assert.match(apiSource, /\/api\/v1\/operations\/telemetry/);
    assert.match(analyticsSource, /getRecoveryImpact\(\{ days: Number\(range\), channel, signal: controller\.signal \}\)/);
    assert.match(analyticsSource, /opportunity_shown/);
    assert.match(analyticsSource, /opportunity_opened/);
    assert.match(analyticsSource, /افتح المحادثة والدليل/);
    assert.match(analyticsSource, /\.finally\(openWorkspace\)/);
    assert.match(analyticsSource, /النتائج المالية: غير متصلة/);
    assert.match(analyticsSource, /ارتباط زمني، وليس إثبات سببية/);
    assert.match(dashboardSource, /opportunity_shown/);
    assert.match(dashboardSource, /opportunity_opened/);
});
