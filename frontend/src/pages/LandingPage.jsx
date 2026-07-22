import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowLeft, Check, ChevronDown, CircleAlert, Clock3, Eye,
  Menu, MoveLeft, ShieldCheck, Sparkles, Target,
  UserRoundCheck, X,
} from 'lucide-react';
import { VelorLogo } from '../components/velor/VelorLogo';

const navItems = [
  ['المنتج', '#product'], ['كيف يعمل', '#how'], ['استرداد الإيراد', '#recovery'], ['الثقة', '#trust'],
];

const leakage = [
  ['عميل سأل عن السعر', 'والمحادثة اتدفنت قبل ما حد يرد.'],
  ['مشتري جاهز', 'مستني معلومة شحن أو توافر.'],
  ['وعد بمتابعة', 'اتأجل واتنسي وسط الشاتات.'],
  ['موقف يحتاج قرار', 'اتساب من غير ما يوصل للمالك.'],
];

const workflow = [
  ['01', 'اربط المحادثات', 'ابدأ بـ Web Chat، واصنع مساحة عمل مرتبة لفريقك.'],
  ['02', 'التقط الإشارة', 'VELOR يحدد سؤال سعر، نية شراء، اعتراض، أو معلومة ناقصة.'],
  ['03', 'رتّب القرار', 'افتح المحادثات التي تحتاج تدخلاً الآن، بدل قراءة كل شيء.'],
  ['04', 'راجع الرد', 'اقتراح مرتبط بسياق العميل والبيانات المتاحة؛ عدّله قبل الإرسال.'],
  ['05', 'تابع بوضوح', 'أنشئ متابعة، أجّلها، أو أغلقها وفق ما حدث فعلاً.'],
  ['06', 'قِس التشغيل', 'اعرف ما ظهر وما فُتح وما تم، من دون اختراع إيراد.'],
];

const trustItems = [
  ['لا مصدر؟ لا ادعاء.', 'عند غياب السعر أو السياسة أو التوافر، يظهر النقص بدل تخمين معلومة.'],
  ['المجهول ليس صفراً.', 'القيم المالية غير المتصلة ببيانات طلب أو دفع موثوقة تبقى غير متاحة.'],
  ['أنت في التحكم.', 'VELOR يقترح؛ فريقك يراجع ويعدّل ويرسل.'],
  ['كل مساحة مستقلة.', 'المحادثات والموارد معزولة بين مساحات العمل.'],
];

function ProductScene() {
  return (
    <div className="relative mx-auto max-w-[620px] rounded-[1.5rem] border border-white/[0.11] bg-[#111324] p-3 shadow-[0_28px_90px_rgba(0,0,0,.42)]" aria-label="مثال لمساحة عمل VELOR">
      <div className="flex items-center justify-between border-b border-white/[0.08] px-3 pb-3 text-[10px] text-velor-muted">
        <span className="font-semibold text-white">VELOR · Revenue Recovery</span><span className="rounded-full bg-emerald-400/10 px-2 py-1 text-emerald-300">إشارة موثّقة</span>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-[.9fr_1.25fr]">
        <div className="rounded-xl border border-white/[0.07] bg-black/15 p-3">
          <p className="text-[9px] font-bold tracking-[.14em] text-velor-muted">أولوية الآن</p>
          <div className="mt-3 rounded-lg border border-velor-purple/25 bg-velor-purple/[.09] p-2.5">
            <div className="flex justify-between gap-2"><span className="text-[11px] font-bold text-white">عميلة تنتظر رداً</span><Clock3 className="h-3.5 w-3.5 text-velor-violet" /></div>
            <p className="mt-1 text-[10px] leading-5 text-velor-secondary">سألت عن الشحن والتوافر ولم يُرسل رد لاحق.</p>
            <p className="mt-2 text-[9px] font-semibold text-amber-300">WAITING ON US</p>
          </div>
          <div className="mt-2 rounded-lg border border-white/[.06] p-2.5 text-[10px] text-velor-muted">متابعة مستحقة · 11:00 ص</div>
        </div>
        <div className="rounded-xl border border-white/[0.07] bg-white/[.025] p-3">
          <p className="text-[9px] font-bold tracking-[.14em] text-velor-muted">محادثة العميل</p>
          <div className="mt-3 rounded-xl rounded-tr-sm bg-white/[.06] p-2.5 text-[11px] leading-5 text-white" dir="auto">ممكن أعرف التوافر والتوصيل للقاهرة؟</div>
          <div className="mt-2 rounded-xl border border-velor-purple/25 bg-velor-purple/[.08] p-2.5">
            <div className="flex items-center justify-between"><span className="text-[10px] font-bold text-velor-violet">رد مقترح</span><span className="text-[9px] text-velor-muted">قابل للتعديل</span></div>
            <p className="mt-1.5 text-[11px] leading-5 text-velor-secondary">أهلاً بك. أراجع تفاصيل التوافر والتوصيل المسجلة عندنا وأرد عليك بالمعلومة الدقيقة.</p>
            <div className="mt-2 flex gap-2"><span className="rounded-md bg-white/[.07] px-2 py-1 text-[9px] text-white">راجع الدليل</span><span className="rounded-md bg-velor-purple px-2 py-1 text-[9px] font-semibold text-white">أدرج الرد</span></div>
          </div>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-4 gap-1.5 text-center text-[9px] text-velor-muted"><span>رسالة عميل</span><MoveLeft className="mx-auto h-3 w-3 text-velor-violet" /><span>قرار فريقك</span><span>نتيجة تشغيلية</span></div>
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
          <div className="mx-auto grid max-w-[1200px] items-center gap-12 lg:grid-cols-[.94fr_1.06fr]">
            <div>
              <p className="inline-flex items-center gap-2 rounded-full border border-velor-purple/25 bg-velor-purple/[.07] px-3 py-1.5 text-[11px] font-semibold text-violet-200"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />Revenue recovery for customer conversations</p>
              <h1 className="mt-6 max-w-2xl text-4xl font-extrabold leading-[1.2] tracking-[-.045em] text-white sm:text-5xl lg:text-[58px]">المحادثات اللي بتضيع منك، <span className="velor-glow-text-purple">VELOR يرجّعها لفرص بيع.</span></h1>
              <p className="mt-6 max-w-xl text-base leading-8 text-velor-secondary sm:text-lg">نظام استرداد الإيراد للشركات التي تبيع عبر Web Chat وWhatsApp workflows. يلتقط المحادثات المهمة، يرتّب التدخل، ويساعد فريقك على الرد والمتابعة بوضوح.</p>
              <p className="mt-3 max-w-xl text-xs leading-6 text-velor-muted">لا يخترع أسعاراً أو طلبات أو إيراداً. عندما تكون المعلومة غير متاحة، يقول ذلك بوضوح.</p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row"><Link to="/signup" id="hero-primary-cta" className="velor-button-primary min-h-[52px] px-6 text-sm">ابدأ تجربة VELOR <ArrowLeft className="h-4 w-4" /></Link><a href="#how" className="velor-button-secondary min-h-[52px] px-6 text-sm">شاهد طريقة العمل <ChevronDown className="h-4 w-4" /></a></div>
              <div className="mt-7 flex flex-wrap gap-x-5 gap-y-2 text-[11px] text-velor-muted"><span className="inline-flex items-center gap-1.5"><Check className="h-3.5 text-emerald-400" />ابدأ عبر Web Chat</span><span className="inline-flex items-center gap-1.5"><Check className="h-3.5 text-emerald-400" />مراجعة بشرية قبل الإرسال</span></div>
            </div>
            <ProductScene />
          </div>
        </section>

        <section id="product" className="scroll-mt-20 border-y border-white/[.06] bg-white/[.015] px-4 py-16 sm:px-6 sm:py-20">
          <div className="mx-auto max-w-[1200px]"><div className="max-w-2xl"><p className="text-xs font-bold tracking-[.16em] text-velor-violet">المشكلة ليست في عدد الرسائل</p><h2 className="mt-3 text-3xl font-bold tracking-[-.04em] text-white sm:text-4xl">الفرص تضيع في تفاصيل يوم العمل.</h2><p className="mt-4 text-sm leading-7 text-velor-secondary">VELOR لا يحوّل كل شات إلى تنبيه. يركز على لحظات البيع أو التعطّل التي تستحق قراراً واضحاً.</p></div><div className="mt-9 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{leakage.map(([title, detail]) => <article key={title} className="rounded-2xl border border-white/[.07] bg-black/10 p-5"><CircleAlert className="h-5 w-5 text-amber-300" /><h3 className="mt-5 text-sm font-bold text-white">{title}</h3><p className="mt-2 text-xs leading-6 text-velor-muted">{detail}</p></article>)}</div></div>
        </section>

        <section id="how" className="scroll-mt-20 px-4 py-20 sm:px-6 sm:py-24"><div className="mx-auto max-w-[1200px]"><div className="flex flex-col justify-between gap-5 md:flex-row md:items-end"><div><p className="text-xs font-bold tracking-[.16em] text-velor-violet">كيف يعمل</p><h2 className="mt-3 text-3xl font-bold tracking-[-.04em] text-white sm:text-4xl">من الرسالة إلى إجراء يمكن تنفيذه.</h2></div><p className="max-w-md text-sm leading-7 text-velor-secondary">مصمم لسير عمل Web Chat وWhatsApp. Web Chat متاح الآن؛ WhatsApp workflow مصمم ضمن البنية ولا يُدّعى أنه نشر معتمد.</p></div><div className="mt-10 grid gap-3 md:grid-cols-2 lg:grid-cols-3">{workflow.map(([number, title, detail]) => <article key={number} className="velor-card p-5"><span className="text-[11px] font-bold text-velor-violet">{number}</span><h3 className="mt-7 text-base font-bold text-white">{title}</h3><p className="mt-2 text-sm leading-6 text-velor-muted">{detail}</p></article>)}</div></div></section>

        <section id="recovery" className="scroll-mt-20 bg-[linear-gradient(135deg,rgba(91,53,190,.16),rgba(12,14,27,.1)_45%,rgba(11,13,22,.1))] px-4 py-20 sm:px-6 sm:py-24"><div className="mx-auto grid max-w-[1200px] gap-10 lg:grid-cols-[.86fr_1.14fr]"><div><p className="text-xs font-bold tracking-[.16em] text-violet-200">REVENUE RECOVERY</p><h2 className="mt-3 text-3xl font-bold tracking-[-.04em] text-white sm:text-4xl">استرداد الإيراد هو تشغيل أفضل، وليس وعداً مالياً.</h2><p className="mt-5 text-sm leading-7 text-velor-secondary">VELOR يقيس تسلسل العمل: فرصة ظهرت، فرصة فُتحت، رد أُرسل، أو متابعة اكتملت. الإيراد يُنسب فقط عند ربطه ببيانات طلب أو دفع موثوقة.</p><p className="mt-5 rounded-xl border border-amber-300/15 bg-amber-300/[.06] p-4 text-sm font-semibold leading-6 text-amber-100">الإيراد غير المعروف يظهر غير معروف — وليس رقماً مخترعاً.</p></div><div className="grid gap-3 sm:grid-cols-2">{[['فرصة تم تحديدها','إشارة من محادثة قابلة للمراجعة.'],['فرصة تم فتحها','فتح المالك للمحادثة والدليل.'],['رد تم إرساله','بعد نجاح الإرسال فقط.'],['متابعة اكتملت','حالة تشغيلية مسجلة، لا افتراض.']].map(([title, detail], i) => <div key={title} className="rounded-2xl border border-white/[.08] bg-[#111326]/80 p-5"><span className="text-xs text-velor-violet">0{i + 1}</span><h3 className="mt-8 text-sm font-bold text-white">{title}</h3><p className="mt-2 text-xs leading-6 text-velor-muted">{detail}</p></div>)}</div></div></section>

        <section className="px-4 py-20 sm:px-6 sm:py-24"><div className="mx-auto grid max-w-[1200px] gap-8 lg:grid-cols-2"><article className="velor-panel p-6 sm:p-8"><Eye className="h-6 w-6 text-velor-violet" /><p className="mt-6 text-xs font-bold tracking-[.16em] text-velor-violet">ذكاء مرتبط بالدليل</p><h2 className="mt-3 text-2xl font-bold tracking-[-.035em] text-white sm:text-3xl">المساعد ليس مصدر الحقيقة التجارية.</h2><p className="mt-4 text-sm leading-7 text-velor-secondary">السياق وبيانات نشاطك المصرح بها هي التي تحدد ما يمكن قوله. VELOR يعرض المعلومة الناقصة بدلاً من ملئها بافتراضات.</p></article><article className="velor-panel p-6 sm:p-8"><Target className="h-6 w-6 text-emerald-300" /><p className="mt-6 text-xs font-bold tracking-[.16em] text-emerald-300">انتباه المالك</p><h2 className="mt-3 text-2xl font-bold tracking-[-.035em] text-white sm:text-3xl">مش لازم تفتح كل شات. افتح الشات اللي محتاج قرار.</h2><p className="mt-4 text-sm leading-7 text-velor-secondary">محادثة تنتظر رداً، نية شراء، اعتراض موثّق، معلومة ناقصة، أو متابعة مستحقة — تظهر في مكانها عندما تكون مؤهلة للإجراء.</p></article></div></section>

        <section className="border-y border-white/[.06] bg-white/[.015] px-4 py-20 sm:px-6 sm:py-24"><div className="mx-auto grid max-w-[1200px] gap-10 lg:grid-cols-[1.1fr_.9fr]"><div><p className="text-xs font-bold tracking-[.16em] text-velor-violet">الردود والمتابعات</p><h2 className="mt-3 text-3xl font-bold tracking-[-.04em] text-white sm:text-4xl">مساعدة عملية، مع بقاء القرار في يد الفريق.</h2><div className="mt-8 space-y-3">{[['راجع وعدّل ثم أرسل','استخدام الرد يُسجل فقط بعد إرسال ناجح.'],['سياق جديد؟ الرد القديم يتوقف','أي رسالة عميل أحدث تجعل الاقتراح القديم غير صالح للاستخدام.'],['لا تضيّع المتابعة','أنشئ متابعة مستحقة، أجّلها، أكملها أو ألغها حسب الواقع.']].map(([title, detail]) => <div key={title} className="flex gap-3 rounded-xl border border-white/[.07] bg-black/10 p-4"><UserRoundCheck className="mt-0.5 h-4 w-4 shrink-0 text-velor-violet" /><div><h3 className="text-sm font-bold text-white">{title}</h3><p className="mt-1 text-xs leading-6 text-velor-muted">{detail}</p></div></div>)}</div></div><div className="rounded-2xl border border-white/[.08] bg-[#0d0f1d] p-5 sm:p-6"><p className="text-[10px] font-bold tracking-[.14em] text-velor-muted">FOLLOW-UP</p><div className="mt-5 space-y-3">{[['مستحقة الآن','رد على سؤال الشحن قبل 11:00 ص','bg-amber-400'],['تم التأجيل','مراجعة الغد بعد وصول بيانات المخزون','bg-sky-400'],['مكتملة','تم إرسال رد يدوي مرتبط بالعميل','bg-emerald-400']].map(([state, detail, color]) => <div key={state} className="flex gap-3 rounded-xl border border-white/[.07] p-3"><span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${color}`} /><div><p className="text-xs font-bold text-white">{state}</p><p className="mt-1 text-[11px] leading-5 text-velor-muted">{detail}</p></div></div>)}</div></div></div></section>

        <section id="trust" className="scroll-mt-20 px-4 py-20 sm:px-6 sm:py-24"><div className="mx-auto max-w-[1200px]"><div className="max-w-2xl"><p className="text-xs font-bold tracking-[.16em] text-velor-violet">الثقة والخصوصية</p><h2 className="mt-3 text-3xl font-bold tracking-[-.04em] text-white sm:text-4xl">وضوح في ما نعرفه، وما لا نعرفه.</h2></div><div className="mt-9 grid gap-3 md:grid-cols-2 lg:grid-cols-4">{trustItems.map(([title, detail]) => <article key={title} className="rounded-2xl border border-white/[.07] p-5"><ShieldCheck className="h-5 w-5 text-velor-violet" /><h3 className="mt-6 text-sm font-bold text-white">{title}</h3><p className="mt-2 text-xs leading-6 text-velor-muted">{detail}</p></article>)}</div></div></section>

        <section className="px-4 pb-20 pt-6 sm:px-6 sm:pb-28"><div className="relative mx-auto max-w-[1000px] overflow-hidden rounded-[2rem] border border-velor-purple/25 bg-[radial-gradient(circle_at_75%_0%,rgba(139,92,246,.25),transparent_45%),#141328] px-6 py-12 text-center sm:px-12 sm:py-16"><Sparkles className="mx-auto h-6 w-6 text-violet-200" /><h2 className="mx-auto mt-6 max-w-2xl text-3xl font-bold tracking-[-.04em] text-white sm:text-4xl">كل محادثة من غير متابعة ممكن تكون صفقة ضاعت.</h2><p className="mx-auto mt-4 max-w-xl text-sm leading-7 text-velor-secondary">اختبر VELOR على محادثات Web Chat وشاهد كيف تتحول الرسائل إلى أولويات قابلة للتنفيذ.</p><Link to="/signup" id="final-primary-cta" className="velor-button-primary mt-8 min-h-[52px] px-7 text-sm">ابدأ مساحة عملك <ArrowLeft className="h-4 w-4" /></Link></div></section>
      </main>

      <footer className="border-t border-white/[.06] px-4 py-10 sm:px-6"><div className="mx-auto flex max-w-[1200px] flex-col gap-6 text-center sm:flex-row sm:items-center sm:justify-between sm:text-right"><div><VelorLogo size={28} wordmarkClassName="text-sm" className="text-white" /><p className="mt-2 text-[10px] text-velor-muted">Revenue recovery for customer conversations.</p></div><div className="flex flex-wrap justify-center gap-x-5 gap-y-2 text-[11px] font-semibold text-velor-muted"><a href="#product">المنتج</a><Link to="/terms">الشروط</Link><Link to="/privacy">الخصوصية</Link><Link to="/login">تسجيل الدخول</Link><Link to="/signup">إنشاء مساحة عمل</Link></div><p className="text-[10px] text-velor-muted">© {new Date().getFullYear()} VELOR</p></div></footer>
      <div className="fixed inset-x-3 bottom-3 z-40 rounded-xl border border-white/[.1] bg-[#15162b]/95 p-2 shadow-2xl backdrop-blur md:hidden"><Link to="/signup" className="velor-button-primary flex min-h-11 w-full text-sm">ابدأ تجربة VELOR <ArrowLeft className="h-4 w-4" /></Link></div>
    </div>
  );
}
