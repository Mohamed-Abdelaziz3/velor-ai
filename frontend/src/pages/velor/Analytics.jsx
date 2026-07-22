import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Clock3,
  Database,
  Layers3,
  MessageCircle,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Target,
  TrendingUp,
} from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import {
  createClientEventId,
  getBusinessInsights,
  getRecoveryImpact,
  recordProductEvents,
} from '../../services/api';
import {
  Badge,
  Button,
  Card,
  DataStateNotice,
  MetricCard,
  PageHeader,
  PanelHeader,
  SegmentedControl,
  SelectField,
  cx,
} from '../../components/velor/ui';
import { TrendChart } from '../../components/velor/charts';
import { buildRevenueCockpitPresentation } from './analyticsPresentation';

const RANGE_OPTIONS = [
  { value: '7', label: '7 أيام' },
  { value: '30', label: '30 يومًا' },
  { value: '90', label: '90 يومًا' },
];

const CHANNEL_OPTIONS = [
  { value: 'all', label: 'كل القنوات' },
  { value: 'whatsapp', label: 'واتساب' },
  { value: 'web', label: 'دردشة الموقع' },
];

const METRIC_ICONS = {
  demand_without_progress: TrendingUp,
  purchase_intent: Target,
  waiting_on_us: Clock3,
  currently_unavailable_demand: MessageCircle,
  knowledge_gaps: Layers3,
};

const numberFormatter = new Intl.NumberFormat('ar-EG');
const isNumber = (value) => typeof value === 'number' && Number.isFinite(value);
const formatCount = (value) => (isNumber(value) ? numberFormatter.format(value) : '—');

function CockpitLoading() {
  return (
    <div className="space-y-5" role="status" aria-label="جاري تحميل قرارات المحادثات">
      <Card className="min-h-[190px] animate-pulse p-5">
        <div className="h-3 w-28 rounded bg-white/[0.07]" />
        <div className="mt-5 h-8 w-3/4 rounded bg-white/[0.08]" />
        <div className="mt-4 h-3 w-1/2 rounded bg-white/[0.05]" />
      </Card>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((item) => (
          <Card key={item} className="min-h-[154px] animate-pulse p-5">
            <div className="h-3 w-24 rounded bg-white/[0.07]" />
            <div className="mt-5 h-8 w-20 rounded bg-white/[0.08]" />
            <div className="mt-4 h-3 w-40 rounded bg-white/[0.05]" />
          </Card>
        ))}
      </div>
    </div>
  );
}

function ExecutiveBrief({ brief, onOpenLead }) {
  return (
    <Card
      className="overflow-hidden border-velor-purple/20 bg-[radial-gradient(circle_at_top_right,rgba(155,92,255,.16),transparent_42%),linear-gradient(135deg,rgba(21,24,36,.98),rgba(11,12,20,.98))] p-5 sm:p-6"
      glow
    >
      <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0 max-w-4xl">
          <Badge tone="purple"><Sparkles className="h-3 w-3" aria-hidden="true" /> القرار الأهم الآن</Badge>
          <h2 className="mt-4 text-xl font-semibold leading-8 text-white sm:text-2xl" dir="auto">{brief.headline}</h2>
          {brief.context && <p className="mt-2 max-w-3xl text-xs leading-6 text-velor-muted" dir="auto">{brief.context}</p>}
          {brief.action && (
            <div className="mt-4 rounded-xl border border-velor-purple/20 bg-velor-purple/[0.075] p-3.5">
              <p className="text-[10px] font-bold tracking-[0.14em] text-velor-violet">الخطوة المقترحة</p>
              <p className="mt-1 text-sm font-medium leading-6 text-white" dir="auto">{brief.action}</p>
            </div>
          )}
        </div>
        {brief.leadId !== null && brief.leadId !== undefined && (
          <Button onClick={() => onOpenLead(brief.leadId)} className="shrink-0">
            افتح المحادثة <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          </Button>
        )}
      </div>
    </Card>
  );
}

function DecisionMetrics({ metrics }) {
  return (
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="أهم قرارات نافذة المحادثات">
      {metrics.map((metric) => {
        const Icon = METRIC_ICONS[metric.key] || MessageCircle;
        return (
          <MetricCard
            key={metric.key}
            label={metric.label}
            value={formatCount(metric.value)}
            detail={metric.detail}
            icon={Icon}
            tone={metric.tone}
            unavailable={!isNumber(metric.value)}
          >
            {metric.subject && <Badge tone="neutral" className="mt-2 max-w-full truncate">{metric.subject}</Badge>}
          </MetricCard>
        );
      })}
    </section>
  );
}

function OpportunityQueue({ opportunities, onOpenLead }) {
  return (
    <Card className="min-w-0 overflow-hidden p-4 sm:p-5">
      <PanelHeader
        eyebrow="نفّذ الآن"
        title="فرص مرتبطة بمحادثاتها"
        description="الترتيب مبني على إشارات وأدلة قابلة للمراجعة، وليس على إيراد مفترض."
        action={<Badge tone={opportunities.length ? 'purple' : 'neutral'}>{numberFormatter.format(opportunities.length)} فرصة</Badge>}
      />
      {opportunities.length ? (
        <div className="mt-4 divide-y divide-white/[0.06] overflow-hidden rounded-xl border border-white/[0.07]">
          {opportunities.map((opportunity) => (
            <button
              key={opportunity.id}
              type="button"
              onClick={() => onOpenLead(opportunity.leadId, opportunity)}
              className="grid w-full gap-3 bg-white/[0.015] px-4 py-4 text-right transition hover:bg-white/[0.045] md:grid-cols-[minmax(150px,.7fr)_minmax(0,1.35fr)_minmax(0,1.25fr)_auto] md:items-center"
            >
              <span className="min-w-0">
                <span className="block truncate text-xs font-semibold text-white">{opportunity.customerName}</span>
                <span className="mt-1 block truncate text-[10px] text-velor-muted">{opportunity.product || opportunity.waitingDuration || 'محادثة موثّقة'}</span>
              </span>
              <span className="min-w-0">
                <Badge tone={opportunity.status === 'PURCHASE_HANDOFF' || opportunity.status === 'READY_TO_CLOSE' ? 'green' : opportunity.status === 'WAITING_ON_US' ? 'amber' : 'purple'}>{opportunity.statusLabel}</Badge>
                <span className="mt-2 line-clamp-2 block text-[11px] leading-5 text-velor-secondary" dir="auto">{opportunity.reason || opportunity.title}</span>
              </span>
              <span className="line-clamp-2 text-[11px] font-medium leading-5 text-white" dir="auto">{opportunity.action}</span>
              <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-velor-violet">افتح المحادثة والدليل <ArrowLeft className="h-3.5 w-3.5" /></span>
            </button>
          ))}
        </div>
      ) : (
        <div className="mt-4">
          <DataStateNotice
            title="لا توجد فرصة مرتبطة بمحادثة قابلة للفتح"
            description="لم تُرجع نافذة المصدر الحالية إجراءً مدعومًا بدليل محادثة. هذا لا يعني عدم وجود مبيعات أو طلبات."
          />
        </div>
      )}
    </Card>
  );
}

function ProductFriction({ product }) {
  if (!product.friction.length) return <span className="text-velor-muted">لا يوجد عائق متكرر موثّق</span>;
  return (
    <span className="space-y-1">
      {product.friction.map((item) => <span key={item} className="block" dir="auto">{item}</span>)}
    </span>
  );
}

function DemandBoard({ products, onOpenLead }) {
  return (
    <section className="space-y-4" aria-labelledby="demand-board-heading">
      <PanelHeader
        eyebrow="صوت السوق"
        title="لوحة الطلب بلا تقدم"
        description="اهتمام صريح ← تقدم محادثة لاحق. هذه ليست مبيعات أو نسبة تحويل."
        action={<Badge tone={products.length ? 'green' : 'neutral'}>{numberFormatter.format(products.length)} منتج بأدلة</Badge>}
      />

      {!products.length ? (
        <DataStateNotice
          title="لا توجد أدلة منتجات كافية في هذه النافذة"
          description="ستظهر المنتجات بعد تسجيل أسئلة أو مقارنة أو اختيار صريح مرتبط بمنتج موثّق في الكتالوج."
        />
      ) : (
        <>
          <Card className="hidden overflow-hidden p-0 md:block">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1050px] border-collapse text-right text-[11px]">
                <thead className="border-b border-white/[0.07] bg-white/[0.025] text-[10px] font-bold text-velor-muted">
                  <tr>
                    <th className="px-4 py-3">المنتج</th>
                    <th className="px-3 py-3">اهتمام</th>
                    <th className="px-3 py-3">تقدم</th>
                    <th className="px-3 py-3">الفجوة</th>
                    <th className="min-w-[210px] px-3 py-3">اعتراضات / مراحل مرصودة</th>
                    <th className="px-3 py-3">التصنيف</th>
                    <th className="min-w-[260px] px-4 py-3">القرار التالي</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.06]">
                  {products.map((product) => (
                    <tr key={product.id} className="bg-white/[0.01] transition hover:bg-white/[0.025]">
                      <td className="px-4 py-4"><span className="font-semibold text-white" dir="auto">{product.product}</span></td>
                      <td className="metric-numbers px-3 py-4 text-white">{formatCount(product.interest)}</td>
                      <td className="metric-numbers px-3 py-4 text-white">{formatCount(product.progressed)}</td>
                      <td className={cx('metric-numbers px-3 py-4 font-semibold', isNumber(product.gap) && product.gap > 0 ? 'text-velor-amber' : 'text-velor-secondary')}>{formatCount(product.gap)}</td>
                      <td className="px-3 py-4 leading-5 text-velor-muted"><ProductFriction product={product} /></td>
                      <td className="px-3 py-4"><Badge tone={product.tone}>{product.classificationLabel}</Badge></td>
                      <td className="px-4 py-4">
                        <div className="flex items-center justify-between gap-3">
                          <span className="line-clamp-2 leading-5 text-velor-secondary" dir="auto">{product.recommendedAction}</span>
                          {product.leadId !== null && product.leadId !== undefined && (
                            <Button variant="ghost" className="min-h-9 shrink-0 px-2 text-[10px]" onClick={() => onOpenLead(product.leadId)}>الدليل <ArrowLeft className="h-3 w-3" /></Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <div className="grid gap-3 md:hidden">
            {products.map((product) => (
              <Card key={product.id} className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0"><p className="truncate text-sm font-semibold text-white" dir="auto">{product.product}</p><p className="mt-1 text-[10px] text-velor-muted">اهتمام {formatCount(product.interest)} ← تقدم {formatCount(product.progressed)}</p></div>
                  <Badge tone={product.tone}>{product.classificationLabel}</Badge>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                  {[['اهتمام', product.interest], ['تقدم', product.progressed], ['الفجوة', product.gap]].map(([label, value]) => (
                    <div key={label} className="rounded-xl border border-white/[0.06] bg-white/[0.025] p-2"><p className="metric-numbers text-base font-semibold text-white">{formatCount(value)}</p><p className="mt-1 text-[10px] text-velor-secondary">{label}</p></div>
                  ))}
                </div>
                <div className="mt-3 text-[11px] leading-5 text-velor-muted"><ProductFriction product={product} /></div>
                <p className="mt-3 text-xs leading-5 text-velor-secondary" dir="auto">{product.recommendedAction}</p>
                {product.leadId !== null && product.leadId !== undefined && <Button variant="secondary" className="mt-3 w-full text-xs" onClick={() => onOpenLead(product.leadId)}>افتح محادثة داعمة</Button>}
              </Card>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

const INSIGHT_FIELD_TONES = {
  observed: 'border-white/[0.07] bg-white/[0.025]',
  unknown: 'border-velor-amber/15 bg-velor-amber/[0.045]',
  recommendation: 'border-velor-purple/15 bg-velor-purple/[0.055]',
  experiment: 'border-velor-blue/15 bg-velor-blue/[0.045]',
  measure: 'border-velor-green/15 bg-velor-green/[0.04]',
};

function InsightField({ label, value, tone }) {
  if (!value) return null;
  return (
    <div className={cx('rounded-xl border p-3', INSIGHT_FIELD_TONES[tone] || INSIGHT_FIELD_TONES.observed)}>
      <p className="text-[10px] font-bold tracking-[0.1em] text-velor-muted">{label}</p>
      <p className="mt-1 text-xs leading-5 text-velor-secondary" dir="auto">{value}</p>
    </div>
  );
}

function InsightCard({ insight, onOpenLead }) {
  return (
    <Card as="article" className="flex h-full flex-col p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Badge tone="purple">إشارة قابلة للتحقق</Badge>
          <h3 className="mt-3 text-sm font-semibold leading-6 text-white" dir="auto">{insight.title}</h3>
        </div>
        <Badge tone="neutral">{numberFormatter.format(insight.evidence.length)} دليل</Badge>
      </div>

      <div className="mt-4 space-y-2.5">
        <InsightField label="ما الذي لاحظناه؟" value={insight.observed} tone="observed" />
        <InsightField label="ما الذي لا نعرفه؟" value={insight.unknown} tone="unknown" />
        <InsightField label="ماذا نفعل؟" value={insight.recommendation} tone="recommendation" />
        <InsightField label="التجربة التالية" value={insight.experiment} tone="experiment" />
        <InsightField label="كيف نقيسها؟" value={insight.measure} tone="measure" />
      </div>

      {insight.doNotConclude && <p className="mt-3 text-[10px] leading-5 text-velor-muted" dir="auto">تنبيه: {insight.doNotConclude}</p>}

      <div className="mt-auto pt-4">
        <p className="mb-2 text-[10px] font-bold tracking-[0.12em] text-velor-muted">المحادثات الداعمة</p>
        <div className="space-y-2">
          {insight.evidence.filter((evidence) => evidence.leadId !== null && evidence.leadId !== undefined).slice(0, 2).map((evidence, index) => (
            <button
              key={evidence.id || `${insight.id}-${evidence.leadId}-${index}`}
              type="button"
              onClick={() => onOpenLead(evidence.leadId)}
              className="flex min-h-11 w-full items-center justify-between gap-3 rounded-xl border border-white/[0.07] bg-black/15 p-3 text-right transition hover:border-velor-purple/25 hover:bg-velor-purple/[0.04]"
            >
              <span className="min-w-0"><span className="block truncate text-[11px] font-semibold text-white">{evidence.customerName}{evidence.product ? ` · ${evidence.product}` : ''}</span><span className="mt-1 line-clamp-1 block text-[10px] text-velor-muted" dir="auto">{evidence.sourceText}</span></span>
              <ArrowLeft className="h-3.5 w-3.5 shrink-0 text-velor-violet" />
            </button>
          ))}
        </div>
      </div>
    </Card>
  );
}

function InsightGrid({ insights, onOpenLead }) {
  return (
    <section className="space-y-4" aria-labelledby="insight-grid-heading">
      <PanelHeader
        eyebrow="لماذا يتوقف الطلب؟"
        title="قرارات مبنية على دليل المحادثة"
        description="كل بطاقة تفصل بين الملاحظة والمجهول، ثم تقترح تجربة وطريقة قياس."
        action={<Badge tone={insights.length ? 'purple' : 'neutral'}>{numberFormatter.format(insights.length)} تحليل</Badge>}
      />
      {insights.length ? (
        <div className="grid gap-4 xl:grid-cols-2">
          {insights.slice(0, 8).map((insight) => <InsightCard key={insight.id} insight={insight} onOpenLead={onOpenLead} />)}
        </div>
      ) : (
        <DataStateNotice
          title="لا توجد تحليلات مرتبطة بمحادثات كافية بعد"
          description="لا يعرض VELOR نمطًا تجاريًا من دون دليل يمكن فتحه ومراجعته."
        />
      )}
    </section>
  );
}

function OutcomeCoverageBar({ coverage }) {
  const outcomes = [
    { key: 'orders', label: 'طلبات مؤكدة', ...coverage.orders, trustedOutcome: true },
    { key: 'payments', label: 'نتائج مدفوعة', ...coverage.payments, trustedOutcome: true },
  ];
  const statusLabel = (status, unavailable) => {
    const normalized = String(status || '').toLowerCase();
    if (normalized === 'not_connected' || normalized === 'disconnected') return 'غير متصل';
    if (normalized === 'connected') return unavailable ? 'متصل بلا قيمة موثّقة' : 'متصل';
    return unavailable ? 'غير معروف' : 'موثّق';
  };

  return (
    <Card className="p-3.5 sm:p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-start gap-2.5">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-velor-blue" aria-hidden="true" />
          <div><p className="text-xs font-semibold text-white">تغطية نتائج الطلب والدفع</p><p className="mt-1 text-[10px] leading-5 text-velor-muted" dir="auto">{coverage.note}</p></div>
        </div>
        <div className="flex flex-wrap gap-2">
          {outcomes.map(({ key, label, value, status, trustedOutcome }) => {
            const unavailable = trustedOutcome && !isNumber(value);
            return (
              <div key={key} className="flex min-w-[150px] items-center justify-between gap-3 rounded-xl border border-white/[0.07] bg-white/[0.025] px-3 py-2">
                <span><span className="block text-[10px] text-velor-muted">{label}</span><span className="metric-numbers mt-0.5 block text-sm font-semibold text-white">{unavailable ? '—' : formatCount(value)}</span></span>
                <Badge tone={unavailable ? 'neutral' : 'green'}>{statusLabel(status, unavailable)}</Badge>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}

function RecoveryImpact({ data, error }) {
  if (error) {
    return <DataStateNotice title="تعذّر تحميل أثر الاسترداد" description={error} tone="blue" />;
  }
  if (!data) return null;
  const metrics = data.metrics || {};
  const operational = [
    ['unique_active_opportunities_shown', 'فرص نشطة ظهرت'],
    ['unique_opportunities_opened', 'فرص فتحها المالك'],
    ['priority_signals_handled_within_24_hours', 'إشارات عولجت خلال 24 ساعة'],
    ['follow_ups_completed_on_time', 'متابعات اكتملت في موعدها'],
    ['suggestion_sends', 'ردود مقترحة أُرسلت'],
    ['conversations_with_subsequent_commercial_progress', 'محادثات شهدت تقدماً لاحقاً'],
  ];
  return (
    <Card as="section" className="p-4 sm:p-5">
      <PanelHeader
        eyebrow="Recovery Impact"
        title="أثر تشغيلي موثّق"
        description="هذه قياسات أحداث فعلية داخل VELOR. التقدم اللاحق ارتباط زمني، وليس إثبات سببية أو إيراد مسترد."
        action={<Badge tone="blue">{data.filters_applied?.days || '—'} يوم</Badge>}
      />
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {operational.map(([key, label]) => {
          const metric = metrics[key] || {};
          return (
            <div key={key} className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-3">
              <p className="text-[10px] text-velor-muted">{label}</p>
              <p className="metric-numbers mt-1 text-xl font-semibold text-white">{formatCount(metric.value)}</p>
              <p className="mt-1 text-[10px] leading-4 text-velor-muted" dir="auto">{metric.definition}</p>
            </div>
          );
        })}
      </div>
      <div className="mt-4 rounded-xl border border-amber-400/15 bg-amber-400/[0.04] p-3">
        <div className="flex flex-wrap items-center gap-2"><Badge tone="neutral">النتائج المالية: غير متصلة</Badge><span className="text-xs font-semibold text-white">الإيراد المسترد والمنسوب —</span></div>
        <p className="mt-2 text-[11px] leading-5 text-velor-muted" dir="auto">{data.outcome_explanation_ar}</p>
      </div>
    </Card>
  );
}

export default function Analytics() {
  const { companyId } = useAuth();
  const navigate = useNavigate();
  const [range, setRange] = useState('30');
  const [channel, setChannel] = useState('all');
  const [intelligence, setIntelligence] = useState(null);
  const [intelligenceError, setIntelligenceError] = useState('');
  const [recoveryImpact, setRecoveryImpact] = useState(null);
  const [recoveryError, setRecoveryError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const requestRef = useRef(0);
  const shownQueueItemsRef = useRef(new Set());

  useEffect(() => {
    if (!companyId) {
      setLoading(false);
      setIntelligence(null);
      setIntelligenceError('لم يتم العثور على مساحة عمل نشطة. سجّل الدخول أو اختر مساحة عمل لتحميل قرارات المحادثات.');
      return undefined;
    }

    const controller = new AbortController();
    const requestId = ++requestRef.current;
    setLoading(true);
    setIntelligence(null);
    setRecoveryImpact(null);
    setIntelligenceError('');
    setRecoveryError('');

    Promise.allSettled([
      getBusinessInsights({ days: Number(range), channel, signal: controller.signal }),
      getRecoveryImpact({ days: Number(range), channel, signal: controller.signal }),
    ])
      .then(([insightsResult, impactResult]) => {
        if (requestId !== requestRef.current) return;
        if (insightsResult.status === 'fulfilled') {
          setIntelligence(insightsResult.value.data?.data || insightsResult.value.data || null);
        } else if (insightsResult.reason?.code !== 'ERR_CANCELED') {
          setIntelligenceError('لم تستجب خدمة ذكاء المحادثات. لم يتم استبدالها بقيم محفوظة أو تجريبية.');
        }
        if (impactResult.status === 'fulfilled') {
          setRecoveryImpact(impactResult.value.data?.data || impactResult.value.data || null);
        } else if (impactResult.reason?.code !== 'ERR_CANCELED') {
          setRecoveryError('بيانات الأثر التشغيلي غير متاحة في هذا التحديث، ولم تُستبدل بأرقام تقديرية.');
        }
      })
      .finally(() => {
        if (requestId === requestRef.current) setLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [channel, companyId, range, refreshVersion]);

  const presentation = useMemo(
    () => buildRevenueCockpitPresentation(intelligence || {}, { days: Number(range), channel }),
    [channel, intelligence, range]
  );

  useEffect(() => {
    if (!intelligence) return;
    const newlyRendered = presentation.opportunities.filter(
      (item) => item.queueItemId && item.leadId && !shownQueueItemsRef.current.has(item.queueItemId)
    );
    if (!newlyRendered.length) return;
    newlyRendered.forEach((item) => shownQueueItemsRef.current.add(item.queueItemId));
    recordProductEvents(newlyRendered.map((item) => ({
      event_name: 'opportunity_shown',
      client_event_id: createClientEventId('analytics-shown'),
      metadata: {
        lead_id: item.leadId,
        queue_item_id: item.queueItemId,
        surface: 'analytics',
      },
    }))).catch(() => {});
  }, [intelligence, presentation.opportunities]);

  const openLead = (leadId, opportunity = null) => {
    if (leadId === null || leadId === undefined) return;
    const openWorkspace = () => navigate(`/inbox/${encodeURIComponent(String(leadId))}`, {
      state: opportunity?.queueItemId
        ? { recoveryQueueItemId: opportunity.queueItemId, recoverySurface: 'analytics' }
        : undefined,
    });
    if (opportunity?.queueItemId) {
      recordProductEvents([{
        event_name: 'opportunity_opened',
        client_event_id: createClientEventId('analytics-opened'),
        metadata: {
          lead_id: leadId,
          queue_item_id: opportunity.queueItemId,
          surface: 'analytics',
        },
      }]).catch(() => {}).finally(openWorkspace);
      return;
    }
    openWorkspace();
  };

  const evidenceSourceBadge = intelligenceError
    ? <Badge tone="red">المصدر غير متاح</Badge>
    : intelligence
      ? <Badge tone="green" dot>بيانات محادثات موثّقة</Badge>
      : <Badge tone="neutral">بانتظار المصدر</Badge>;

  const actualWindowLabel = presentation.filters.days
    ? `${numberFormatter.format(presentation.filters.days)} يومًا`
    : 'النافذة غير معروفة';
  const channelLabel = CHANNEL_OPTIONS.find((option) => option.value === presentation.filters.channel)?.label
    || presentation.filters.channel;

  return (
    <div className="mx-auto w-full max-w-[1600px] space-y-6 p-4 pb-16 sm:p-6 xl:p-8 animate-velor-in" dir="rtl" lang="ar">
      <PageHeader
        eyebrow="Revenue Cockpit"
        title="من المحادثة إلى قرار قابل للتنفيذ"
        description="اعرف ماذا يطلب العملاء، أين يتوقف التقدم، وأي محادثة تستحق تدخلك الآن — من دون اختلاق مبيعات أو تحويلات."
        badge={evidenceSourceBadge}
        actions={<Button variant="secondary" onClick={() => setRefreshVersion((value) => value + 1)} loading={loading}><RefreshCw className="h-4 w-4" /> تحديث</Button>}
      />

      <Card as="section" className="p-3 sm:p-4" aria-label="مرشحات قرارات المحادثات" aria-busy={loading}>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xs font-semibold text-white">نافذة القرار</p>
              {intelligence && <Badge tone={presentation.filters.windowMismatch ? 'amber' : 'neutral'}>{actualWindowLabel} · {channelLabel || 'كل القنوات'}</Badge>}
            </div>
            <p className="mt-1 text-[11px] leading-5 text-velor-muted">تُرسل الفترة والقناة إلى مصدر التحليلات؛ إذا أعاد المصدر نافذة مختلفة تظهر النافذة الفعلية هنا.</p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div>
              <p className="mb-2 text-xs font-semibold text-velor-secondary">الفترة</p>
              <SegmentedControl options={RANGE_OPTIONS} value={range} onChange={setRange} label="فترة ذكاء المحادثات" className="w-full sm:w-auto" />
            </div>
            <SelectField label="القناة" value={channel} onChange={(event) => setChannel(event.target.value)} className="min-w-[170px]">
              {CHANNEL_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </SelectField>
          </div>
        </div>
      </Card>

      {intelligenceError && (
        <DataStateNotice
          title="تعذر تحميل قرارات المحادثات"
          description={intelligenceError}
          tone="blue"
          action={<Button variant="secondary" onClick={() => setRefreshVersion((value) => value + 1)}>حاول مرة أخرى</Button>}
        />
      )}

      {!loading && !intelligence && <RecoveryImpact data={recoveryImpact} error={recoveryError} />}

      {loading ? (
        <CockpitLoading />
      ) : intelligence ? (
        <div className="space-y-6">
          <ExecutiveBrief brief={presentation.executiveBrief} onOpenLead={openLead} />
          <DecisionMetrics metrics={presentation.metrics} />
          <RecoveryImpact data={recoveryImpact} error={recoveryError} />

          <section className={cx('grid gap-5', presentation.trend && 'xl:grid-cols-[minmax(0,1.25fr)_minmax(340px,.75fr)]')}>
            <OpportunityQueue opportunities={presentation.opportunities} onOpenLead={openLead} />
            {presentation.trend && (
              <Card className="min-w-0 p-4 sm:p-5">
                <PanelHeader eyebrow="الحركة عبر الوقت" title={presentation.trend.label} description="سلسلة المصدر للفترة والقناة المختارتين." action={<Database className="h-4 w-4 text-velor-blue" />} />
                <TrendChart values={presentation.trend.values} labels={presentation.trend.labels} summary={presentation.trend.label} className="mt-5" color="#38BDF8" />
              </Card>
            )}
          </section>

          <DemandBoard products={presentation.products} onOpenLead={openLead} />
          <InsightGrid insights={presentation.evidenceInsights} onOpenLead={openLead} />
          <OutcomeCoverageBar coverage={presentation.coverage} />
        </div>
      ) : null}
    </div>
  );
}
