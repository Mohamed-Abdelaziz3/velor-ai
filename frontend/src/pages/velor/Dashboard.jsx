import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity,
  ArrowLeft,
  CheckCircle2,
  Clock3,
  MessageSquareText,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  UserRoundCheck,
} from 'lucide-react';
import api, { createClientEventId, recordProductEvents } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { useGlobalEvents } from '../../contexts/GlobalEventContext';
import { Badge, Button, Card, DataStateNotice, MetricCard, PageHeader, PanelHeader } from '../../components/velor/ui';
import { formatRelativeTime } from '../../utils/timeUtils';

const actionTone = {
  NEEDS_ACTION: 'red',
  PURCHASE_HANDOFF: 'green',
  FOLLOW_UP: 'amber',
  WAITING_FOR_CUSTOMER: 'blue',
  RESOLVED_TODAY: 'purple',
};

const actionLabels = {
  NEEDS_ACTION: 'يحتاج تدخلك',
  PURCHASE_HANDOFF: 'جاهز لتأكيد الطلب',
  FOLLOW_UP: 'متابعة مستحقة',
  WAITING_FOR_CUSTOMER: 'بانتظار العميل',
  RESOLVED_TODAY: 'تمت معالجته اليوم',
};

const streamStates = {
  connected: { label: 'متصل', tone: 'green', dot: true },
  connecting: { label: 'جاري الاتصال', tone: 'blue', dot: false },
  reconnecting: { label: 'إعادة اتصال', tone: 'amber', dot: false },
  disconnected: { label: 'غير متصل', tone: 'red', dot: false },
  idle: { label: 'لم يبدأ الاتصال', tone: 'neutral', dot: false },
};

function getGreeting(date = new Date()) {
  return date.getHours() < 12 ? 'صباح الخير' : 'مساء الخير';
}

function toAction(item, index) {
  return {
    id: item.id || item.lead_id || index,
    queueItemId: item.queue_item_id || item.id || null,
    leadId: item.lead_id,
    name: item.customer_name || item.display_label || item.name || 'محادثة عميل',
    channel: item.channel || item.channel_type || 'القناة غير متاحة',
    action: actionLabels[item.status] || item.status_label || 'تحتاج مراجعة',
    detail: item.recommended_action || item.reason || 'راجع آخر دليل موثّق في محادثة العميل.',
    time: item.waiting_duration || 'الوقت غير متاح',
    tone: actionTone[item.status] || 'purple',
    product: item.current_product || item.product,
    status: item.status,
  };
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { companyId } = useAuth();
  const { lastEvent, connectionState, lastEventAt } = useGlobalEvents();
  const [queue, setQueue] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [clockNow, setClockNow] = useState(() => Date.now());
  const shownQueueItemsRef = useRef(new Set());

  const loadDashboard = useCallback(async () => {
    if (!companyId) {
      setQueue(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError('');
    try {
      const response = await api.get('/api/v1/copilot/queue');
      const payload = response.data?.data || response.data || {};
      setQueue((payload.items || []).map(toAction));
    } catch {
      setQueue(null);
      setError('تعذّر تحديث قائمة الأولويات. لا تعتمد على حالة قديمة قبل إعادة المحاولة.');
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
    if (['message.received', 'lead.updated', 'lead.created', 'intelligence.updated', 'canonical_commercial.updated'].includes(lastEvent.type)) loadDashboard();
  }, [lastEvent, loadDashboard]);

  const queueAvailable = Array.isArray(queue);
  const priorityItems = useMemo(() => (queue || []).filter((item) => item.status !== 'RESOLVED_TODAY'), [queue]);
  const counts = useMemo(() => ({
    attention: (queue || []).filter((item) => ['NEEDS_ACTION', 'PURCHASE_HANDOFF'].includes(item.status)).length,
    followUp: (queue || []).filter((item) => item.status === 'FOLLOW_UP').length,
    waiting: (queue || []).filter((item) => item.status === 'WAITING_FOR_CUSTOMER').length,
    resolved: (queue || []).filter((item) => item.status === 'RESOLVED_TODAY').length,
  }), [queue]);
  const topActions = priorityItems.slice(0, 6);
  const stream = streamStates[connectionState] || streamStates.idle;
  const today = new Intl.DateTimeFormat('ar-EG', { weekday: 'long', month: 'long', day: 'numeric' }).format(new Date());

  useEffect(() => {
    const newlyRendered = topActions.filter((item) => item.queueItemId && item.leadId && !shownQueueItemsRef.current.has(item.queueItemId));
    if (!newlyRendered.length) return;
    newlyRendered.forEach((item) => shownQueueItemsRef.current.add(item.queueItemId));
    recordProductEvents(newlyRendered.map((item) => ({
      event_name: 'opportunity_shown',
      client_event_id: createClientEventId('dashboard-shown'),
      metadata: { lead_id: item.leadId, queue_item_id: item.queueItemId, surface: 'dashboard' },
    }))).catch(() => {});
  }, [topActions]);

  const openAction = (item) => {
    const openWorkspace = () => {
      if (item.leadId) navigate(`/inbox/${item.leadId}`, { state: { recoveryQueueItemId: item.queueItemId, recoverySurface: 'dashboard' } });
      else navigate('/inbox');
    };
    if (!item.queueItemId || !item.leadId) return openWorkspace();
    recordProductEvents([{
      event_name: 'opportunity_opened',
      client_event_id: createClientEventId('dashboard-opened'),
      metadata: { lead_id: item.leadId, queue_item_id: item.queueItemId, surface: 'dashboard' },
    }]).catch(() => {}).finally(openWorkspace);
  };

  const metricValue = (value) => queueAvailable ? value.toLocaleString('ar-EG') : '—';

  return (
    <div dir="rtl" lang="ar" className="mx-auto w-full max-w-[1420px] space-y-5 p-4 text-right sm:p-5 xl:p-7 2xl:p-8">
      <PageHeader
        eyebrow="ما يحتاج قرارك الآن"
        title={`${getGreeting()} — ابدأ بالمحادثات المهمة.`}
        description={`${today} · راجع سبب الأولوية والدليل قبل الرد أو التصعيد.`}
        badge={<Badge tone={stream.tone} dot={stream.dot}>التحديثات: {stream.label}</Badge>}
        actions={<><Button variant="secondary" onClick={loadDashboard} loading={loading}><RefreshCw className="h-4 w-4" /> تحديث</Button><Button onClick={() => navigate('/inbox')}><MessageSquareText className="h-4 w-4" /> كل المحادثات</Button></>}
      />

      {error && <div className="rounded-xl border border-velor-red/25 bg-velor-red/[0.07] px-4 py-3 text-xs text-[#ffb0bd]" role="alert">{error}</div>}

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="مؤشرات قائمة المتابعة">
        <MetricCard label="تحتاج انتباهك" value={metricValue(counts.attention)} detail="تدخل بشري أو تأكيد طلب" icon={ShieldAlert} tone="red" unavailable={!queueAvailable} />
        <MetricCard label="متابعات مستحقة" value={metricValue(counts.followUp)} detail="التزام متابعة مسجل" icon={Clock3} tone="amber" unavailable={!queueAvailable} />
        <MetricCard label="بانتظار العميل" value={metricValue(counts.waiting)} detail="لا يحتاج ردًا جديدًا الآن" icon={UserRoundCheck} tone="blue" unavailable={!queueAvailable} />
        <MetricCard label="عولجت اليوم" value={metricValue(counts.resolved)} detail="حالة سير عمل، وليست عملية بيع" icon={CheckCircle2} tone="green" unavailable={!queueAvailable} />
      </section>

      <Card className="p-4 sm:p-5">
        <PanelHeader
          eyebrow="قائمة المتابعة"
          title="المحادثات ذات الأولوية"
          description="الترتيب مبني على حالة المحادثة والدليل المحفوظ؛ لا يعرض إيرادًا أو احتمال بيع غير موثّق."
          action={<Button variant="ghost" onClick={() => navigate('/inbox')}>اعرض الكل <ArrowLeft className="h-3.5 w-3.5" /></Button>}
        />

        {!queueAvailable ? (
          <DataStateNotice title="قائمة الأولويات غير متاحة" description="لم يتمكن VELOR من التحقق من الحالة الحالية، لذلك لا يعرض أن كل شيء مكتمل." tone="warning" />
        ) : topActions.length ? (
          <div className="mt-5 overflow-hidden rounded-xl border border-white/[0.07]">
            <div className="hidden grid-cols-[1.05fr_.78fr_1.45fr_auto] gap-4 border-b border-white/[0.07] bg-white/[0.025] px-4 py-2.5 text-[11px] font-bold text-velor-secondary md:grid"><span>المحادثة</span><span>الحالة</span><span>الخطوة المقترحة</span><span /></div>
            <div className="divide-y divide-white/[0.06]">
              {topActions.map((item) => (
                <button key={item.id} type="button" onClick={() => openAction(item)} className="grid w-full gap-2 px-4 py-4 text-right transition hover:bg-white/[0.03] md:grid-cols-[1.05fr_.78fr_1.45fr_auto] md:items-center md:gap-4">
                  <span><span className="block text-xs font-semibold text-white">{item.name}</span><span className="mt-1 block text-[10px] text-velor-muted">{item.channel}{item.product ? ` · ${item.product}` : ''} · {item.time}</span></span>
                  <Badge tone={item.tone}>{item.action}</Badge>
                  <span className="line-clamp-2 text-[11px] leading-5 text-velor-secondary">{item.detail}</span>
                  <ArrowLeft className="hidden h-4 w-4 text-velor-muted md:block" />
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mt-5 rounded-xl border border-white/[0.07] py-14 text-center"><Activity className="mx-auto h-7 w-7 text-velor-muted" /><p className="mt-3 text-sm font-semibold text-white">لا توجد محادثة أولوية موثّقة الآن</p><p className="mx-auto mt-2 max-w-md text-xs leading-5 text-velor-muted">ستظهر هنا محادثة تحتاج تدخلًا أو متابعة عندما تسجل القائمة سببًا قابلًا للمراجعة.</p></div>
        )}
      </Card>

      <Card className="border-velor-purple/15 bg-gradient-to-l from-velor-purple/[0.08] to-transparent p-4 sm:p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-velor-purple/20 bg-velor-purple/10 text-velor-violet"><Sparkles className="h-4 w-4" /></span><div><p className="text-sm font-semibold text-white">داخل مساحة العميل: القرار، الدليل، والرد المقترح</p><p className="mt-1 text-xs leading-5 text-velor-muted">افتح أي محادثة أولوية لمراجعة الحقائق الناقصة أو تولّي المحادثة بدل الاعتماد على تخمين.</p></div></div>
          <span className="shrink-0 text-[10px] text-velor-muted">{lastEventAt ? `آخر تحديث ${formatRelativeTime(lastEventAt, { now: clockNow, locale: 'ar-EG' })}` : 'لم يصل تحديث مباشر في هذه الجلسة'}</span>
        </div>
      </Card>
    </div>
  );
}
