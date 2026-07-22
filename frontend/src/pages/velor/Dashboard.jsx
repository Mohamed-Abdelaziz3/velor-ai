import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity,
  ArrowLeft,
  Bot,
  Clock3,
  DollarSign,
  RefreshCw,
  ShieldAlert,
  ShoppingCart,
  Sparkles,
  Target,
  UsersRound,
  Zap,
} from 'lucide-react';
import api, { createClientEventId, getStats, recordProductEvents } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { useGlobalEvents } from '../../contexts/GlobalEventContext';
import { Badge, Button, Card, DataStateNotice, MetricCard, PageHeader, PanelHeader, ProgressBar, cx } from '../../components/velor/ui';
import { formatRelativeTime } from '../../utils/timeUtils';

const actionTone = {
  NEEDS_ACTION: 'red',
  PURCHASE_HANDOFF: 'green',
  FOLLOW_UP: 'amber',
  WAITING_FOR_CUSTOMER: 'blue',
  RESOLVED_TODAY: 'purple',
};

const actionLabels = {
  NEEDS_ACTION: 'محتاج تدخّل',
  PURCHASE_HANDOFF: 'جاهز لتأكيد الطلب',
  FOLLOW_UP: 'موعد المتابعة',
  WAITING_FOR_CUSTOMER: 'مستني رد العميل',
  RESOLVED_TODAY: 'اتقفل النهارده',
};

const streamStates = {
  connected: { label: 'متصل', tone: 'green', dot: true },
  connecting: { label: 'جاري الاتصال', tone: 'blue', dot: false },
  reconnecting: { label: 'جاري إعادة الاتصال', tone: 'amber', dot: false },
  disconnected: { label: 'غير متصل', tone: 'red', dot: false },
  idle: { label: 'لم يبدأ الاتصال', tone: 'neutral', dot: false },
};

function getGreeting(date = new Date()) {
  const hour = date.getHours();
  if (hour < 12) return 'صباح الخير';
  return 'مساء الخير';
}

function finiteMetric(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function toAction(item, index) {
  return {
    id: item.id || item.lead_id || index,
    queueItemId: item.queue_item_id || item.id || null,
    leadId: item.lead_id,
    name: item.customer_name || item.display_label || item.name || 'محادثة عميل',
    channel: item.channel || item.channel_type || 'القناة غير متاحة',
    action: actionLabels[item.status] || item.status_label || 'إشارة تجارية موثّقة',
    detail: item.recommended_action || item.reason || 'راجع آخر دليل موثّق في محادثة العميل.',
    confidence: item.confidence ? Math.round(item.confidence * (item.confidence <= 1 ? 100 : 1)) : null,
    time: item.waiting_duration || 'الوقت غير متاح',
    tone: actionTone[item.status] || 'purple',
    product: item.current_product || item.product,
    status: item.status,
    category: item.category,
    sourceMessageInternalId: item.source_message_internal_id || null,
  };
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { companyId } = useAuth();
  const { lastEvent, connectionState, lastEventAt } = useGlobalEvents();
  const [stats, setStats] = useState(null);
  const [queue, setQueue] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [clockNow, setClockNow] = useState(() => Date.now());
  const shownQueueItemsRef = useRef(new Set());

  const loadDashboard = useCallback(async () => {
    if (!companyId) {
      setStats(null);
      setQueue(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError('');
    try {
      const [statsResult, queueResult] = await Promise.allSettled([
        getStats(companyId),
        api.get('/api/v1/copilot/queue'),
      ]);

      if (statsResult.status === 'fulfilled') {
        setStats(statsResult.value.data || null);
      } else {
        setStats(null);
      }

      if (queueResult.status === 'fulfilled') {
        const queuePayload = queueResult.value.data?.data || queueResult.value.data || {};
        setQueue((queuePayload.items || []).map(toAction));
      } else {
        setQueue(null);
      }

      if (statsResult.status === 'rejected' && queueResult.status === 'rejected') {
        setError('تعذّر تحديث ملخص التشغيل. بياناتك الحالية لم تتغيّر.');
      } else if (statsResult.status === 'rejected') {
        setError('مؤشرات التشغيل غير متاحة مؤقتًا، لكن إشارات الأولوية الموثّقة ما زالت ظاهرة.');
      } else if (queueResult.status === 'rejected') {
        setError('قائمة الأولويات غير متاحة مؤقتًا، لكن مؤشرات التشغيل الموثّقة ما زالت ظاهرة.');
      }
    } catch {
      setError('تعذّر تحديث ملخص التشغيل. بياناتك الحالية لم تتغيّر.');
    } finally {
      setLoading(false);
    }
  }, [companyId]);

  useEffect(() => { loadDashboard(); }, [loadDashboard]);
  useEffect(() => {
    const interval = setInterval(() => setClockNow(Date.now()), 60_000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!lastEvent) return;
    if (['message.received', 'lead.updated', 'lead.created', 'intelligence.updated', 'canonical_commercial.updated'].includes(lastEvent.type)) {
      loadDashboard();
    }
  }, [lastEvent, loadDashboard]);

  const automation = finiteMetric(stats?.automation_rate);
  const hoursSaved = finiteMetric(stats?.hours_saved);
  const dailyTarget = finiteMetric(stats?.daily_target);
  const wonToday = finiteMetric(stats?.won_deals_today);
  const targetProgress = dailyTarget !== null && dailyTarget > 0 && wonToday !== null ? Math.round((wonToday / dailyTarget) * 100) : null;
  const queueAvailable = Array.isArray(queue);
  const topActions = (queue || []).slice(0, 4);
  const stream = streamStates[connectionState] || streamStates.idle;
  const now = new Intl.DateTimeFormat('ar-EG', { weekday: 'long', month: 'long', day: 'numeric' }).format(new Date());
  const greeting = getGreeting();

  useEffect(() => {
    const newlyRendered = topActions.filter(
      (item) => item.queueItemId && item.leadId && !shownQueueItemsRef.current.has(item.queueItemId)
    );
    if (!newlyRendered.length) return;
    newlyRendered.forEach((item) => shownQueueItemsRef.current.add(item.queueItemId));
    recordProductEvents(newlyRendered.map((item) => ({
      event_name: 'opportunity_shown',
      client_event_id: createClientEventId('dashboard-shown'),
      metadata: {
        lead_id: item.leadId,
        queue_item_id: item.queueItemId,
        surface: 'dashboard',
      },
    }))).catch(() => {});
  }, [topActions]);

  const openAction = (item) => {
    const openWorkspace = () => {
      if (item.leadId) navigate(`/inbox/${item.leadId}`, {
        state: { recoveryQueueItemId: item.queueItemId, recoverySurface: 'dashboard' },
      });
      else navigate('/inbox');
    };
    if (item.queueItemId && item.leadId) {
      recordProductEvents([{
        event_name: 'opportunity_opened',
        client_event_id: createClientEventId('dashboard-opened'),
        metadata: {
          lead_id: item.leadId,
          queue_item_id: item.queueItemId,
          surface: 'dashboard',
        },
      }]).catch(() => {}).finally(openWorkspace);
      return;
    }
    openWorkspace();
  };

  return (
    <div dir="rtl" lang="ar" className="mx-auto w-full max-w-[1560px] space-y-5 p-4 text-right sm:p-5 xl:p-7 2xl:p-8">
      <PageHeader
        eyebrow="ملخص التشغيل والمبيعات"
        title={`${greeting} — دي أهم الإشارات.`}
        description={`${now} · VELOR بيفصل بين بيانات التشغيل الموثّقة وأي تحليلات لسه محتاجة مصدر بيانات معتمد.`}
        badge={
          <span className="inline-flex items-center gap-1.5 rounded-lg bg-white/[0.03] border border-white/[0.08] px-2.5 py-1 text-xs text-velor-secondary font-medium">
            <span className={cx(
              "h-1.5 w-1.5 rounded-full",
              stream.tone === 'green' ? "bg-emerald-500 animate-pulse" : "bg-velor-muted"
            )} style={{ boxShadow: stream.tone === 'green' ? '0 0 6px #10b981' : 'none' }} />
            <span>التحديثات: {stream.label}</span>
          </span>
        }
        actions={(
          <>
            <Button variant="secondary" onClick={loadDashboard} loading={loading}><RefreshCw className="h-4 w-4" /> تحديث</Button>
            <Button onClick={() => navigate('/inbox')}><Sparkles className="h-4 w-4" /> افتح المحادثات</Button>
          </>
        )}
      />

      {error && <div className="rounded-xl border border-velor-red/25 bg-velor-red/[0.07] px-4 py-3 text-xs text-[#ffb0bd]" role="alert">{error}</div>}

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="مؤشرات الأداء الرئيسية">
        <MetricCard
          label="مبيعات منسوبة للذكاء الاصطناعي"
          value="غير متصل"
          detail="تحتاج أحداث طلب أو دفع موثّقة"
          icon={DollarSign}
          tone="purple"
          unavailable
        />
        <MetricCard
          label="الاعتراضات المفتوحة"
          value="غير متصل"
          detail="تحتاج سياق محادثات نشط"
          icon={ShieldAlert}
          tone="blue"
          unavailable
        />
        <MetricCard
          label="الطلبات المعلقة"
          value="غير متصل"
          detail="تحتاج إشارات دفع صالحة"
          icon={ShoppingCart}
          tone="green"
          unavailable
        />
        <MetricCard
          label="متوسط زمن رد الذكاء الاصطناعي"
          value="غير مقاس"
          detail="يحتاج تجميعًا موثوقًا للطوابع الزمنية"
          icon={Clock3}
          tone="amber"
          unavailable
        />
      </section>

      <Card className="overflow-hidden border-velor-purple/15 bg-gradient-to-l from-velor-purple/[0.09] via-[#11131d] to-velor-blue/[0.04] p-4 sm:p-5" glow={queueAvailable && queue.length > 0}>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-start gap-3.5">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-velor-purple/20 bg-velor-purple/10 text-velor-violet"><Zap className="h-5 w-5" /></span>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-semibold text-white">{!queueAvailable ? 'قائمة الأولويات غير متاحة' : queue.length ? `في ${queue.length.toLocaleString('ar-EG')} محادثة تستاهل المراجعة` : 'مفيش إجراءات أولوية موثّقة دلوقتي'}</p>
                <span className={cx(
                  "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-medium leading-none",
                  !queueAvailable ? "border-white/10 bg-white/[0.03] text-velor-muted" : queue.length ? "border-purple-500/25 bg-purple-500/[0.04] text-purple-300" : "border-blue-500/20 bg-blue-500/[0.02] text-blue-300"
                )}>
                  <span className={cx(
                    "h-1.5 w-1.5 rounded-full",
                    !queueAvailable ? "bg-velor-muted" : queue.length ? "bg-purple-400" : "bg-blue-400"
                  )} />
                  <span>{!queueAvailable ? 'غير متاحة' : queue.length ? 'إشارة أولوية' : 'لا توجد إشارات موثّقة'}</span>
                </span>
              </div>
              <p className="mt-1 text-xs leading-5 text-velor-muted">{!queueAvailable ? 'VELOR مقدرش يتحقق من القائمة الحالية، لذلك مش بيعرض حالة «كله تمام».' : queue.length ? 'الترتيب مبني على إشارات شراء موثّقة، مخاطر العميل، ومواعيد المتابعة — مش على إيراد متوقّع.' : 'آخر استجابة ناجحة للقائمة لم تحتوِ على إجراء أولوية موثّق.'}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-2 text-[11px]">
            <span className="text-velor-muted"><b className="metric-numbers ml-1 text-white">{automation === null ? '—' : `${automation}%`}</b> نسبة ردود VELOR من الردود المسجّلة</span>
            <span className="text-velor-muted"><b className="metric-numbers ml-1 text-white">{hoursSaved === null ? '—' : hoursSaved}</b> ساعة تقديرية على أساس ٢٠ ثانية لكل رد</span>
            <Button variant="ghost" onClick={() => navigate('/inbox')} className="min-h-9 px-2 text-[#d8c1ff]">راجع القائمة <ArrowLeft className="h-3.5 w-3.5" /></Button>
          </div>
        </div>
      </Card>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(340px,.8fr)]">
        <Card className="min-w-0 p-4 sm:p-5">
          <PanelHeader
            eyebrow="نتائج المبيعات"
            title="اتجاه المبيعات بمساعدة الذكاء الاصطناعي"
            description="الرسم هيتفعّل بعد ربط نتائج الطلبات أو المدفوعات وسياسة نسب واضحة."
            action={<Badge tone="neutral">مستني مصدر بيانات</Badge>}
          />
          <DataStateNotice
            title="نسب الإيراد متوقّف عمدًا"
            description="VELOR مش بيستنتج البيع من كلام العميل. اربط أحداث طلب أو دفع حتمية تشمل المبلغ والعملة وفترة النسب علشان الرسم يشتغل."
            action={<Button variant="secondary" onClick={() => navigate('/analytics')}>راجع متطلبات البيانات <ArrowLeft className="h-3.5 w-3.5" /></Button>}
          />
        </Card>

        <Card className="min-w-0 overflow-hidden p-4 sm:p-5" aria-live="polite">
          <PanelHeader
            eyebrow="تدفّق الأحداث"
            title="VELOR شغّال دلوقتي"
            description={lastEventAt ? `إشارات تجارية موثّقة حديثة. آخر حدث ${formatRelativeTime(lastEventAt, { now: clockNow, locale: 'ar-EG' })}.` : 'لم يصل أي حدث خلال جلسة الاتصال الحالية.'}
            action={<Badge tone={stream.tone} dot={stream.dot}>{stream.label}</Badge>}
          />
          <div className="mt-4 space-y-1">
            {topActions.map((item, index) => (
              <button key={item.id} type="button" onClick={() => openAction(item)} className="group flex w-full items-start gap-3 rounded-xl border border-transparent p-3 text-right transition hover:border-white/[0.07] hover:bg-white/[0.035]">
                <span className={cx('mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border', item.tone === 'green' ? 'border-velor-green/15 bg-velor-green/10 text-velor-green' : item.tone === 'amber' ? 'border-velor-amber/15 bg-velor-amber/10 text-velor-amber' : item.tone === 'blue' ? 'border-velor-blue/15 bg-velor-blue/10 text-velor-blue' : item.tone === 'red' ? 'border-velor-red/15 bg-velor-red/10 text-velor-red' : 'border-velor-purple/15 bg-velor-purple/10 text-velor-violet')}>
                  {index % 2 ? <Target className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2"><span className="truncate text-xs font-semibold text-white">{item.name}</span><span className="shrink-0 text-[9px] text-velor-muted">{item.time}</span></span>
                  <span className="mt-0.5 block text-[11px] font-medium text-velor-secondary">{item.action}</span>
                  <span className="mt-1 line-clamp-2 block text-[10px] leading-4 text-velor-muted">{item.detail}</span>
                </span>
              </button>
            ))}
            {!topActions.length && <div className="py-12 text-center"><Activity className="mx-auto h-7 w-7 text-velor-muted" /><p className="mt-3 text-xs font-medium text-velor-secondary">{queueAvailable ? 'لا توجد إشارات أولوية موثّقة' : 'قائمة الأولويات غير متاحة'}</p><p className="mx-auto mt-1 max-w-xs text-[10px] leading-4 text-velor-muted">{queueAvailable ? 'الإشارات بتظهر بعد ما VELOR يوثّق نية شراء أو مخاطرة أو التزام متابعة.' : 'VELOR مقدرش يتحقق من القائمة في آخر تحديث.'}</p></div>}
          </div>
        </Card>
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,.8fr)_minmax(0,1.2fr)]">
        <Card className="p-4 sm:p-5">
          <PanelHeader eyebrow="نشاط القناة" title="حجم رسائل واتساب" description="يحتاج عقد تجميع تحليلي موثوق بدل أخذ عيّنة من الرسائل الخام في المتصفح." />
          <div className="mt-5">
            <DataStateNotice title="بيانات الخريطة الحرارية غير متصلة" description="نقطة التحليلات الموثوقة لازم ترجع سلسلة كاملة ٧×٢٤، والمنطقة الزمنية، وفترة العيّنة، ووقت آخر تحديث." tone="blue" />
          </div>
        </Card>

        <Card className="p-4 sm:p-5">
          <PanelHeader eyebrow="التركيز التجاري" title="الفرص ذات الأولوية" description="الإجراءات مترتبة حسب حالة المحادثة الموثّقة، مش حسب درجة إيراد مخفية." action={<Button variant="ghost" onClick={() => navigate('/inbox')}>اعرض الكل <ArrowLeft className="h-3.5 w-3.5" /></Button>} />
          <div className="mt-4 overflow-hidden rounded-xl border border-white/[0.07]">
            <div className="hidden grid-cols-[1.1fr_.85fr_1.4fr_auto] gap-4 border-b border-white/[0.07] bg-white/[0.025] px-4 py-2.5 text-[11px] font-bold text-velor-secondary md:grid">
              <span>العميل</span><span>الإشارة</span><span>الخطوة الأنسب</span><span />
            </div>
            <div className="divide-y divide-white/[0.06]">
              {topActions.slice(0, 3).map((item) => (
                <button key={item.id} type="button" onClick={() => openAction(item)} className="grid w-full gap-2 px-4 py-3.5 text-right transition hover:bg-white/[0.03] md:grid-cols-[1.1fr_.85fr_1.4fr_auto] md:items-center md:gap-4">
                  <span><span className="block text-xs font-semibold text-white">{item.name}</span><span className="mt-0.5 block text-[10px] text-velor-muted">{item.channel}{item.product ? ` · ${item.product}` : ''}</span></span>
                  <Badge tone={item.tone === 'red' ? 'red' : item.tone === 'green' ? 'green' : item.tone === 'amber' ? 'amber' : item.tone === 'blue' ? 'blue' : 'purple'} className="w-fit">{item.action}</Badge>
                  <span className="line-clamp-2 text-[11px] leading-5 text-velor-secondary">{item.detail}</span>
                  <ArrowLeft className="hidden h-4 w-4 text-velor-muted md:block" />
                </button>
              ))}
              {!topActions.length && <p className="px-4 py-10 text-center text-xs text-velor-muted">{queueAvailable ? 'لا توجد فرص أولوية موثّقة حاليًا.' : 'فرص الأولوية غير متاحة في آخر تحديث.'}</p>}
            </div>
          </div>
        </Card>
      </section>

      <section className="grid gap-3 sm:grid-cols-3" aria-label="مؤشرات تشغيل قابلة للمراجعة">
        <Card className="p-4">
          <div className="flex items-center justify-between"><span className="text-xs font-medium text-velor-secondary">نسبة ردود VELOR من الردود المسجّلة</span><Bot className="h-4 w-4 text-velor-purple" /></div>
          {automation === null ? <p className="mt-4 text-xs text-velor-muted">غير متاحة في آخر استجابة للمؤشرات.</p> : <><ProgressBar value={automation} detail={`${automation}%`} className="mt-4" /><p className="mt-2 text-[10px] leading-4 text-velor-muted">المعادلة: ردود VELOR ÷ (ردود VELOR + ردود صاحب النشاط).</p></>}
        </Card>
        <Card className="p-4">
          <div className="flex items-center justify-between"><span className="text-xs font-medium text-velor-secondary">الوقت التقديري الموفَّر</span><Clock3 className="h-4 w-4 text-velor-blue" /></div>
          {hoursSaved === null ? <p className="mt-4 text-xs text-velor-muted">غير متاح في آخر استجابة للمؤشرات.</p> : <><p className="metric-numbers mt-3 text-xl font-semibold text-white">{hoursSaved} <span className="text-xs font-normal text-velor-muted">ساعة</span></p><p className="mt-2 text-[10px] leading-4 text-velor-muted">تقدير إرشادي على أساس ٢٠ ثانية لكل رد مسجّل من المساعد.</p></>}
        </Card>
        <Card className="p-4">
          <div className="flex items-center justify-between"><span className="text-xs font-medium text-velor-secondary">سجلات مرحلة «مكتمل» المحدّثة اليوم</span><UsersRound className="h-4 w-4 text-velor-green" /></div>
          {targetProgress === null ? <p className="mt-4 text-xs text-velor-muted">{wonToday === null ? 'عدد السجلات غير متاح في آخر استجابة للمؤشرات.' : dailyTarget === null ? `${wonToday} مسجّل، والهدف اليومي غير متاح.` : `${wonToday} مسجّل، ولا يوجد هدف يومي موجب.`}</p> : <ProgressBar value={targetProgress} detail={`${wonToday} / ${dailyTarget}`} tone="green" className="mt-4" />}
          <p className="mt-2 text-[10px] leading-4 text-velor-muted">ده عدد مرحلة داخل سير العمل، مش إجمالي طلبات أو مدفوعات مؤكدة.</p>
        </Card>
      </section>
    </div>
  );
}
