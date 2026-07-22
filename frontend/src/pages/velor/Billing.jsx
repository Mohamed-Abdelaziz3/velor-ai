import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Check,
  CircleDollarSign,
  CreditCard,
  Gauge,
  MessageCircleMore,
  ReceiptText,
  ShieldCheck,
  Sparkles,
  UsersRound,
} from 'lucide-react';
import api from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { Badge, Button, Card, CheckItem, DataStateNotice, PageHeader, PanelHeader, cx } from '../../components/velor/ui';

const plans = [
  {
    id: 'FREE',
    name: 'مجاني',
    description: 'ابدأ بمساحة عمل محدودة لاختبار VELOR على نطاق صغير.',
    messages: '500 رسالة شهريًا',
    leads: '50 عميلًا محتملًا شهريًا',
    knowledge: '4,000 حرف لقاعدة المعرفة',
  },
  {
    id: 'PRO',
    name: 'احترافي',
    description: 'شغّل قناة مبيعات نامية بمساعدة الذكاء الاصطناعي.',
    messages: '10,000 رسالة شهريًا',
    leads: '1,000 عميل محتمل شهريًا',
    knowledge: '8,000 حرف لقاعدة المعرفة',
    highlighted: true,
  },
  {
    id: 'ENTERPRISE',
    name: 'مؤسسات',
    description: 'حدود تشغيل ودعم تُحدَّد حسب احتياج المؤسسة.',
    messages: 'حجم رسائل حسب الاتفاق',
    leads: 'حجم عملاء محتملين حسب الاتفاق',
    knowledge: '15,000 حرف لقاعدة المعرفة',
  },
];

export default function Billing() {
  const navigate = useNavigate();
  const { companyId, plan: authPlan } = useAuth();
  const [currentPlan, setCurrentPlan] = useState(companyId ? authPlan : null);
  const [selectedPlan, setSelectedPlan] = useState(null);

  useEffect(() => {
    if (!companyId) {
      setCurrentPlan(null);
      return;
    }
    api.get('/me').then(({ data }) => {
      setCurrentPlan(data.plan || authPlan || null);
    }).catch(() => {
      setCurrentPlan(authPlan || null);
    });
  }, [authPlan, companyId]);

  const choosePlan = (planId) => {
    if (planId === currentPlan) return;
    setSelectedPlan(planId);
  };

  const currentPlanDetails = plans.find((item) => item.id === currentPlan);

  return (
    <div dir="rtl" lang="ar" className="mx-auto w-full max-w-[1420px] space-y-6 p-4 text-right sm:p-5 xl:p-7">
      <PageHeader
        eyebrow="الباقة والاستخدام"
        title="الاشتراك والفوترة"
        description="اعرف حدود مساحة العمل وحالة تجهيز الفوترة من غير ما نعرض دفعًا أو فواتير غير متصلة فعليًا."
        badge={<Badge tone="neutral">عرض فقط</Badge>}
        actions={<Button variant="secondary" onClick={() => navigate('/settings')}>إعدادات مساحة العمل <ArrowLeft className="h-4 w-4" /></Button>}
      />

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(330px,.65fr)]">
        <Card className="overflow-hidden border-velor-purple/15 bg-gradient-to-bl from-velor-purple/[0.11] via-[#11131d] to-velor-blue/[0.05] p-5 sm:p-6" glow>
          <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2"><Badge tone={currentPlanDetails ? 'green' : 'neutral'} dot={Boolean(currentPlanDetails)}>{currentPlanDetails ? 'محددة لمساحة العمل' : 'تعذّر التحقق'}</Badge><span className="text-[10px] text-velor-muted">الباقة الحالية</span></div>
              <p className="mt-4 text-3xl font-semibold tracking-[-0.04em] text-white">{currentPlanDetails?.name || 'غير متاحة'}</p>
              <p className="mt-2 max-w-lg text-xs leading-5 text-velor-muted">{currentPlanDetails ? 'الخادم بيطبّق حدود الباقة الموضّحة. تحصيل الدفع، وفروق الترقية، والتجديد، وبوابة العميل للفوترة غير متصلة في النسخة الحالية.' : 'مقدرناش نتحقق من باقة مساحة العمل. مش هنعرض حدودًا افتراضية بدل بيانات الحساب الحقيقية.'}</p>
            </div>
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl border border-velor-purple/20 bg-velor-purple/10 text-velor-violet"><CreditCard className="h-5 w-5" /></span>
          </div>
          <div className="mt-6 grid gap-3 sm:grid-cols-3">
            {[
              [MessageCircleMore, currentPlanDetails?.messages || 'غير متاح', 'حد الرسائل'],
              [UsersRound, currentPlanDetails?.leads || 'غير متاح', 'حد العملاء المحتملين'],
              [Gauge, currentPlanDetails?.knowledge || 'غير متاحة', 'سعة قاعدة المعرفة'],
            ].map(([Icon, value, label]) => (
              <div key={label} className="rounded-xl border border-white/[0.08] bg-black/15 p-3.5"><Icon className="h-4 w-4 text-velor-purple" /><p className="metric-numbers mt-3 text-sm font-semibold text-white">{value}</p><p className="mt-1 text-[10px] text-velor-secondary">{label}</p></div>
            ))}
          </div>
        </Card>

        <Card className="p-5 sm:p-6">
          <PanelHeader eyebrow="الاستخدام" title="الدورة الحالية" description="نقطة قياس الاستخدام الحي غير متصلة." />
          <div className="mt-5"><DataStateNotice title="الاستخدام الحي غير متاح" description="الخادم الحالي بيطبّق الحدود، لكنه لسه مش بيعرض للصفحة استخدام الشهر أو بداية ونهاية الدورة أو حالة التجاوز." /></div>
        </Card>
      </section>

      <section>
        <div className="mb-4 flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-end"><div><p className="text-[11px] font-bold text-velor-purple-hi" style={{ color: 'var(--velor-purple-hi)' }}>الباقات</p><h2 className="mt-1 text-lg font-semibold tracking-[-0.03em] text-white">اختار نطاق التشغيل المناسب</h2></div><Badge tone="neutral">الدفع غير متصل</Badge></div>
        <div className="grid gap-4 lg:grid-cols-3">
          {plans.map((item) => {
            const active = item.id === currentPlan;
            return (
              <Card key={item.id} className={cx('relative flex min-h-[310px] flex-col p-5 sm:p-6', item.highlighted && 'border-velor-purple/18 bg-velor-purple/[0.035]')} glow={item.highlighted && !active} interactive>
                {item.highlighted && <Badge tone="purple" className="absolute left-4 top-4"><Sparkles className="h-3 w-3" /> نطاق احترافي</Badge>}
                <span className={cx('flex h-10 w-10 items-center justify-center rounded-xl border', active ? 'border-velor-green/20 bg-velor-green/10 text-velor-green' : 'border-white/[0.08] bg-white/[0.035] text-velor-secondary')}><CircleDollarSign className="h-4 w-4" /></span>
                <h3 className="mt-5 text-xl font-semibold tracking-[-0.03em] text-white">{item.name}</h3>
                <p className="mt-2 min-h-10 text-xs leading-5 text-velor-muted">{item.description}</p>
                <ul className="mt-5 space-y-2.5"><CheckItem>{item.messages}</CheckItem><CheckItem>{item.leads}</CheckItem><CheckItem>{item.knowledge}</CheckItem></ul>
                <Button variant={active ? 'secondary' : item.highlighted ? 'primary' : 'secondary'} onClick={() => choosePlan(item.id)} disabled={active} className="mt-auto w-full">{active ? <><Check className="h-4 w-4 text-velor-green" /> الباقة الحالية</> : `استكشف باقة ${item.name}`}</Button>
              </Card>
            );
          })}
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,.8fr)]">
        <Card className="p-5 sm:p-6">
          <PanelHeader eyebrow="سجل الفوترة" title="الفواتير" description="لا يوجد مزوّد فوترة أو عقد بيانات فواتير متصل." action={<ReceiptText className="h-5 w-5 text-velor-purple" />} />
          <div className="mt-5"><DataStateNotice title="الفواتير غير متاحة" description="تكامل مزوّد الفوترة لازم يكون المصدر الموثوق لأرقام الفواتير وحالاتها وملفات التنزيل والضرائب وحالة الدفع." tone="blue" /></div>
        </Card>

        <Card className="p-5 sm:p-6">
          <PanelHeader eyebrow="وسيلة الدفع" title="جاهزية الفوترة" description="VELOR مش هيختلق بيانات دفع ومش هيخزنها محليًا." action={<ShieldCheck className="h-5 w-5 text-velor-green" />} />
          <div className="mt-5 rounded-xl border border-white/[0.07] bg-white/[0.025] p-4"><div className="flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/[0.04] text-velor-muted"><CreditCard className="h-4 w-4" /></span><div><p className="text-xs font-semibold text-white">لا يوجد مزوّد دفع متصل</p><p className="mt-1 text-[10px] text-velor-muted">إجراءات الدفع وبوابة الفوترة متوقفة.</p></div></div></div>
          <ul className="mt-5 space-y-3"><CheckItem complete={false}>مزوّد دفع آمن</CheckItem><CheckItem complete={false}>بوابة فوترة للعميل</CheckItem><CheckItem complete={false}>إشعارات الفواتير والتجديد من الخادم</CheckItem><CheckItem complete={false}>نقطة استخدام ودورة فوترة</CheckItem></ul>
        </Card>
      </section>

      {selectedPlan && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/75 px-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="plan-dialog" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedPlan(null); }}>
          <Card className="w-full max-w-md border-white/12 bg-[#11131e] p-6 text-center shadow-[0_30px_100px_rgba(0,0,0,.55)] animate-velor-in">
            <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl border border-velor-purple/20 bg-velor-purple/10 text-velor-purple"><CreditCard className="h-5 w-5" /></span>
            <Badge tone="purple" className="mt-4">الفوترة غير متاحة</Badge>
            <h2 id="plan-dialog" className="mt-3 text-lg font-semibold text-white">باقة {plans.find((item) => item.id === selectedPlan)?.name}</h2>
            <p className="mt-2 text-xs leading-5 text-velor-muted">تغيير الباقة يحتاج دفعًا وعقد اشتراك موثوقين. الإجراء متوقف بأمان في النسخة الحالية.</p>
            <Button onClick={() => setSelectedPlan(null)} className="mt-5 w-full">ارجع لصفحة الفوترة</Button>
          </Card>
        </div>
      )}
    </div>
  );
}
