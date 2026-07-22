import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  Check,
  CheckCheck,
  CircleAlert,
  Clock3,
  ExternalLink,
  Filter,
  MessageCircleMore,
  Search,
  ShieldCheck,
  Sparkles,
  Wifi,
  Zap,
} from 'lucide-react';
import toast from 'react-hot-toast';
import { getConversations, getLeads } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { useGlobalEvents } from '../../contexts/GlobalEventContext';
import { Badge, Button, Card, SegmentedControl, cx } from '../../components/velor/ui';
import { formatClockTime, formatDateSeparator, formatRelativeTime, groupMessagesByDate } from '../../utils/timeUtils';

const INTERNAL_SUMMARY_PATTERN = /(?:V2\s+trace\s+path|response_path|provider_unconfigured|fallback\s+analysis|decision_json)/i;

const streamStates = {
  connected: { label: 'متصل', tone: 'green', detail: 'تدفق الأحداث متصل' },
  connecting: { label: 'جاري الاتصال', tone: 'blue', detail: 'جاري فتح تدفق الأحداث' },
  reconnecting: { label: 'إعادة اتصال', tone: 'amber', detail: 'انقطع تدفق الأحداث مؤقتًا' },
  disconnected: { label: 'غير متصل', tone: 'red', detail: 'تدفق الأحداث غير متصل' },
  idle: { label: 'غير متصل', tone: 'neutral', detail: 'تدفق الأحداث غير مفعّل' },
};

function initials(name = '') {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || 'ع';
}

const STAGE_LABELS = {
  NEW: 'جديد',
  OPEN: 'مفتوح',
  INFORMATION_GATHERING: 'جمع المعلومات',
  QUALIFIED: 'مؤهل',
  INTERESTED: 'مهتم',
  NEGOTIATION: 'تفاوض',
  PURCHASE_HANDOFF: 'جاهز لإتمام الشراء',
  FOLLOW_UP: 'متابعة',
  WAITING_FOR_CUSTOMER: 'بانتظار العميل',
  WON: 'تم التحويل',
  CONVERTED: 'تم التحويل',
  LOST: 'لم يكتمل',
  CLOSED: 'مغلق',
  RESOLVED: 'مغلق',
};

function getStageLabel(value) {
  const raw = String(value || '').trim();
  if (!raw) return 'غير موثقة';
  const normalized = raw.replace(/[\s-]+/g, '_').toUpperCase();
  if (STAGE_LABELS[normalized]) return STAGE_LABELS[normalized];
  return /[\u0600-\u06FF]/.test(raw) ? raw : 'غير موثقة';
}

function getContactIdentifier(lead) {
  return lead.contact_identifier || lead.external_customer_id || null;
}

function getChannelLabel(lead) {
  const channelType = String(lead.channel_type || '').toUpperCase();
  if (channelType.includes('WEB_CHAT')) return 'دردشة الموقع';
  if (channelType.includes('WHATSAPP')) return 'واتساب';
  if (lead.channel === 'Web chat') return 'دردشة الموقع';
  if (lead.channel === 'WhatsApp') return 'واتساب';
  return 'القناة غير موثقة';
}

function sanitizeSummary(value) {
  if (typeof value !== 'string') return null;
  const summary = value.trim();
  if (!summary || INTERNAL_SUMMARY_PATTERN.test(summary)) return null;
  return summary;
}

function mapLead(lead) {
  const contactIdentifier = getContactIdentifier(lead);
  const name = lead.name || (lead.id ? `زائر ${lead.id}` : 'عميل غير معروف');
  return {
    id: lead.id,
    name,
    initials: initials(name),
    channel: getChannelLabel(lead),
    contactIdentifier,
    message: lead.last_message_preview || lead.last_message || 'لا توجد معاينة رسالة متاحة',
    lastContactAt: lead.last_contact_date || null,
    stage: getStageLabel(lead.stage || lead.status),
    status: lead.needs_human_intervention ? 'risk' : lead.is_hot_deal ? 'hot' : lead.temperature || 'warm',
    isPaused: Boolean(lead.is_paused),
    summary: sanitizeSummary(lead.ai_summary),
    interest: lead.interest,
    raw: lead,
  };
}

function mapMessage(message) {
  const rawSender = String(message.sender || '').toLowerCase();
  const sender = ['assistant', 'bot'].includes(rawSender) ? 'ai' : ['owner', 'team', 'agent'].includes(rawSender) ? 'team' : 'customer';
  const timestamp = message.created_at || message.date || message.timestamp || null;
  return {
    id: message.id || message.internal_message_id || `${message.created_at}-${message.message}`,
    sender,
    text: message.message,
    timestamp,
    status: String(message.delivery_status || message.status || '').toLowerCase(),
  };
}

function DeliveryStatus({ status }) {
  const states = {
    pending: { label: 'قيد الإرسال', Icon: Clock3, className: 'text-velor-muted' },
    sent: { label: 'تم الإرسال', Icon: Check, className: 'text-velor-muted' },
    delivered: { label: 'تم التسليم', Icon: CheckCheck, className: 'text-velor-blue' },
    read: { label: 'تمت القراءة', Icon: CheckCheck, className: 'text-velor-green' },
    failed: { label: 'فشل الإرسال', Icon: CircleAlert, className: 'text-velor-red' },
  };
  const state = states[status];
  if (!state) return null;
  const { Icon } = state;
  return <span className={state.className} title={state.label}><Icon className="h-3 w-3" /><span className="sr-only">{state.label}</span></span>;
}

function Avatar({ conversation, size = 'md' }) {
  return (
    <span className={cx('flex shrink-0 items-center justify-center rounded-xl border border-white/[0.08] bg-gradient-to-br from-velor-purple/25 to-velor-blue/10 font-semibold text-[#e5d8ff]', size === 'lg' ? 'h-11 w-11 text-xs' : 'h-9 w-9 text-[10px]')}>
      {conversation.initials}
    </span>
  );
}

export default function Inbox() {
  const navigate = useNavigate();
  const { companyId } = useAuth();
  const { lastEvent, connectionState, lastEventAt } = useGlobalEvents();
  const [conversations, setConversations] = useState([]);
  const [conversationTotal, setConversationTotal] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messageError, setMessageError] = useState('');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [mobileDetail, setMobileDetail] = useState(false);
  const [clockNow, setClockNow] = useState(() => Date.now());
  const messagesEndRef = useRef(null);

  const selected = conversations.find((conversation) => String(conversation.id) === String(selectedId)) || (!selectedId ? conversations[0] : null) || null;
  const stream = streamStates[connectionState] || streamStates.idle;
  const messageGroups = useMemo(() => groupMessagesByDate(messages), [messages]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, selectedId]);

  const loadLeads = useCallback(async () => {
    if (!companyId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const { data } = await getLeads(companyId, 1, 100);
      const mapped = (data.leads || []).map(mapLead);
      setConversations(mapped);
      const total = Number(data.total);
      setConversationTotal(Number.isFinite(total) ? total : mapped.length);
      setSelectedId((current) => current && mapped.some((item) => String(item.id) === String(current)) ? current : mapped[0]?.id || null);
    } catch {
      toast.error('تعذر تحديث المحادثات الآن.');
    } finally {
      setLoading(false);
    }
  }, [companyId]);

  const loadMessages = useCallback(async (conversation) => {
    if (!conversation) return;
    if (!conversation.contactIdentifier) {
      setMessages([]);
      setMessageError('سجل المحادثة غير متاح لأن هذا العميل لا يملك معرّف تواصل موثوقًا داخل مساحة العمل.');
      return;
    }
    setMessageError('');
    try {
      const { data } = await getConversations(companyId, 1, 100, conversation.contactIdentifier);
      setMessages((data.conversations || []).map(mapMessage).reverse());
    } catch {
      setMessages([]);
      setMessageError('تعذر تحميل سجل المحادثة لهذا العميل.');
    }
  }, [companyId]);

  useEffect(() => { loadLeads(); }, [loadLeads]);
  useEffect(() => { loadMessages(selected); }, [loadMessages, selected]);
  useEffect(() => {
    const interval = setInterval(() => setClockNow(Date.now()), 60_000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!lastEvent) return;
    if (['message.received', 'message.sent', 'message.updated', 'lead.updated', 'lead.created'].includes(lastEvent.type)) {
      loadLeads();
    }
  }, [lastEvent, loadLeads]);

  const filtered = useMemo(() => conversations.filter((conversation) => {
    const matchesSearch = `${conversation.name} ${conversation.message} ${conversation.contactIdentifier || ''}`.toLowerCase().includes(query.toLowerCase());
    const matchesFilter = filter === 'all' || (filter === 'hot' && ['hot', 'risk'].includes(conversation.status));
    return matchesSearch && matchesFilter;
  }), [conversations, filter, query]);

  const selectConversation = (conversation) => {
    setSelectedId(conversation.id);
    setMobileDetail(true);
  };

  const openWorkspace = () => {
    if (!selected?.id) return;
    navigate(`/inbox/${selected.id}`);
  };

  return (
    <div className="flex h-full w-full min-h-0 flex-1 flex-col p-3 sm:p-4 xl:p-5" dir="rtl" lang="ar">
      <div className="mx-auto grid h-full w-full min-h-0 max-w-[1620px] flex-1 overflow-hidden rounded-[1.25rem] border border-white/[0.075] bg-[#0d0f18]/94 shadow-[0_24px_80px_rgba(0,0,0,.3)] xl:grid-cols-[330px_minmax(460px,1fr)_318px]">
        <aside className={cx('flex flex-col h-full min-h-0 min-w-0 border-l border-white/[0.07] bg-[#0b0d15]', mobileDetail ? 'hidden xl:flex' : 'flex')}>
          <div className="shrink-0 border-b border-white/[0.07] p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-white">المحادثات</p>
                <p className="mt-0.5 text-[10px] text-velor-muted">{conversationTotal === null ? `تم تحميل ${conversations.length}` : `نعرض ${conversations.length} من ${conversationTotal}`}</p>
              </div>
            </div>
            <div className="relative mt-4">
              <Search className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-velor-muted" />
              <input value={query} onChange={(event) => setQuery(event.target.value)} className="velor-input h-10 min-h-10 px-9 text-xs" placeholder="ابحث في المحادثات…" aria-label="البحث في المحادثات" />
              <Filter className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-velor-muted" />
            </div>
            <SegmentedControl value={filter} onChange={setFilter} options={[{ value: 'all', label: 'الكل' }, { value: 'hot', label: 'الأولوية' }]} className="mt-3 w-full [&>button]:flex-1" />
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto p-2" aria-label="قائمة المحادثات">
            {loading && <div className="flex h-28 items-center justify-center"><span className="h-5 w-5 animate-spin rounded-full border-2 border-white/10 border-t-velor-purple" /></div>}
            {!loading && filtered.map((conversation) => {
              const active = selected?.id === conversation.id;
              return (
                <button key={conversation.id} type="button" onClick={() => selectConversation(conversation)} className={cx('group relative flex w-full items-start gap-3 rounded-xl border p-3 text-right transition', active ? 'border-velor-purple/20 bg-velor-purple/[0.07]' : 'border-transparent hover:border-white/[0.06] hover:bg-white/[0.03]')} aria-pressed={active}>
                  {active && <span className="absolute -right-0.5 top-4 h-7 w-0.5 rounded-full bg-velor-purple shadow-[0_0_10px_rgba(155,92,255,.7)]" />}
                  <Avatar conversation={conversation} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-2"><span className="truncate text-xs font-semibold text-white">{conversation.name}</span><span className="shrink-0 text-[9px] text-velor-muted">{conversation.lastContactAt ? formatRelativeTime(conversation.lastContactAt, { now: clockNow, locale: 'ar-EG' }) : '—'}</span></span>
                    <span className="mt-1 flex items-center gap-1.5"><Badge tone={conversation.channel === 'واتساب' ? 'green' : conversation.channel === 'دردشة الموقع' ? 'blue' : 'neutral'} className="px-1.5 py-0.5 text-[8px]">{conversation.channel}</Badge><span className="text-[9px] text-velor-muted">{conversation.stage}</span></span>
                    <span className="mt-1.5 block truncate text-[10px] text-velor-muted">{conversation.message}</span>
                  </span>
                </button>
              );
            })}
            {!loading && !filtered.length && <div className="py-12 text-center"><MessageCircleMore className="mx-auto h-6 w-6 text-velor-muted" /><p className="mt-3 text-xs text-velor-secondary">لا توجد محادثات مطابقة</p></div>}
          </div>
        </aside>

        <section className={cx('relative flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-[#10121b]', !mobileDetail && 'hidden xl:flex')}>
          {selected ? (
            <>
              <header className="flex h-[74px] shrink-0 items-center justify-between gap-3 border-b border-white/[0.07] px-4">
                <div className="flex min-w-0 items-center gap-3">
                  <button type="button" onClick={() => setMobileDetail(false)} className="flex h-9 w-9 items-center justify-center rounded-lg text-velor-muted hover:bg-white/5 hover:text-white xl:hidden" aria-label="الرجوع إلى المحادثات"><ArrowRight className="h-4 w-4" /></button>
                  <Avatar conversation={selected} size="lg" />
                  <div className="min-w-0"><p className="truncate text-sm font-semibold text-white">{selected.name}</p><p className="mt-0.5 truncate text-[10px] text-velor-muted">{selected.channel} · {selected.contactIdentifier || 'معرّف التواصل غير متاح'}</p></div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge tone={selected.isPaused ? 'amber' : 'neutral'} className="hidden sm:inline-flex">{selected.isPaused ? 'المحادثة تحت الإدارة اليدوية' : 'VELOR يدير المحادثة'}</Badge>
                  <Badge tone="neutral">معاينة للقراءة فقط</Badge>
                </div>
              </header>

              <div className="flex-1 min-h-0 overflow-y-auto px-4 py-5 sm:px-6">
                <div className="mx-auto max-w-[760px] space-y-4">
                  {messageGroups.map((group) => (
                    <Fragment key={group.key}>
                      <div className="flex items-center gap-3 py-2 text-[10px] text-velor-muted"><span className="h-px flex-1 bg-white/[0.06]" />{group.timestamp ? formatDateSeparator(group.timestamp, { now: clockNow, locale: 'ar-EG' }) : 'التاريخ غير متاح'}<span className="h-px flex-1 bg-white/[0.06]" /></div>
                      {group.items.map((message) => (
                        <div key={message.id} className={cx('flex', message.sender === 'customer' ? 'justify-start' : 'justify-end')}>
                          <div className={cx('max-w-[84%]', message.sender === 'ai' && 'w-full max-w-[88%]')}>
                            {message.sender === 'ai' && <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold text-velor-purple-hi" style={{ color: 'var(--velor-purple-hi)' }}><Sparkles className="h-3 w-3" /> VELOR</div>}
                            <div className={cx('rounded-2xl px-4 py-3 text-xs leading-5', message.sender === 'customer' ? 'rounded-br-md border border-white/[0.07] bg-white/[0.045] text-velor-secondary' : message.sender === 'team' ? 'rounded-bl-md bg-velor-blue/12 text-white ring-1 ring-velor-blue/20' : 'rounded-bl-md border border-velor-purple/15 bg-velor-purple/[0.075] text-white')}>
                              {message.text}
                            </div>
                            <div className={cx('mt-1.5 flex items-center gap-1 text-[10px] text-velor-muted', message.sender !== 'customer' && 'justify-end')}>
                              {message.insight && <span className="mr-auto inline-flex items-center gap-1 text-velor-purple"><ShieldCheck className="h-3 w-3" /> {message.insight}</span>}
                              <span>{message.timestamp ? formatClockTime(message.timestamp, 'ar-EG') : ''}</span>
                              {message.sender !== 'customer' && <DeliveryStatus status={message.status} />}
                            </div>
                          </div>
                        </div>
                      ))}
                    </Fragment>
                  ))}
                  {!messages.length && <div className="py-20 text-center"><MessageCircleMore className="mx-auto h-8 w-8 text-velor-muted" /><p className="mt-3 text-xs text-velor-secondary">لا يوجد سجل رسائل متاح</p><p className="mx-auto mt-1 max-w-sm text-[10px] leading-4 text-velor-muted">{messageError || 'لا توجد رسائل محفوظة لهذه المحادثة حتى الآن.'}</p></div>}
                  <div ref={messagesEndRef} />
                </div>
              </div>

              <footer className="shrink-0 border-t border-white/[0.07] bg-[#0d0f18]/95 p-3 sm:p-4">
                <div className="mx-auto flex max-w-[760px] flex-col gap-3 rounded-2xl border border-white/[0.09] bg-black/20 p-3 sm:flex-row sm:items-center sm:justify-between">
                  <div><p className="text-xs font-semibold text-white">هذه معاينة للقراءة فقط</p><p className="mt-1 text-[10px] leading-4 text-velor-muted">افتح مساحة العميل للرد أو تولّي المحادثة أو مراجعة الأدلة أو إعادة التحكم إلى VELOR.</p></div>
                  <Button variant="secondary" onClick={openWorkspace} className="shrink-0 text-[11px]">فتح مساحة العميل <ExternalLink className="h-3.5 w-3.5" /></Button>
                </div>
              </footer>
            </>
          ) : <div className="flex h-full items-center justify-center text-xs text-velor-muted">اختر محادثة لعرضها.</div>}
        </section>

        <aside className="hidden h-full min-h-0 min-w-0 overflow-y-auto border-r border-white/[0.07] bg-[#0b0d15] xl:block">
          {selected && (
            <div className="space-y-4 p-4">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold text-white">معلومات المحادثة</p>
                <span className="flex items-center gap-1 text-[10px] font-medium text-velor-muted">
                  <span className={cx(
                    "h-1.5 w-1.5 rounded-full",
                    connectionState === 'connected' ? "bg-[#34d399] animate-pulse" : "bg-red-500"
                  )} />
                  {stream.label}
                </span>
              </div>
              <Card className="p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0"><p className="text-[10px] font-bold tracking-[0.12em] text-velor-muted">مرحلة المتابعة</p><p className="mt-1 text-sm font-semibold text-white">{selected.stage}</p><p className="mt-1 text-[10px] leading-4 text-velor-muted">حالة مسجلة في سير العمل، وليست نسبة احتمال.</p></div>
                  <span className={cx(
                    "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[10px] font-semibold leading-none",
                    selected.status === 'risk' ? "border-red-500/25 bg-red-500/[0.04] text-red-300" : selected.status === 'hot' ? "border-purple-500/25 bg-purple-500/[0.04] text-purple-300" : "border-white/10 bg-white/[0.02] text-velor-muted"
                  )}>
                    <span className={cx(
                      "h-1.5 w-1.5 rounded-full",
                      selected.status === 'risk' ? "bg-red-400" : selected.status === 'hot' ? "bg-purple-400" : "bg-velor-muted"
                    )} />
                    <span>{selected.status === 'risk' ? 'يحتاج تدخلًا' : selected.status === 'hot' ? 'إشارة أولوية' : 'لا توجد أولوية موثقة'}</span>
                  </span>
                </div>
              </Card>

              <Card className="p-4">
                <p className="text-[10px] font-bold tracking-[0.14em] text-velor-purple">ملخص العميل</p>
                <p className="mt-3 text-xs leading-5 text-velor-secondary">{selected.summary || 'لا يوجد ملخص موثق وآمن للعميل في هذه المحادثة حتى الآن.'}</p>
              </Card>

              <Card className="p-4">
                <div className="flex items-center justify-between"><p className="text-xs font-semibold text-white">الحقائق المعروفة</p><ShieldCheck className="h-4 w-4 text-velor-green" /></div>
                <dl className="mt-3 space-y-3 text-[11px]">
                  <div className="flex justify-between gap-3"><dt className="text-velor-muted">القناة</dt><dd className="font-medium text-velor-secondary">{selected.channel}</dd></div>
                  <div className="flex justify-between gap-3"><dt className="text-velor-muted">الاهتمام</dt><dd className="max-w-[150px] text-left font-medium text-velor-secondary">{selected.interest || 'غير موثق'}</dd></div>
                  <div className="flex justify-between gap-3"><dt className="text-velor-muted">المرحلة</dt><dd className="font-medium text-velor-secondary">{selected.stage}</dd></div>
                </dl>
              </Card>

              <Card className="border-velor-purple/15 bg-velor-purple/[0.055] p-4">
                <div className="flex items-center gap-2 text-xs font-semibold text-white"><Zap className="h-4 w-4 text-velor-purple" /> الخطوة التالية</div>
                <p className="mt-2 text-[11px] leading-5 text-velor-secondary">افتح مساحة العميل المبنية على الأدلة لمراجعة الإجراء المقترح.</p>
              </Card>

              <div className="flex items-center justify-between gap-3 rounded-xl border border-white/[0.06] bg-white/[0.025] px-3 py-2.5 text-[10px] text-velor-muted"><span className="inline-flex items-center gap-1.5"><Wifi className={cx('h-3.5 w-3.5', connectionState === 'connected' ? 'text-velor-green' : connectionState === 'disconnected' ? 'text-velor-red' : 'text-velor-muted')} /> {stream.detail}</span><span className="shrink-0">{lastEventAt ? `آخر حدث ${formatRelativeTime(lastEventAt, { now: clockNow, locale: 'ar-EG' })}` : 'لم يصل أي حدث'}</span></div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
