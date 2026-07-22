import { Link } from 'react-router-dom';
import { ArrowRight, CircleAlert, ShieldCheck } from 'lucide-react';
import { VelorLogo } from '../components/velor/VelorLogo';

const sections = [
  ['1. الخدمة المتاحة حاليًا', 'VELOR أداة تجريبية لإدارة محادثات البيع، وتشمل Hosted Web Chat ومساحة التاجر وميزات مساعدة تعتمد على بيانات النشاط. WhatsApp QR متاح كنسخة Beta وليس تكامل WhatsApp Business Platform الرسمي.'],
  ['2. الحساب والوصول', 'أنت مسؤول عن حماية بيانات الدخول ومفاتيح التكامل، وعن منح الوصول فقط لأفراد فريقك المصرح لهم. لا تشارك حسابًا واحدًا بين جهات لا تنتمي إلى نفس النشاط.'],
  ['3. بيانات النشاط والعملاء', 'يجب أن تمتلك أساسًا قانونيًا مناسبًا لجمع بيانات عملائك وإرسال الرسائل لهم، وأن تُدخل معلومات منتجات وسياسات صحيحة ومحدثة. لا تستخدم VELOR للرسائل المزعجة أو الاحتيال أو أي نشاط غير قانوني.'],
  ['4. مخرجات الذكاء الاصطناعي', 'الردود والملخصات والاقتراحات قد تكون ناقصة أو خاطئة. راجع الردود المهمة والأسعار والمخزون والضمان والتوصيل قبل الاعتماد عليها، واستخدم التحكم البشري عندما تكون المعلومة غير موثقة.'],
  ['5. الإتاحة والنسخة التجريبية', 'قد تتغير الميزات أو تتوقف مؤقتًا أثناء الـPilot. لا يوجد حاليًا checkout أو اشتراك مدفوع ذاتي متصل، ولذلك لا يُعتبر إنشاء الحساب موافقة على خصم أو تحصيل مالي. أي اتفاق Pilot مدفوع يحتاج اتفاقًا منفصلًا واضحًا.'],
  ['6. القنوات الخارجية', 'استخدام WhatsApp أو أي مزود خارجي يخضع أيضًا لشروط ذلك المزود. جلسة WhatsApp QR التجريبية قد تنقطع أو تتطلب إعادة الربط، ولا نضمن قبولها كبديل للتكامل الرسمي.'],
  ['7. حدود المسؤولية', 'تُقدَّم النسخة الحالية كما هي وفي حدود ما يسمح به القانون. لا نضمن نتيجة بيع أو دقة مطلقة أو تشغيلًا بلا انقطاع، ولا ينبغي استخدامها وحدها لاتخاذ قرارات قانونية أو مالية أو عالية المخاطر.'],
  ['8. التعليق والحذف', 'يجوز تعليق الوصول عند وجود إساءة استخدام أو خطر أمني. لطلبات الوصول إلى البيانات أو حذفها، تواصل مع الجهة التي منحتك رابط VELOR إلى أن ينشر مالك الخدمة قناة دعم رسمية.'],
];

export default function Terms() {
  return (
    <main className="min-h-screen bg-velor-deep px-5 py-8 text-velor-text velor-grid-bg sm:px-8 lg:py-12" dir="rtl">
      <div className="mx-auto max-w-4xl">
        <header className="mb-7 flex items-center justify-between gap-4">
          <Link to="/" aria-label="العودة إلى VELOR"><VelorLogo size={34} wordmarkClassName="text-base" /></Link>
          <Link to="/" className="velor-button-secondary min-h-10 px-3 text-xs"><ArrowRight className="h-4 w-4" /> الرئيسية</Link>
        </header>
        <article className="velor-panel overflow-hidden p-5 sm:p-8 lg:p-10">
          <div className="border-b border-white/[0.07] pb-7">
            <p className="text-[10px] font-bold tracking-[0.16em] text-velor-purple">وثيقة النسخة التجريبية</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">شروط استخدام VELOR</h1>
            <p className="mt-3 text-xs leading-6 text-velor-muted">آخر تحديث: 15 يوليو 2026. إنشاء الحساب أو استخدام الخدمة يعني قبول هذه الشروط.</p>
          </div>
          <div className="mt-7 flex gap-3 rounded-xl border border-velor-amber/20 bg-velor-amber/[0.055] p-4 text-xs leading-6 text-velor-secondary">
            <CircleAlert className="mt-1 h-4 w-4 shrink-0 text-velor-amber" />
            <p>هذه الشروط تصف حالة المنتج الحالية بصدق؛ لا تعد بفترة مدفوعة أو ضمانات أو تكاملات غير متصلة.</p>
          </div>
          <div className="mt-8 space-y-8">
            {sections.map(([title, body]) => (
              <section key={title}>
                <h2 className="flex items-center gap-2 text-base font-semibold text-white"><ShieldCheck className="h-4 w-4 text-velor-purple" />{title}</h2>
                <p className="mt-2 text-sm leading-7 text-velor-secondary">{body}</p>
              </section>
            ))}
          </div>
        </article>
      </div>
    </main>
  );
}
