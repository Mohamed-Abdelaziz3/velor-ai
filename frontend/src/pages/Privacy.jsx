import { Link } from 'react-router-dom';
import { ArrowRight, Database, LockKeyhole } from 'lucide-react';
import { VelorLogo } from '../components/velor/VelorLogo';

const sections = [
  ['البيانات التي تُحفظ', 'بيانات حساب التاجر، إعدادات النشاط والكتالوج والسياسات، رسائل العملاء ومعرّفات القناة، حالات التسليم، الأدلة المشتقة من الرسائل، وسجل الأحداث التشغيلي والأمني. لا يجمع VELOR بيانات بطاقات دفع لأن checkout غير متصل حاليًا.'],
  ['لماذا نستخدمها', 'لتشغيل المحادثة، عرض التاريخ للفريق، توليد رد أو ملخص أو اقتراح، منع التكرار وإساءة الاستخدام، تشخيص الأخطاء، وحماية عزل بيانات كل مساحة عمل.'],
  ['الذكاء الاصطناعي والمزودون', 'عند تهيئة مزود AI خارجي، قد تُرسل إليه أجزاء لازمة من المحادثة ومعلومات النشاط لتوليد الرد. عند عدم توفر المزود يستخدم النظام مسار fallback محدود. يجب على مشغل النشر مراجعة شروط وموقع معالجة بيانات أي مزود قبل استقبال عملاء حقيقيين.'],
  ['Web Chat وWhatsApp', 'Hosted Web Chat ينشئ معرّف زائر عشوائيًا ويخزن سجل الجلسة. WhatsApp QR Beta يعالج الرسائل عبر جلسة الجهاز المرتبط؛ استخدامه يخضع لسياسات WhatsApp ولا يمثل تكامل Cloud API رسميًا.'],
  ['الحماية والوصول', 'تُفصل البيانات حسب مساحة العمل ويُستخدم وصول مصادق عليه للتاجر ورمز محدود للزائر. توجد حدود طلبات وسجلات تدقيق، لكن لا يوجد نظام خالٍ تمامًا من المخاطر؛ يجب استخدام HTTPS وأسرار قوية ونسخ احتياطية ومراقبة في الإنتاج.'],
  ['الاحتفاظ والحذف', 'لا توجد في الواجهة الحالية مدة احتفاظ قابلة للضبط لكل تاجر. يحتفظ النظام بالبيانات حتى يحذفها المشغل وفق سياسته أو ينفذ طلب حذف صالح. قبل الإطلاق العام يجب نشر مدة احتفاظ وقناة دعم رسمية واتفاق معالجة بيانات مناسب.'],
  ['حقوق العميل', 'لطلب نسخة أو تصحيح أو حذف، تواصل مع النشاط الذي جمع بياناتك عبر رابط المحادثة أو مع مشغل نشر VELOR. لا ننشر عنوان دعم غير موجود؛ يجب على مالك الخدمة إضافته قبل حملة عامة.'],
];

export default function Privacy() {
  return (
    <main className="min-h-screen bg-velor-deep px-5 py-8 text-velor-text velor-grid-bg sm:px-8 lg:py-12" dir="rtl">
      <div className="mx-auto max-w-4xl">
        <header className="mb-7 flex items-center justify-between gap-4">
          <Link to="/" aria-label="العودة إلى VELOR"><VelorLogo size={34} wordmarkClassName="text-base" /></Link>
          <Link to="/" className="velor-button-secondary min-h-10 px-3 text-xs"><ArrowRight className="h-4 w-4" /> الرئيسية</Link>
        </header>
        <article className="velor-panel overflow-hidden p-5 sm:p-8 lg:p-10">
          <div className="border-b border-white/[0.07] pb-7">
            <p className="text-[10px] font-bold tracking-[0.16em] text-velor-purple">الخصوصية والشفافية</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">سياسة خصوصية VELOR</h1>
            <p className="mt-3 text-xs leading-6 text-velor-muted">آخر تحديث: 15 يوليو 2026. توضح هذه الصفحة ما يفعله الكود الحالي وما يجب استكماله قبل إطلاق عام.</p>
          </div>
          <div className="mt-7 grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl border border-velor-purple/15 bg-velor-purple/[0.055] p-4"><Database className="h-5 w-5 text-velor-purple" /><p className="mt-3 text-sm font-semibold text-white">بياناتك لخدمة نشاطك</p><p className="mt-1 text-xs leading-5 text-velor-muted">لا نعرض بيانات مساحة عمل لتاجر آخر.</p></div>
            <div className="rounded-xl border border-velor-blue/15 bg-velor-blue/[0.045] p-4"><LockKeyhole className="h-5 w-5 text-velor-blue" /><p className="mt-3 text-sm font-semibold text-white">مراجعة بشرية ضرورية</p><p className="mt-1 text-xs leading-5 text-velor-muted">الذكاء الاصطناعي لا يحوّل التقدير إلى حقيقة مؤكدة.</p></div>
          </div>
          <div className="mt-8 space-y-8">
            {sections.map(([title, body], index) => (
              <section key={title}>
                <h2 className="text-base font-semibold text-white">{index + 1}. {title}</h2>
                <p className="mt-2 text-sm leading-7 text-velor-secondary">{body}</p>
              </section>
            ))}
          </div>
        </article>
      </div>
    </main>
  );
}
