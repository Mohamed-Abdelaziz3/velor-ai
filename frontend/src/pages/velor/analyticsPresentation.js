const CLASSIFICATION_LABELS = {
  STRONG_PERFORMER: 'أداء قوي',
  LEAKAGE_CANDIDATE: 'طلب بلا تقدم',
  HIDDEN_WINNER: 'فرصة خفية',
  LOW_SIGNAL: 'إشارة محدودة',
  INSUFFICIENT_EVIDENCE: 'دليل غير كافٍ',
};

const CLASSIFICATION_TONES = {
  STRONG_PERFORMER: 'green',
  LEAKAGE_CANDIDATE: 'red',
  HIDDEN_WINNER: 'purple',
  LOW_SIGNAL: 'blue',
  INSUFFICIENT_EVIDENCE: 'neutral',
};

const METRIC_KEYS = {
  demandWithoutProgress: ['demand_without_progress', 'demand_without_progress_count', 'leakage_conversations'],
  purchaseIntent: ['purchase_intent', 'purchase_intent_count', 'purchase_intent_conversations', 'purchase_ready_count'],
  waitingOnUs: ['waiting_on_us', 'waiting_on_us_count', 'waiting_on_us_conversations', 'owner_response_waiting'],
  unavailableDemand: ['current_unavailable_demand', 'currently_unavailable_demand', 'currently_unavailable_demand_count', 'currently_unavailable_demand_conversations', 'unavailable_demand', 'unavailable_demand_count'],
  knowledgeGaps: ['knowledge_gap', 'knowledge_gaps', 'knowledge_gap_count', 'knowledge_gaps_count', 'knowledge_gap_conversations'],
};

const PURCHASE_EVENT_TYPES = [
  'PURCHASE_INTENT_EXPRESSED',
  'PURCHASE_COMMITMENT',
  'PURCHASE_EXECUTION_REQUEST',
];

const STATUS_LABELS = {
  NEEDS_ACTION: 'يحتاج إجراء',
  PURCHASE_HANDOFF: 'جاهز للخطوة التالية',
  FOLLOW_UP: 'متابعة',
  WAITING_ON_US: 'ينتظر ردنا',
  WAITING_FOR_CUSTOMER: 'بانتظار العميل',
  READY_TO_CLOSE: 'جاهز للخطوة التالية',
  STUCK_ON_OBJECTION: 'اعتراض يوقف التقدم',
  REGRESSING: 'يحتاج استعادة الزخم',
};

const TREND_LABELS = {
  demand_without_progress: 'الطلب بلا تقدم',
  purchase_intent: 'إشارات نية الشراء',
  waiting_on_us: 'محادثات تنتظر ردنا',
  demand: 'محادثات الاهتمام',
};

const FRICTION_LABELS = {
  objection: 'اعتراضات',
  stalled: 'محادثات متوقفة',
  knowledge_gap: 'فجوات معرفة',
  waiting_on_us: 'انتظار ردنا',
  unavailable_request: 'طلبات غير متاحة',
};

const isObject = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const asObject = (value) => (isObject(value) ? value : {});
const asArray = (value) => (Array.isArray(value) ? value : []);

const safeText = (...values) => {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
};

const finiteNumber = (...values) => {
  for (const value of values) {
    if (value === null || value === undefined || value === '') continue;
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return null;
};

const firstDefinedField = (roots, keys) => {
  for (const root of roots) {
    if (!isObject(root)) continue;
    for (const key of keys) {
      if (Object.prototype.hasOwnProperty.call(root, key)) {
        return { found: true, value: root[key] };
      }
    }
  }
  return { found: false, value: undefined };
};

const metricContract = (rawValue, fallback = {}) => {
  if (isObject(rawValue)) {
    return {
      value: finiteNumber(rawValue.value, rawValue.count, rawValue.conversations, rawValue.total),
      detail: safeText(rawValue.detail, rawValue.description, rawValue.reason, fallback.detail),
      subject: safeText(rawValue.product, rawValue.subject, rawValue.label, fallback.subject),
      leadId: rawValue.lead_id ?? rawValue.leadId ?? fallback.leadId ?? null,
    };
  }
  return {
    value: finiteNumber(rawValue),
    detail: safeText(fallback.detail),
    subject: safeText(fallback.subject),
    leadId: fallback.leadId ?? null,
  };
};

const normalizeEvidence = (item = {}) => ({
  id: item.event_id ?? item.id ?? null,
  leadId: item.lead_id ?? item.leadId ?? item.customer_id ?? null,
  customerName: safeText(item.customer_name, item.customerName, item.lead_name, item.display_label, item.name, 'محادثة عميل'),
  product: safeText(item.product, item.product_ref),
  sourceText: safeText(item.source_text, item.sourceText, item.latest_message, item.message, 'دليل موثّق من المحادثة.'),
  sourceMessageId: item.source_message_internal_id ?? item.sourceMessageId ?? item.source_message_id ?? item.message_internal_id ?? null,
  observedAt: item.observed_at ?? item.observedAt ?? item.created_at ?? null,
  type: safeText(item.event_type, item.type),
});

const normalizeInsight = (item = {}, index = 0) => ({
  id: item.id ?? `insight-${index}`,
  type: safeText(item.type, 'COMMERCIAL_SIGNAL'),
  priority: finiteNumber(item.priority) ?? 0,
  title: safeText(item.title, 'إشارة تجارية قابلة للمراجعة'),
  product: safeText(item.product, item.product_ref),
  observed: safeText(item.observed, item.observation, item.description),
  hypothesis: safeText(item.hypothesis),
  unknown: safeText(item.unknown, item.uncertainty),
  recommendation: safeText(item.recommendation, item.recommended_action, item.what_next),
  experiment: safeText(item.experiment, item.next_experiment),
  measure: safeText(item.measure, item.success_measure),
  doNotConclude: safeText(item.do_not_conclude, item.caveat),
  evidence: asArray(item.evidence).map(normalizeEvidence),
});

const listLabels = (value) => {
  if (Array.isArray(value)) {
    return value.map((item) => {
      if (typeof item === 'string') return item.trim();
      if (!isObject(item)) return '';
      const label = safeText(item.label, item.objection, item.reason, item.name, item.type);
      const count = finiteNumber(item.count, item.frequency, item.conversations);
      return label ? `${label}${count === null ? '' : ` · ${count}`}` : '';
    }).filter(Boolean);
  }
  if (isObject(value)) {
    return Object.entries(value)
      .map(([label, count]) => ({ label, count: finiteNumber(count) }))
      .sort((a, b) => (b.count ?? 0) - (a.count ?? 0))
      .map(({ label, count }) => `${label}${count === null ? '' : ` · ${count}`}`);
  }
  return safeText(value) ? [safeText(value)] : [];
};

const mostObservedStage = (stageCounts) => {
  const stages = Object.entries(asObject(stageCounts))
    .map(([stage, count]) => ({ stage, count: finiteNumber(count) }))
    .filter((item) => item.count !== null)
    .sort((a, b) => b.count - a.count);
  if (!stages.length) return '';
  return `أكثر مرحلة مرصودة: ${stages[0].stage} · ${stages[0].count}`;
};

const normalizeProducts = (payload, insights) => {
  const productRows = asArray(
    payload.products
      ?? asObject(payload.demand).products
      ?? payload.product_demand
      ?? payload.demand_products
  );

  return productRows.map((item, index) => {
    const product = safeText(item.product, item.product_name, item.name, `منتج ${index + 1}`);
    const interest = finiteNumber(
      item.interest_conversations,
      item.demand_conversations,
      item.requested_conversations,
      item.request_count,
      item.total_requests
    );
    const progressed = finiteNumber(
      item.progressed_conversations,
      item.progress_conversations,
      item.progressed,
      item.progress_count
    );
    const explicitGap = finiteNumber(item.demand_without_progress, item.gap, item.progression_gap);
    const gap = explicitGap ?? (interest !== null && progressed !== null ? Math.max(interest - progressed, 0) : null);
    const classification = safeText(item.classification, item.status, 'INSUFFICIENT_EVIDENCE').toUpperCase();
    const matchedInsight = insights.find(
      (insight) => insight.product && insight.product.toLocaleLowerCase() === product.toLocaleLowerCase()
    );
    const objections = listLabels(item.top_objections ?? item.objections ?? item.objection_counts);
    const stalls = listLabels(item.stall_reasons ?? item.stalls ?? item.blockers ?? item.top_stall);
    const frictionCounts = Object.entries(asObject(item.friction_counts))
      .map(([key, count]) => ({ label: FRICTION_LABELS[key] || key, count: finiteNumber(count) }))
      .filter((entry) => entry.count !== null && entry.count > 0)
      .sort((a, b) => b.count - a.count)
      .map(({ label, count }) => `${label} · ${count}`);
    const observedStage = mostObservedStage(item.stage_counts);
    const friction = [...new Set([
      ...objections,
      ...stalls,
      ...frictionCounts,
      ...(observedStage ? [observedStage] : []),
    ])].slice(0, 3);
    const evidence = asArray(item.evidence).map(normalizeEvidence);
    const sourceLeadIds = asArray(item.source_lead_ids).filter((value) => value !== null && value !== undefined);
    const leadId = item.lead_id
      ?? evidence.find((entry) => entry.leadId)?.leadId
      ?? matchedInsight?.evidence.find((entry) => entry.leadId)?.leadId
      ?? sourceLeadIds[0]
      ?? null;

    return {
      id: item.id ?? product,
      product,
      interest,
      progressed,
      gap,
      classification,
      classificationLabel: safeText(item.classification_label, CLASSIFICATION_LABELS[classification], classification),
      tone: CLASSIFICATION_TONES[classification] || 'neutral',
      friction,
      recommendedAction: safeText(
        item.recommended_action,
        item.recommendation,
        matchedInsight?.recommendation,
        'راجع المحادثات الداعمة قبل تغيير العرض.'
      ),
      leadId,
      eventCounts: asObject(item.event_counts),
      stageCounts: asObject(item.stage_counts),
      evidence: evidence.length ? evidence : matchedInsight?.evidence || [],
      uncertainty: safeText(item.uncertainty),
    };
  }).sort((a, b) => {
    const classPriority = { LEAKAGE_CANDIDATE: 0, HIDDEN_WINNER: 1, STRONG_PERFORMER: 2, LOW_SIGNAL: 3, INSUFFICIENT_EVIDENCE: 4 };
    return (classPriority[a.classification] ?? 5) - (classPriority[b.classification] ?? 5)
      || (b.gap ?? -1) - (a.gap ?? -1)
      || (b.interest ?? -1) - (a.interest ?? -1);
  });
};

const normalizeOpportunity = (item = {}, index = 0) => {
  const evidence = asArray(item.evidence).map(normalizeEvidence);
  const status = safeText(item.status, item.projection_class, item.priority_category, 'NEEDS_ACTION').toUpperCase();
  return {
    id: item.id ?? `opportunity-${index}`,
    queueItemId: item.queue_item_id ?? item.id ?? null,
    leadId: item.lead_id ?? item.customer_id ?? evidence.find((entry) => entry.leadId)?.leadId ?? null,
    customerName: safeText(item.customer_name, item.lead_name, item.display_label, item.name, 'محادثة عميل'),
    product: safeText(item.product, item.current_product, item.product_ref),
    title: safeText(item.title, item.what, item.reason, item.status_label, STATUS_LABELS[status], 'فرصة تحتاج مراجعة'),
    reason: safeText(item.observed, item.description, item.reason, item.why, item.latest_message),
    action: safeText(item.recommended_action, item.recommendation, item.what_next, item.suggested_action, 'افتح المحادثة وراجع الدليل.'),
    waitingDuration: safeText(item.waiting_duration, asObject(item.freshness).label),
    status,
    statusLabel: safeText(item.status_label, STATUS_LABELS[status], 'يحتاج مراجعة'),
    priority: finiteNumber(item.priority, item.score) ?? 0,
    sourceMessageId: item.source_message_internal_id ?? item.source_message_id ?? evidence[0]?.sourceMessageId ?? null,
    evidence,
  };
};

const opportunitiesFromInsights = (insights) => {
  const rows = [];
  for (const insight of [...insights].sort((a, b) => b.priority - a.priority)) {
    for (const evidence of insight.evidence) {
      if (!evidence.leadId) continue;
      rows.push(normalizeOpportunity({
        id: `${insight.id}:${evidence.leadId}`,
        lead_id: evidence.leadId,
        customer_name: evidence.customerName,
        product: evidence.product || insight.product,
        title: insight.title,
        observed: insight.observed || evidence.sourceText,
        recommended_action: insight.recommendation,
        priority: insight.priority,
        source_message_internal_id: evidence.sourceMessageId,
        evidence: [evidence],
        status: insight.type === 'OWNER_RESPONSE_LEAKAGE' ? 'WAITING_ON_US' : 'NEEDS_ACTION',
      }, rows.length));
    }
  }
  return rows;
};

const normalizeOpportunities = (payload, insights) => {
  const queueKey = ['opportunity_queue', 'opportunities', 'action_queue']
    .find((key) => Object.prototype.hasOwnProperty.call(payload, key));
  const queue = queueKey ? payload[queueKey] : undefined;
  const queueRows = Array.isArray(queue)
    ? queue
    : asArray(asObject(queue).items ?? asObject(queue).opportunities);
  // An explicitly empty canonical queue means "nothing actionable now".  Only
  // legacy payloads that omit the queue contract may fall back to insight evidence.
  const source = queueKey
    ? queueRows.map(normalizeOpportunity)
    : opportunitiesFromInsights(insights);
  const seen = new Set();
  return source
    .filter((item) => item.leadId !== null && item.leadId !== undefined)
    .sort((a, b) => b.priority - a.priority)
    .filter((item) => {
      const key = String(item.leadId);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 8);
};

const countUniqueEvidenceLeads = (insights) => {
  const ids = new Set();
  for (const insight of insights) {
    for (const evidence of insight.evidence) {
      if (evidence.leadId !== null && evidence.leadId !== undefined) ids.add(String(evidence.leadId));
    }
  }
  return ids.size || null;
};

const purchaseIntentFallback = (products) => {
  let hasEventCounts = false;
  let count = 0;
  for (const product of products) {
    if (Object.keys(product.eventCounts).length) hasEventCounts = true;
    for (const type of PURCHASE_EVENT_TYPES) {
      count += finiteNumber(product.eventCounts[type]) ?? 0;
    }
  }
  return hasEventCounts ? count : null;
};

const normalizeMetric = ({ roots, keys, fallback }) => {
  const field = firstDefinedField(roots, keys);
  return field.found ? metricContract(field.value, fallback) : metricContract(fallback.value, fallback);
};

const normalizeExecutiveBrief = (payload, insights, opportunities) => {
  const raw = payload.executive_brief ?? payload.executive_summary ?? payload.brief;
  if (typeof raw === 'string' && raw.trim()) {
    return { headline: raw.trim(), context: '', action: '', leadId: opportunities[0]?.leadId ?? null };
  }
  if (isObject(raw)) {
    return {
      headline: safeText(raw.headline, raw.title, raw.answer, raw.summary, raw.decision),
      context: safeText(raw.context, raw.observed, raw.why, raw.detail),
      action: safeText(raw.recommended_action, raw.recommendation, raw.next_action, raw.what_next),
      leadId: raw.lead_id ?? opportunities[0]?.leadId ?? null,
    };
  }
  const topInsight = [...insights].sort((a, b) => b.priority - a.priority)[0];
  if (topInsight) {
    return {
      headline: safeText(topInsight.observed, topInsight.title),
      context: safeText(topInsight.unknown, topInsight.hypothesis),
      action: topInsight.recommendation,
      leadId: topInsight.evidence.find((item) => item.leadId)?.leadId ?? opportunities[0]?.leadId ?? null,
    };
  }
  const topOpportunity = opportunities[0];
  if (topOpportunity) {
    return {
      headline: safeText(topOpportunity.title, topOpportunity.reason),
      context: safeText(topOpportunity.reason, topOpportunity.product),
      action: topOpportunity.action,
      leadId: topOpportunity.leadId,
    };
  }
  return {
    headline: 'لا توجد إشارة تنفيذية مدعومة كفاية في هذه النافذة.',
    context: 'سيظهر القرار الأهم عندما تسجل المحادثات أدلة طلب أو اعتراض أو انتظار قابلًا للمراجعة.',
    action: '',
    leadId: null,
  };
};

const pointValue = (point, preferredKey = null) => {
  if (typeof point === 'number') return Number.isFinite(point) ? point : null;
  if (preferredKey && isObject(point) && Object.prototype.hasOwnProperty.call(point, preferredKey)) {
    return finiteNumber(point[preferredKey]);
  }
  return finiteNumber(
    point?.value,
    point?.count,
    point?.conversations,
    point?.demand,
    point?.interest_conversations
  );
};

const normalizeTrendSeries = (rawSeries, fallbackLabel = 'حركة الإشارات التجارية', parent = {}, preferredKey = null) => {
  const series = asObject(rawSeries);
  const rawPoints = Array.isArray(rawSeries)
    ? rawSeries
    : asArray(series.points ?? series.data ?? series.values);
  const parentLabels = asArray(series.labels ?? parent.labels);
  const points = rawPoints.map((point, index) => ({
    value: pointValue(point, preferredKey),
    label: typeof point === 'number'
      ? safeText(parentLabels[index], `${index + 1}`)
      : safeText(point?.label, point?.date, point?.period, point?.bucket, parentLabels[index], `${index + 1}`),
  })).filter((point) => point.value !== null);
  // Short daily series read like decoration rather than a reliable trend.
  // Keep the cockpit focused on the demand board and action queue.
  if (points.length < 8) return null;
  return {
    label: safeText(series.label, series.title, series.name, fallbackLabel),
    values: points.map((point) => point.value),
    labels: points.map((point) => point.label),
  };
};

const normalizeTrend = (payload) => {
  const trend = payload.trend ?? payload.daily_trend;
  if (!trend) return null;
  if (Array.isArray(trend)) {
    const sample = trend.find(isObject);
    const preferredKey = ['demand_without_progress', 'purchase_intent', 'waiting_on_us', 'demand_conversations']
      .find((key) => sample && Object.prototype.hasOwnProperty.call(sample, key));
    const label = preferredKey === 'demand_conversations'
      ? 'محادثات الطلب'
      : TREND_LABELS[preferredKey] || 'حركة الإشارات التجارية';
    return normalizeTrendSeries(trend, label, {}, preferredKey);
  }
  const trendObject = asObject(trend);
  const explicitSeries = asArray(trendObject.series);
  for (const series of explicitSeries) {
    const normalized = normalizeTrendSeries(series, 'حركة الإشارات التجارية', trendObject);
    if (normalized) return normalized;
  }
  const direct = normalizeTrendSeries(trendObject, safeText(trendObject.label, trendObject.title, 'حركة الإشارات التجارية'), trendObject);
  if (direct) return direct;
  for (const key of ['demand_without_progress', 'purchase_intent', 'waiting_on_us', 'demand']) {
    if (!trendObject[key]) continue;
    const normalized = normalizeTrendSeries(trendObject[key], TREND_LABELS[key], trendObject);
    if (normalized) return normalized;
  }
  return null;
};

const normalizeCoverage = (payload, summary) => {
  const coverage = asObject(summary.outcome_coverage ?? payload.outcome_coverage);
  const orderCoverage = coverage.orders;
  const paymentCoverage = coverage.payments;
  return {
    orders: {
      value: finiteNumber(summary.confirmed_orders, payload.confirmed_orders),
      status: safeText(asObject(orderCoverage).status, typeof orderCoverage === 'string' ? orderCoverage : ''),
    },
    payments: {
      value: finiteNumber(summary.paid_outcomes, summary.paid_conversations, payload.paid_outcomes),
      status: safeText(asObject(paymentCoverage).status, typeof paymentCoverage === 'string' ? paymentCoverage : ''),
    },
    note: safeText(summary.outcome_note, payload.outcome_note, 'نتائج الطلب والدفع لا تُستنتج من نص المحادثة.'),
  };
};

export function buildRevenueCockpitPresentation(payload = {}, requestedFilters = {}) {
  const data = asObject(payload);
  const summary = asObject(data.summary);
  const actionable = asObject(summary.actionable ?? data.actionable_summary);
  const metricRoots = [actionable, summary, data];
  const insights = asArray(data.insights ?? data.actionable_insights)
    .map(normalizeInsight)
    .sort((a, b) => b.priority - a.priority);
  const products = normalizeProducts(data, insights);
  const opportunities = normalizeOpportunities(data, insights);
  const leakageProduct = products.find((product) => product.classification === 'LEAKAGE_CANDIDATE')
    || products.find((product) => product.gap !== null && product.gap > 0);
  const leakageFallback = leakageProduct ? {
    value: leakageProduct.gap,
    subject: leakageProduct.product,
    detail: leakageProduct.interest !== null && leakageProduct.progressed !== null
      ? `${leakageProduct.product}: ${leakageProduct.interest} اهتمام ← ${leakageProduct.progressed} تقدم`
      : `${leakageProduct.product}: راجع أدلة الاهتمام والتقدم`,
    leadId: leakageProduct.leadId,
  } : { value: null };

  const purchaseFallbackValue = purchaseIntentFallback(products);
  const waitingInsights = insights.filter((insight) => insight.type === 'OWNER_RESPONSE_LEAKAGE' || insight.type === 'WAITING_ON_US');
  const knowledgeInsights = insights.filter((insight) => insight.type === 'KNOWLEDGE_GAP');
  const unavailableField = firstDefinedField(metricRoots, METRIC_KEYS.unavailableDemand);
  const knowledgeField = firstDefinedField(metricRoots, METRIC_KEYS.knowledgeGaps);

  const demandWithoutProgress = normalizeMetric({
    roots: metricRoots,
    keys: METRIC_KEYS.demandWithoutProgress,
    fallback: leakageFallback,
  });
  const purchaseIntent = normalizeMetric({
    roots: metricRoots,
    keys: METRIC_KEYS.purchaseIntent,
    fallback: {
      value: purchaseFallbackValue,
      detail: purchaseFallbackValue === null ? '' : 'أحداث نية شراء صريحة مسجلة عبر المنتجات.',
      leadId: opportunities.find((item) => ['PURCHASE_HANDOFF', 'READY_TO_CLOSE'].includes(item.status))?.leadId ?? null,
    },
  });
  const waitingOnUs = normalizeMetric({
    roots: metricRoots,
    keys: METRIC_KEYS.waitingOnUs,
    fallback: {
      value: countUniqueEvidenceLeads(waitingInsights),
      detail: 'محادثات لها دليل انتظار لتدخل الشركة.',
      leadId: waitingInsights[0]?.evidence.find((item) => item.leadId)?.leadId ?? null,
    },
  });

  const unavailableMetric = unavailableField.found
    ? metricContract(unavailableField.value, { detail: 'طلبات حالية لا يملك الكتالوج عرضًا موثّقًا لها.' })
    : null;
  const knowledgeMetric = knowledgeField.found
    ? metricContract(knowledgeField.value, { detail: 'أسئلة متكررة تحتاج حقيقة موثّقة.' })
    : metricContract(countUniqueEvidenceLeads(knowledgeInsights), {
      detail: 'محادثات تعطلت بسبب معلومة غير موثّقة.',
      leadId: knowledgeInsights[0]?.evidence.find((item) => item.leadId)?.leadId ?? null,
    });
  // Keep the fourth decision slot useful: a real knowledge gap outranks an
  // explicitly reported zero/unknown unavailable-demand count.
  const useUnavailableDemand = unavailableField.found
    && ((unavailableMetric?.value ?? 0) > 0 || !((knowledgeMetric.value ?? 0) > 0));
  const fourthMetric = useUnavailableDemand ? unavailableMetric : knowledgeMetric;

  const filtersApplied = asObject(data.filters_applied ?? data.filters);
  const actualDays = finiteNumber(filtersApplied.days, filtersApplied.window_days, data.window_days, requestedFilters.days);
  const actualChannel = safeText(filtersApplied.channel, requestedFilters.channel, 'all');

  return {
    metrics: [
      {
        key: 'demand_without_progress',
        label: 'طلب بلا تقدم',
        ...demandWithoutProgress,
        detail: demandWithoutProgress.detail || 'الفرق بين محادثات الاهتمام والمحادثات التي سجلت تقدمًا لاحقًا.',
        tone: 'purple',
      },
      {
        key: 'purchase_intent',
        label: 'إشارات نية شراء',
        ...purchaseIntent,
        detail: purchaseIntent.detail || 'لا تُعد طلبات مؤكدة أو مدفوعات.',
        tone: 'green',
      },
      {
        key: 'waiting_on_us',
        label: 'ينتظرون ردنا',
        ...waitingOnUs,
        detail: waitingOnUs.detail || 'حالات موثّقة تحتاج تدخل الشركة.',
        tone: 'amber',
      },
      {
        key: useUnavailableDemand ? 'currently_unavailable_demand' : 'knowledge_gaps',
        label: useUnavailableDemand ? 'طلب غير متاح حاليًا' : 'فجوات معرفة تعطل الرد',
        ...fourthMetric,
        detail: fourthMetric.detail || 'لا توجد قيمة موثقة في استجابة المصدر.',
        tone: 'blue',
      },
    ],
    products,
    insights,
    evidenceInsights: insights.filter((insight) => insight.evidence.some((item) => item.leadId !== null && item.leadId !== undefined)),
    opportunities,
    executiveBrief: normalizeExecutiveBrief(data, insights, opportunities),
    trend: normalizeTrend(data),
    coverage: normalizeCoverage(data, summary),
    filters: {
      days: actualDays,
      channel: actualChannel,
      requestedDays: finiteNumber(requestedFilters.days),
      requestedChannel: safeText(requestedFilters.channel, 'all'),
      windowMismatch: actualDays !== null && finiteNumber(requestedFilters.days) !== null && actualDays !== finiteNumber(requestedFilters.days),
    },
    generatedAt: data.generated_at ?? null,
    dataSource: safeText(data.data_source, 'deterministic_commercial_events'),
    askExamples: asArray(data.ask_examples).filter((item) => typeof item === 'string' && item.trim()),
  };
}

export const analyticsClassificationTone = (classification) => CLASSIFICATION_TONES[classification] || 'neutral';
