import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, Building2, Check, CheckCircle2, Copy, Eye, EyeOff, KeyRound, Lock, Mail, ShieldCheck } from 'lucide-react';
import { GoogleLogin } from '@react-oauth/google';
import { googleAuth, login, signup } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import AuthHero from '../components/AuthHero';
import { VelorLogo } from '../components/velor/VelorLogo';
import { Badge, Button, Field, ProgressBar } from '../components/velor/ui';

function passwordScore(password) {
  let score = 0;
  if (password.length >= 8) score += 25;
  if (/[A-Z]/.test(password)) score += 25;
  if (/[0-9]/.test(password)) score += 25;
  if (/[^A-Za-z0-9]/.test(password)) score += 25;
  return score;
}

export default function Signup() {
  const navigate = useNavigate();
  const { loginUser } = useAuth();
  const [formData, setFormData] = useState({ company_name: '', email: '', password: '' });
  const [accepted, setAccepted] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [successData, setSuccessData] = useState(null);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const googleAuthEnabled = import.meta.env.VITE_ENABLE_GOOGLE_AUTH === 'true';
  const strength = useMemo(() => passwordScore(formData.password), [formData.password]);

  const onChange = (event) => {
    setFormData((current) => ({ ...current, [event.target.name]: event.target.value }));
    if (error) setError('');
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!accepted) {
      setError('راجع الشروط وسياسة الخصوصية ووافق عليهما للمتابعة.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const { data } = await signup({ ...formData, terms_accepted: true });
      if (data?.success) {
        try {
          const { data: session } = await login({ email: formData.email, password: formData.password });
          if (!session?.success) throw new Error('login_failed');
          loginUser(session);
          navigate('/onboarding', { replace: true });
          return;
        } catch {
          // The account exists even if the follow-up session request was
          // interrupted. Keep the recovery screen and never ask the merchant
          // to repeat signup.
          setSuccessData(data);
        }
      }
    } catch (requestError) {
      const detail = requestError.response?.data?.message || requestError.response?.data?.detail;
      setError(Array.isArray(detail) ? detail.map((item) => item.msg).join(' · ') : detail || 'تعذّر إنشاء مساحة العمل الآن. حاول مرة أخرى.');
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleSuccess = async (credentialResponse) => {
    if (!accepted) {
      setError('راجع الشروط وسياسة الخصوصية ووافق عليهما للمتابعة.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const { data } = await googleAuth({ token: credentialResponse.credential, terms_accepted: true });
      if (data?.success) {
        loginUser(data);
        navigate(data.is_new_user ? '/onboarding' : '/dashboard', { replace: true });
      }
    } catch (requestError) {
      setError(requestError.response?.data?.message || requestError.response?.data?.detail || 'تعذّر إكمال التسجيل بحساب Google.');
    } finally {
      setLoading(false);
    }
  };

  const copyKey = async () => {
    if (!successData?.api_key) return;
    await navigator.clipboard.writeText(successData.api_key);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2200);
  };

  if (successData) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-velor-bg px-5 py-10 text-velor-text velor-grid-bg" dir="rtl">
        <section className="velor-panel w-full max-w-lg p-6 text-center sm:p-8 animate-velor-in">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-velor-green/20 bg-velor-green/10 text-velor-green"><CheckCircle2 className="h-7 w-7" /></span>
          <Badge tone="green" className="mt-5">تم إنشاء مساحة العمل</Badge>
          <h1 className="mt-4 text-2xl font-semibold tracking-[-0.04em] text-white">مساحة VELOR جاهزة.</h1>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-velor-muted">تم إنشاء الحساب، لكن فتح الجلسة تعطل. احتفظ بمفتاح التكامل ثم سجّل الدخول للمتابعة من نفس الحساب.</p>

          {successData.api_key && (
            <div className="mt-6 rounded-xl border border-velor-amber/20 bg-velor-amber/[0.055] p-4 text-left">
              <div className="mb-2 flex items-center gap-2 text-[10px] font-bold tracking-[0.12em] text-velor-amber"><KeyRound className="h-3.5 w-3.5" /> مفتاح التكامل — يظهر مرة واحدة</div>
              <div className="flex items-center gap-2">
                <code className="min-w-0 flex-1 truncate rounded-lg border border-white/[0.08] bg-black/25 px-3 py-2.5 text-xs text-white">{successData.api_key}</code>
                <Button variant="secondary" onClick={copyKey} className="shrink-0 px-3">{copied ? <Check className="h-4 w-4 text-velor-green" /> : <Copy className="h-4 w-4" />}<span className="sr-only">نسخ مفتاح التكامل</span></Button>
              </div>
            </div>
          )}

          <Button onClick={() => navigate(`/login?onboarding=1&email=${encodeURIComponent(formData.email)}`)} className="mt-6 w-full">سجّل الدخول وأكمل الإعداد <ArrowRight className="h-4 w-4 rotate-180" /></Button>
          <p className="mt-4 text-[10px] leading-5 text-velor-muted">لن نطلب منك إنشاء الحساب مرة أخرى.</p>
        </section>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen bg-velor-bg text-velor-text" dir="ltr">
      <AuthHero mode="signup" />
      <section className="relative flex min-h-screen w-full items-center justify-center overflow-hidden px-5 py-10 lg:w-[44%] lg:px-10" dir="rtl">
        <div className="pointer-events-none absolute -right-28 top-[-7rem] h-80 w-80 rounded-full bg-velor-purple/[0.1] blur-[110px]" />
        <div className="relative z-10 w-full max-w-[420px] animate-velor-in">
          <Link to="/" className="mb-8 inline-flex" aria-label="العودة إلى VELOR"><VelorLogo size={36} wordmarkClassName="text-base" /></Link>
          <div className="mb-7">
            <Badge tone="purple">إعداد موجّه خطوة بخطوة</Badge>
            <h1 className="mt-4 text-[2rem] font-semibold tracking-[-0.045em] text-white">ابدأ مساحة مبيعاتك.</h1>
            <p className="mt-2 text-sm leading-6 text-velor-muted">أنشئ الحساب، ثم فعّل قناة وأضف منتجاتك وسياساتك قبل نشر المحادثة.</p>
          </div>

          {error && <div className="mb-5 rounded-xl border border-velor-red/25 bg-velor-red/[0.08] p-3.5 text-xs leading-5 text-[#ffb1be]" role="alert">{error}</div>}

          <form onSubmit={handleSubmit} className="space-y-4">
            <Field label="اسم النشاط" icon={Building2} name="company_name" value={formData.company_name} onChange={onChange} placeholder="مثال: متجر النور" required minLength={2} maxLength={100} autoComplete="organization" disabled={loading} />
            <Field label="البريد الإلكتروني" icon={Mail} type="email" name="email" value={formData.email} onChange={onChange} placeholder="you@company.com" required autoComplete="email" disabled={loading} />
            <div>
              <label className="block">
                <span className="mb-2 flex items-center justify-between text-xs font-semibold text-velor-secondary"><span>كلمة المرور</span><span className="font-normal text-velor-muted">8 أحرف أو أكثر</span></span>
                <span className="relative block">
                  <Lock className="pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-velor-muted" />
                  <input className="velor-input px-10" type={showPassword ? 'text' : 'password'} name="password" value={formData.password} onChange={onChange} placeholder="أنشئ كلمة مرور قوية" required minLength={8} autoComplete="new-password" disabled={loading} />
                  <button type="button" onClick={() => setShowPassword((visible) => !visible)} className="absolute left-1.5 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-lg text-velor-muted transition hover:bg-white/5 hover:text-white" aria-label={showPassword ? 'إخفاء كلمة المرور' : 'إظهار كلمة المرور'}>{showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button>
                </span>
              </label>
              {formData.password && <ProgressBar value={strength} label={strength >= 75 ? 'كلمة مرور قوية' : strength >= 50 ? 'تحتاج تنويعًا أكثر' : 'أضف رقمًا ورمزًا وحرفًا كبيرًا'} detail={`${strength}%`} tone={strength >= 75 ? 'green' : strength >= 50 ? 'purple' : 'amber'} className="mt-2" />}
            </div>

            <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-white/[0.07] bg-white/[0.025] p-3.5">
              <input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} className="mt-0.5 h-4 w-4 rounded border-white/20 bg-black/30 accent-[#9b5cff]" />
              <span className="text-[11px] leading-5 text-velor-muted">أوافق على <Link to="/terms" className="text-velor-secondary hover:text-white">شروط الاستخدام</Link> و<Link to="/privacy" className="text-velor-secondary hover:text-white">سياسة الخصوصية</Link>.</span>
            </label>

            <Button type="submit" loading={loading} className="w-full">{loading ? 'جاري إنشاء المساحة…' : 'أنشئ مساحة VELOR'} {!loading && <ArrowRight className="h-4 w-4 rotate-180" />}</Button>

            {googleAuthEnabled && (
              <>
                <div className="flex items-center gap-3 py-1"><span className="h-px flex-1 bg-white/[0.07]" /><span className="text-[11px] font-bold text-velor-secondary">أو تابع باستخدام</span><span className="h-px flex-1 bg-white/[0.07]" /></div>
                <div className="flex justify-center overflow-hidden rounded-xl"><GoogleLogin onSuccess={handleGoogleSuccess} onError={() => setError('تعذّر التسجيل بحساب Google.')} theme="filled_black" text="signup_with" shape="rectangular" width={380} /></div>
              </>
            )}
          </form>

          <div className="mt-6 border-t border-white/[0.07] pt-5 text-center text-xs text-velor-muted">لديك مساحة بالفعل؟ <Link to="/login" className="font-semibold text-[#d9c4ff] transition hover:text-white">سجّل الدخول</Link></div>
          <p className="mt-5 flex items-center justify-center gap-1.5 text-[10px] text-velor-muted"><ShieldCheck className="h-3.5 w-3.5 text-velor-green" /> بيانات كل نشاط معزولة عن الأنشطة الأخرى.</p>
        </div>
      </section>
    </main>
  );
}
