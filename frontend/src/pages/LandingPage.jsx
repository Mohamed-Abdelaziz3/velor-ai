import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowLeft,
  Check,
  ChevronDown,
  CircleAlert,
  FileCheck2,
  Menu,
  MessageSquareText,
  ShieldCheck,
  Sparkles,
  UserRoundCheck,
  X,
} from 'lucide-react';
import { VelorLogo } from '../components/velor/VelorLogo';

const navItems = [
  ['ماذا يفعل VELOR؟', '#product'],
  ['كيف يعمل', '#how'],
  ['مصادر الإجابة', '#evidence'],
  ['حدود واضحة', '#trust'],
];

const coreLoop = [
  {
    icon: CircleAlert,
    title: 'اعرف أين تتدخل',
    detail: 'يرتّب المحادثات التي تنتظر ردًا، أو متابعة، أو قرارًا بشريًا واضحًا.',
  },
  {
    icon: FileCheck2,
    title: 'راجع الرد ودليله',
    detail: 'يعرض مسودة قابلة للتعديل، والحقائق والرسائل التي بُنيت عليها.',
  },
  {
    icon: UserRoundCheck,
    title: 'صعّد بدل التخمين',
    detail: 'إذا نقص سعر أو مخزون أو سياسة، يوضح النقص ويطلب تدخل الفريق.',
  },
];

const workflow = [
  ['01', 'تصل رسالة العميل', 'تدخل المحادثة إلى مساحة العمل من قناة مهيأة.'],
  ['02', 'يظهر القرار مع الدليل', 'ترى سبب الأولوية، المعلومات المعروفة، وما يزال ناقصًا.'],
  ['03', 'يراجع الفريق ويتصرف', 'عدّل الرد وأرسله، أنشئ متابعة، أو تولَّ المحادثة عند عدم اليقين.'],
];

function ProductScene() {
  return (
    <div className="relative mx-auto max-w-[640px] rounded-[1.5rem] border border-white/[0.11] bg-[#111324] p-3 shadow-[0_28px_90px_rgba(0,0,0,.42)]" aria-label="مثال لمساحة عمل VELOR">
      <div className="flex items-center justify-between border-b border-white/[0.08] px-3 pb-3 text-[10px] text-velor-muted">
        <span className="font-semibold text-white">مساحة المتابعة</span>
        <span className="rounded-full bg-amber-400/10 px-2 py-1 text-amber-200">تحتاج انتباهك</span>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-[.86fr_1.2fr]">
        <div className="rounded-xl border border-white/[0.07] bg-black/15 p-3">
          <p className="text-[9px] font-bold tracking-[.14em] text-velor-muted">الأولوية الآن</p>
          <div className="mt-3 rounded-lg border border-amber-300/20 bg-amber-300/[.06] p-2.5">
            <p className="text-[11px] font-bold text-white">عميلة تنتظر معلومة مؤكدة</p>
            <p className="mt-1 text-[10px] leading-5 text-velor-secondary">سألت عن التوافر والتوصيل، والسياسة لا تحتوي إجابة كاملة.</p>
          </div>
          <div className="mt-2 rounded-lg border border-white/[.07] p-2.5">
            <p className="text-[9px] font-semibold text-velor-violet">الإجراء المقترح</p>
            <p className="mt-1 text-[10px] leading-5 text-white">تأكيد التوافر أولًا، ثم الرد.</p>
          </div>
        </div>
        <div className="rounded-xl border border-white/[0.07] bg-white/[.025] p-3">
          <div className="flex items-center justify-between">
            <p className="text-[9px] font-bold tracking-[.14em] text-velor-muted">رد مقترح للمراجعة</p>
            <span className="text-[9px] text-amber-200">معلومة ناقصة</span>
          </div>
          <div className="mt-3 rounded-xl border border-velor-purple/25 bg-velor-purple/[.08] p-2.5">
            <p className="text-[11px] leading-5 text-velor-secondary">أراجع التوافر المسجل قبل ما أأكد لك. رسوم التوصيل للقاهرة موثقة في سياسة الشحن.</p>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 text-[9px]">
            <div className="rounded-lg border border-emerald-300/15 bg-emerald-300/[.05] p-2 text-emerald-100"><b className="block">دليل متاح</b>سياسة التوصيل</div>
            <div className="rounded-lg border border-amber-300/15 bg-amber-300/[.05] p-2 text-amber-100"><b className="block">يحتاج تحققًا</b>المخزون الحالي</div>
          </div>
          <div className="mt-2 flex gap-2"><span className="rounded-md bg-white/[.07] px-2 py-1 text-[9px] text-white">راجع الدليل</span><span className="rounded-md bg-velor-purple px-2 py-1 text-[9px] font-semibold text-white">تولَّ المحادثة</span></div>
        </div>
      </div>
    </div>
  );
}

export default function LandingPage() {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="min-h-screen overflow-x-hidden bg-velor-bg text-velor-text" dir="rtl">
      <header className="sticky top-0 z-50 border-b border-white/[.06] bg-velor-bg/90 backdrop-blur-xl">
        <nav className="mx-auto flex h-[72px] max-w-[1200px] items-center justify-between px-4 sm:px-6" aria-label="التنقل الرئيسي">
          <Link to="/" aria-label="VELOR الصفحة الرئيسية"><VelorLogo size={32} wordmarkClassName="text-base" className="text-white" /></Link>
          <div className="hidden items-center gap-7 md:flex">{navItems.map(([label, href]) => <a key={href} href={href} className="text-xs font-semibold text-velor-muted transition hover:text-white">{label}</a>)}</div>
          <div className="hidden items-center gap-4 md:flex"><Link to="/login" className="text-xs font-semibold text-velor-secondary hover:text-white">تسجيل الدخول</Link><Link to="/signup" className="velor-button-primary min-h-10 px-4 text-xs">ابدأ مساحة عملك <ArrowLeft className="h-3.5 w-3.5" /></Link></div>
          <button type="button" className="rounded-lg p-2 text-white md:hidden" aria-label="فتح القائمة" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? <X /> : <Menu />}</button>
        </nav>
        {menuOpen && <div className="border-t border-white/[.06] px-4 py-4 md:hidden"><div className="mx-auto grid max-w-[1200px] gap-3">{navItems.map(([label, href]) => <a key={href} onClick={() => setMenuOpen(false)} href={href} className="rounded-lg px-3 py-2 text-sm text-velor-secondary hover:bg-white/[.04]">{label}</a>)}<Link to="/login" className="px-3 py-2 text-sm text-velor-secondary">تسجيل الدخول</Link><Link to="/signup" className="velor-button-primary mt-1 text-sm">ابدأ مساحة عملك</Link></div></div>}
      </header>

      <main>
        <section className="relative isolate px-4 pb-16 pt-16 sm:px-6 sm:pb-24 sm:pt-24">
          <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[520px] bg-[radial-gradient(ellipse_at_70%_0%,rgba(139,92,246,.18),transparent_55%)]" />
          <div className="mx-auto grid max-w-[1200px] items-center gap-12 lg:grid-cols-[.92fr_1.08fr]">
            <div>
              <p className="inline-flex items-center gap-2 rounded-full border border-velor-purple/25 bg-velor-purple/[.07] px-3 py-1.5 text-[11px] font-semibold text-violet-200"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />مساعد قرار لمحادثات المبيعات</p>
              <h1 className="mt-6 max-w-2xl text-4xl font-extrabold leading-[1.18] tracking-[-.045em] text-white sm:text-5xl lg:text-[56px]">اعرف المحادثات التي تحتاج انتباهك. <span className="velor-glow-text-purple">وردّ بدليل.</span></h1>
              <p className="mt-6 max-w-xl text-base leading-8 text-velor-secondary sm:text-lg">VELOR يحدد محادثات البيع المهمة، يقترح ردودًا مبنية على الكتالوج والسياسات والمحادثة، ويصعّد عدم اليقين بدل ما يخمّن.</p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row"><Link to="/signup" id="hero-primary-cta" className="velor-button-primary min-h-[52px] px-6 text-sm">ابدأ مساحة عملك <ArrowLeft className="h-4 w-4" /></Link><a href="#how" className="velor-button-secondary min-h-[52px] px-6 text-sm">شاهد سير العمل <ChevronDown className="h-4 w-4" /></a></div>
              <div className="mt-7 flex flex-wrap gap-x-5 gap-y-2 text-[11px] text-velor-muted"><span className="inline-flex items-center gap-1.5"><Check className="h-3.5 text-emerald-400" />الردود قابلة للمراجعة والتعديل</span><span className="inline-flex items-center gap-1.5"><Check className="h-3.5 text-emerald-400" />المعلومة الناقصة تظهر بوضوح</span></div>
            </div>
            <ProductScene />
          </div>
        </section>

        <section id="product" className="scroll-mt-20 border-y border-white/[.06] bg-white/[.015] px-4 py-16 sm:px-6 sm:py-20">
          <div className="mx-auto max-w-[1200px]"><div className="max-w-2xl"><p className="text-xs font-bold tracking-[.16em] text-velor-violet">مهمة واحدة واضحة</p><h2 className="mt-3 text-3xl font-bold tracking-[-.04em] text-white sm:text-4xl">من زحمة المحادثات إلى قرار قابل للتنفيذ.</h2></div><div className="mt-9 grid gap-3 md:grid-cols-3">{coreLoop.map(({ icon: Icon, title, detail }) => <article key={title} className="rounded-2xl border border-white/[.07] bg-black/10 p-5"><Icon className="h-5 w-5 text-velor-violet" /><h3 className="mt-5 text-base font-bold text-white">{title}</h3><p className="mt-2 text-sm leading-7 text-velor-muted">{detail}</p></article>)}</div></div>
        </section>

        <section id="how" className="scroll-mt-20 px-4 py-20 sm:px-6 sm:py-24">
          <div className="mx-auto max-w-[1200px]"><div className="max-w-2xl"><p className="text-xs font-bold tracking-[.16em] text-velor-violet">سير العمل</p><h2 className="mt-3 text-3xl font-bold tracking-[-.04em] text-white sm:text-4xl">رسالة، دليل، ثم قرار الفريق.</h2><p className="mt-4 text-sm leading-7 text-velor-secondary">كل خطوة تبقى مرتبطة بالمحادثة الحالية. لو وصلت رسالة أحدث، لا تُستخدم مسودة قديمة خارج سياقها.</p></div><div className="mt-9 grid gap-3 md:grid-cols-3">{workflow.map(([number, title, detail]) => <article key={number} className="velor-card p-5"><span className="text-[11px] font-bold text-velor-violet">{number}</span><h3 className="mt-7 text-base font-bold text-white">{title}</h3><p className="mt-2 text-sm leading-6 text-velor-muted">{detail}</p></article>)}</div></div>
        </section>

        <section id="evidence" className="scroll-mt-20 border-y border-white/[.06] bg-white/[.015] px-4 py-20 sm:px-6 sm:py-24">
          <div className="mx-auto grid max-w-[1200px] gap-8 lg:grid-cols-[.9fr_1.1fr] lg:items-center">
            <div><p className="text-xs font-bold tracking-[.16em] text-emerald-300">سياق قابل للمراجعة</p><h2 className="mt-3 text-3xl font-bold tracking-[-.04em] text-white sm:text-4xl">الكتالوج والسياسات والمحادثة هي مصدر الإجابة.</h2><p className="mt-5 text-sm leading-7 text-velor-secondary">يعرض VELOR الحقائق المعروفة، الرسائل المصدرية، والمعلومة الناقصة بجوار الإجراء والرد المقترح. لا تُعرض نتيجة تقييم اصطناعي كأنها نتيجة عميل.</p></div>
            <div className="grid gap-3 sm:grid-cols-3">{[['الكتالوج','السعر والمنتج والخصائص المسجلة.'],['السياسات','التوصيل والاسترجاع والضمان المرفوع.'],['المحادثة','آخر طلب للعميل وسياق الرسائل المحفوظ.']].map(([title, detail]) => <div key={title} className="rounded-2xl border border-white/[.08] bg-[#111326]/80 p-5"><ShieldCheck className="h-5 w-5 text-emerald-300" /><h3 className="mt-6 text-sm font-bold text-white">{title}</h3><p className="mt-2 text-xs leading-6 text-velor-muted">{detail}</p></div>)}</div>
          </div>
        </section>

        <section id="trust" className="scroll-mt-20 px-4 py-20 sm:px-6 sm:py-24">
          <div className="mx-auto grid max-w-[1200px] gap-8 lg:grid-cols-2">
            <article className="velor-panel p-6 sm:p-8"><MessageSquareText className="h-6 w-6 text-velor-violet" /><h2 className="mt-6 text-2xl font-bold text-white">رد مقترح، وليس حقيقة جديدة.</h2><p className="mt-4 text-sm leading-7 text-velor-secondary">فريقك يراجع المسودة والدليل قبل الإرسال، وحالة التسليم تظهر كما أبلغ بها النظام.</p></article>
            <article className="velor-panel p-6 sm:p-8"><UserRoundCheck className="h-6 w-6 text-amber-300" /><h2 className="mt-6 text-2xl font-bold text-white">عند الشك، ينتقل القرار للإنسان.</h2><p className="mt-4 text-sm leading-7 text-velor-secondary">السعر أو المخزون أو السياسة غير الموثقة تبقى غير معروفة، مع خطوة واضحة لجمع المعلومة أو تولّي المحادثة.</p></article>
          </div>
        </section>

        <section className="px-4 pb-20 pt-4 sm:px-6 sm:pb-28">
          <div className="relative mx-auto max-w-[960px] overflow-hidden rounded-[2rem] border border-velor-purple/25 bg-[radial-gradient(circle_at_75%_0%,rgba(139,92,246,.25),transparent_45%),#141328] px-6 py-12 text-center sm:px-12 sm:py-16"><Sparkles className="mx-auto h-6 w-6 text-violet-200" /><h2 className="mx-auto mt-6 max-w-2xl text-3xl font-bold tracking-[-.04em] text-white sm:text-4xl">ابدأ بالمحادثات التي تحتاج قرارًا.</h2><p className="mx-auto mt-4 max-w-xl text-sm leading-7 text-velor-secondary">أنشئ مساحة عمل وابدأ عبر Web Chat، ثم راجع الأولويات والأدلة والردود المقترحة من مكان واحد.</p><Link to="/signup" id="final-primary-cta" className="velor-button-primary mt-8 min-h-[52px] px-7 text-sm">ابدأ مساحة عملك <ArrowLeft className="h-4 w-4" /></Link></div>
        </section>
      </main>

      <footer className="border-t border-white/[.06] px-4 py-10 sm:px-6"><div className="mx-auto flex max-w-[1200px] flex-col gap-6 text-center sm:flex-row sm:items-center sm:justify-between sm:text-right"><div><VelorLogo size={28} wordmarkClassName="text-sm" className="text-white" /><p className="mt-2 text-[10px] text-velor-muted">قرارات أوضح لمحادثات المبيعات.</p></div><div className="flex flex-wrap justify-center gap-x-5 gap-y-2 text-[11px] font-semibold text-velor-muted"><a href="#product">المنتج</a><Link to="/terms">الشروط</Link><Link to="/privacy">الخصوصية</Link><Link to="/login">تسجيل الدخول</Link><Link to="/signup">إنشاء مساحة عمل</Link></div><p className="text-[10px] text-velor-muted">© {new Date().getFullYear()} VELOR</p></div></footer>
      <div className="fixed inset-x-3 bottom-3 z-40 rounded-xl border border-white/[.1] bg-[#15162b]/95 p-2 shadow-2xl backdrop-blur md:hidden"><Link to="/signup" className="velor-button-primary flex min-h-11 w-full text-sm">ابدأ مساحة عملك <ArrowLeft className="h-4 w-4" /></Link></div>
    </div>
  );
}
