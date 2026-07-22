import { ArrowUpRight, Bot, CheckCircle2, MessageCircle, ShieldCheck, Sparkles, Star, Zap } from 'lucide-react';
import { Link } from 'react-router-dom';
import { VelorLogo, VelorMark } from './velor/VelorLogo';
import { Badge } from './velor/ui';

const features = [
  { icon: MessageCircle, label: 'سؤال شراء واضح',        tone: 'green',  toneClass: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/15' },
  { icon: CheckCircle2, label: 'حجم الفريق مذكور',        tone: 'purple', toneClass: 'bg-purple-500/10 text-purple-400 border-purple-500/15' },
  { icon: ShieldCheck,  label: 'الرد من معلومات الإعداد', tone: 'blue',   toneClass: 'bg-blue-500/10 text-blue-400 border-blue-500/15' },
];

export default function AuthHero({ mode = 'login' }) {
  return (
    <aside
      className="relative hidden min-h-screen w-[56%] overflow-hidden lg:flex lg:flex-col"
      dir="rtl"
      style={{
        background: 'linear-gradient(160deg, #07071a 0%, #09091f 50%, #060614 100%)',
        borderInlineStart: '1px solid rgba(130,120,220,0.08)',
      }}
    >
      {/* ── Ambient layers ── */}
      <div className="absolute inset-0 velor-grid-bg opacity-40" aria-hidden="true" />

      {/* Aurora orbs — subtle, not spinning */}
      <div
        className="pointer-events-none absolute -left-40 top-1/4 h-[480px] w-[480px] rounded-full opacity-40 blur-[130px] animate-aurora"
        style={{ background: 'radial-gradient(circle, rgba(139,92,246,0.5) 0%, rgba(99,102,241,0.2) 60%, transparent 80%)' }}
        aria-hidden="true"
      />
      <div
        className="pointer-events-none absolute -right-56 bottom-[-8rem] h-[500px] w-[500px] rounded-full opacity-20 blur-[150px]"
        style={{ background: 'radial-gradient(circle, rgba(56,189,248,0.3) 0%, transparent 70%)' }}
        aria-hidden="true"
      />

      {/* Noise texture */}
      <div className="pointer-events-none absolute inset-0 opacity-[0.3]" aria-hidden="true"
        style={{
          backgroundImage: "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.06'/%3E%3C/svg%3E\")",
          mixBlendMode: 'soft-light',
        }}
      />

      {/* ── Header ── */}
      <header className="relative z-10 flex h-24 items-center justify-between px-10 xl:px-14">
        <Link to="/" aria-label="العودة إلى VELOR">
          <VelorLogo size={36} wordmarkClassName="text-lg font-bold tracking-widest text-white" />
        </Link>
        <Badge tone="purple" className="velor-badge-shine">واجهة توضيحية</Badge>
      </header>

      {/* ── Hero content ── */}
      <div className="relative z-10 flex flex-1 flex-col justify-center px-10 pb-10 xl:px-14 2xl:px-20">

        {/* Tag line */}
        <div className="mb-6 animate-velor-in">
          <span className="inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-[11px] font-bold tracking-[0.12em]" style={{
            borderColor: 'rgba(139,92,246,0.25)',
            background: 'rgba(139,92,246,0.08)',
            color: '#c4b5fd',
          }}>
            <Sparkles className="h-3 w-3 text-purple-400" />
            وضوح أكثر في كل محادثة بيع
            <Sparkles className="h-3 w-3 text-purple-400" />
          </span>
        </div>

        {/* Heading */}
        <div className="mb-6 animate-velor-in">
          <h2 className="max-w-[580px] text-[3rem] font-extrabold leading-[1.04] tracking-[-0.055em] text-white xl:text-[3.75rem]">
            اعرف المحادثة
            <br />
            التي تحتاج{' '}
            <span className="velor-glow-text-vivid">تدخّلك الآن.</span>
          </h2>
          <p className="mt-5 max-w-[520px] text-[15px] leading-7" style={{ color: '#8882a2' }}>
            VELOR يساعدك على مراجعة إشارات الشراء والاعتراض والمتابعة، ويستخدم المنتجات والسياسات التي تضيفها كمصدر للرد.
          </p>
        </div>

        {/* Demo card */}
        <div className="relative max-w-[640px] animate-velor-in-delayed">
          {/* Outer glow */}
          <div className="absolute -inset-6 rounded-full opacity-40 blur-3xl" aria-hidden="true"
            style={{ background: 'radial-gradient(ellipse, rgba(139,92,246,0.15), transparent 70%)' }} />

          {/* Card */}
          <div
            className="relative overflow-hidden rounded-2xl"
            style={{
              background: 'linear-gradient(145deg, rgba(20,18,42,0.95) 0%, rgba(12,11,26,0.98) 100%)',
              border: '1px solid rgba(139,92,246,0.18)',
              boxShadow: '0 1px 0 0 rgba(255,255,255,0.04) inset, 0 40px 120px rgba(0,0,0,0.5)',
            }}
          >
            {/* Card shimmer removed — was too flashy */}

            {/* Card header */}
            <div className="flex items-center justify-between border-b px-4 py-3" style={{ borderColor: 'rgba(139,92,246,0.1)' }}>
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-xl" style={{
                  background: 'linear-gradient(135deg, rgba(139,92,246,0.25), rgba(99,102,241,0.15))',
                  border: '1px solid rgba(139,92,246,0.2)',
                }}>
                  <VelorMark size={18} decorative />
                </div>
                <div>
                  <p className="text-xs font-bold text-white">مثال داخل VELOR</p>
                  <p className="mt-0.5 text-[9px]" style={{ color: '#6b6585' }}>سيناريو توضيحي لمحادثة Web Chat</p>
                </div>
              </div>
              <Badge tone="neutral">غير متصل بعميل حقيقي</Badge>
            </div>

            {/* Chat + insights */}
            <div className="grid gap-3 p-4 xl:grid-cols-[1.2fr_.9fr]">
              {/* Chat messages */}
              <div className="space-y-2.5">
                {/* Customer message */}
                <div className="mr-auto max-w-[85%]">
                  <div className="rounded-2xl rounded-br-sm px-3.5 py-2.5 text-xs leading-5" style={{
                    background: 'rgba(255,255,255,0.06)',
                    color: '#b0aacb',
                  }}>
                    محتاج أعرف المنتج مناسب لفريق 12 شخص؟ ونقدر نبدأ إمتى؟
                  </div>
                  <p className="mt-1 text-[9px] text-right" style={{ color: '#6b6585' }}>عميل • منذ دقيقتين</p>
                </div>

                {/* AI response */}
                <div className="max-w-[88%]">
                  <div className="rounded-2xl rounded-bl-sm px-3.5 py-2.5 text-xs leading-5" style={{
                    background: 'linear-gradient(135deg, rgba(139,92,246,0.1), rgba(99,102,241,0.06))',
                    border: '1px solid rgba(139,92,246,0.15)',
                    color: '#f0eeff',
                  }}>
                    تقدر تبدأ بإعداد موجّه، وتفعّل أول قناة، وتختبر الردود على كتالوجك قبل نشر المحادثة للعملاء.
                  </div>
                  <div className="mt-1.5 flex items-center gap-1.5 px-1 text-[9px]" style={{ color: '#6b6585' }}>
                    <Bot className="h-3 w-3 text-purple-400" />
                    <span>VELOR · من بيانات الإعداد</span>
                    <span className="mr-auto flex items-center gap-1" style={{ color: '#34d399' }}>
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-signal-pulse" />
                      رد مقترح للمراجعة
                    </span>
                  </div>
                </div>
              </div>

              {/* Insights panel */}
              <div className="rounded-xl p-3" style={{
                background: 'rgba(0,0,0,0.2)',
                border: '1px solid rgba(130,120,220,0.08)',
              }}>
                <p className="mb-3 text-[9px] font-bold tracking-[0.14em] uppercase" style={{ color: '#6b6585' }}>
                  ما الذي التقطه المثال؟
                </p>
                <div className="space-y-2">
                  {features.map(({ icon: Icon, label, toneClass }) => (
                    <div key={label} className="flex items-center gap-2.5 text-[10px]" style={{ color: '#b0aacb' }}>
                      <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border ${toneClass}`}>
                        <Icon className="h-3.5 w-3.5" />
                      </span>
                      <span className="min-w-0 flex-1">{label}</span>
                      <ArrowUpRight className="h-3 w-3 shrink-0" style={{ color: '#6b6585' }} />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Trust badges */}
        <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-2 text-[10px] animate-velor-in-slow" style={{ color: '#6b6585' }}>
          <span className="flex items-center gap-1.5">
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
            عزل بيانات كل نشاط
          </span>
          <span className="flex items-center gap-1.5">
            <Star className="h-3.5 w-3.5 text-amber-400" />
            مراجعة بشرية عند الحاجة
          </span>
          <span className="flex items-center gap-1.5">
            <Zap className="h-3.5 w-3.5 text-blue-400" />
            {mode === 'signup' ? 'إعداد موجّه قبل النشر' : 'سجل محادثة قابل للمراجعة'}
          </span>
        </div>
      </div>
    </aside>
  );
}
