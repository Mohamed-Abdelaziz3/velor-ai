import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Eye, EyeOff, Lock, Mail, ShieldCheck, Sparkles } from 'lucide-react';
import { GoogleLogin } from '@react-oauth/google';
import { googleAuth, login } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import AuthHero from '../components/AuthHero';
import { VelorLogo } from '../components/velor/VelorLogo';
import { Badge, Button, Field } from '../components/velor/ui';

export default function Login() {
  const [formData, setFormData] = useState({ email: '', password: '' });
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const { loginUser, isAuthenticated } = useAuth();
  const googleAuthEnabled = import.meta.env.VITE_ENABLE_GOOGLE_AUTH === 'true';
  const isOnboardingLogin = searchParams.get('onboarding') === '1';

  useEffect(() => {
    const suggestedEmail = searchParams.get('email');
    if (suggestedEmail) setFormData((current) => ({ ...current, email: suggestedEmail }));
  }, [searchParams]);

  useEffect(() => {
    if (!isAuthenticated) return;
    const next = searchParams.get('next');
    navigate(next?.startsWith('/') ? next : isOnboardingLogin ? '/onboarding' : '/dashboard', { replace: true });
  }, [isAuthenticated, isOnboardingLogin, navigate, searchParams]);

  const onChange = (event) => {
    setFormData((current) => ({ ...current, [event.target.name]: event.target.value }));
    if (error) setError('');
  };

  const finishLogin = (data) => {
    loginUser(data);
    const next = searchParams.get('next') || location.state?.next;
    navigate(next?.startsWith('/') ? next : isOnboardingLogin ? '/onboarding' : '/dashboard', { replace: true });
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError('');
    try {
      const { data } = await login(formData);
      if (!data?.success) throw new Error('login_failed');
      finishLogin(data);
    } catch (requestError) {
      setError(requestError.response?.data?.message || requestError.response?.data?.detail || 'تعذّر تسجيل الدخول. راجع البريد وكلمة المرور ثم حاول مرة أخرى.');
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleSuccess = async (credentialResponse) => {
    setLoading(true);
    setError('');
    try {
      const { data } = await googleAuth({ token: credentialResponse.credential });
      if (data?.success) finishLogin(data);
    } catch (requestError) {
      setError(requestError.response?.data?.message || requestError.response?.data?.detail || 'تعذّر إكمال تسجيل الدخول بحساب Google.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen text-[#f0eeff]" dir="ltr" style={{ background: 'var(--velor-bg)' }}>
      <AuthHero mode="login" />

      {/* ─── Right Panel: Login Form ─── */}
      <section
        className="relative flex min-h-screen w-full flex-col items-center justify-center overflow-hidden px-6 py-12 lg:w-[44%] lg:px-10"
        dir="rtl"
      >
        {/* Ambient blobs */}
        <div
          className="pointer-events-none absolute -right-32 -top-24 h-72 w-72 rounded-full opacity-60 blur-[100px]"
          style={{ background: 'radial-gradient(circle, rgba(139,92,246,0.18) 0%, transparent 70%)' }}
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute bottom-0 left-0 h-48 w-48 rounded-full opacity-30 blur-[80px]"
          style={{ background: 'radial-gradient(circle, rgba(56,189,248,0.12) 0%, transparent 70%)' }}
          aria-hidden="true"
        />

        {/* Form container */}
        <div className="relative z-10 w-full max-w-[400px] animate-velor-in">

          {/* Logo — shown on mobile only (hero hides on small screens) */}
          <Link to="/" className="mb-8 inline-flex lg:hidden" aria-label="العودة إلى VELOR">
            <VelorLogo size={32} wordmarkClassName="text-sm font-bold" />
          </Link>

          {/* Header */}
          <div className="mb-8">
            <Badge tone={isOnboardingLogin ? 'purple' : 'neutral'} className="mb-4">
              {isOnboardingLogin ? (
                <><Sparkles className="h-3 w-3" /> خطوة واحدة قبل الإعداد</>
              ) : (
                <><ShieldCheck className="h-3 w-3" /> دخول آمن لمساحة العمل</>
              )}
            </Badge>

            <h1 className="text-[2.2rem] font-extrabold tracking-[-0.05em] text-white leading-tight">
              مرحبًا بعودتك.
            </h1>
            <p className="mt-2.5 text-sm leading-6" style={{ color: '#6b6585' }}>
              سجّل الدخول لمراجعة محادثات العملاء وإدارة مساعد المبيعات.
            </p>
          </div>

          {/* Error banner */}
          {error && (
            <div
              className="mb-5 flex items-start gap-2.5 rounded-xl border p-3.5 text-xs leading-5 animate-velor-in"
              role="alert"
              style={{
                borderColor: 'rgba(248,113,113,0.2)',
                background: 'rgba(248,113,113,0.06)',
                color: '#fca5a5',
              }}
            >
              <span className="mt-px h-4 w-4 shrink-0 rounded-full text-center text-[10px] font-bold leading-4" style={{ background: 'rgba(248,113,113,0.2)', color: '#f87171' }}>!</span>
              {error}
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">

            {/* Email */}
            <Field
              label="البريد الإلكتروني"
              icon={Mail}
              type="email"
              name="email"
              value={formData.email}
              onChange={onChange}
              placeholder="you@company.com"
              required
              autoComplete="email"
              disabled={loading}
            />

            {/* Password */}
            <div>
              <label className="block">
                <span className="mb-2 flex items-center justify-between text-xs font-semibold" style={{ color: '#b0aacb' }}>
                  <span>كلمة المرور</span>
                  <span className="font-normal" style={{ color: '#6b6585' }}>٦ أحرف أو أكثر</span>
                </span>
                <span className="relative block">
                  <Lock className="pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2" style={{ color: '#6b6585' }} />
                  <input
                    className="velor-input pr-10 pl-10"
                    type={showPassword ? 'text' : 'password'}
                    name="password"
                    value={formData.password}
                    onChange={onChange}
                    placeholder="أدخل كلمة المرور"
                    required
                    autoComplete="current-password"
                    disabled={loading}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute left-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg transition-all duration-200 hover:bg-white/5"
                    style={{ color: '#6b6585' }}
                    aria-label={showPassword ? 'إخفاء كلمة المرور' : 'إظهار كلمة المرور'}
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </span>
              </label>
              <p className="mt-1.5 text-[10px]" style={{ color: '#6b6585' }}>
                تحتاج مساعدة؟ تواصل مع مالك مساحة العمل.
              </p>
            </div>

            {/* Submit */}
            <Button type="submit" loading={loading} className="w-full mt-2 min-h-[3rem] text-[0.9rem]">
              {loading ? 'جاري فتح المساحة…' : (
                <>الدخول إلى VELOR <ArrowLeft className="h-4 w-4" /></>
              )}
            </Button>

            {/* Google OAuth */}
            {googleAuthEnabled && (
              <>
                <div className="flex items-center gap-3 py-1">
                  <span className="h-px flex-1" style={{ background: 'rgba(255,255,255,0.07)' }} />
                  <span className="text-[11px] font-bold" style={{ color: '#8882a2' }}>أو تابع باستخدام</span>
                  <span className="h-px flex-1" style={{ background: 'rgba(255,255,255,0.07)' }} />
                </div>
                <div className="flex justify-center overflow-hidden rounded-xl">
                  <GoogleLogin
                    onSuccess={handleGoogleSuccess}
                    onError={() => setError('تعذّر تسجيل الدخول بحساب Google.')}
                    theme="filled_black"
                    text="signin_with"
                    shape="rectangular"
                    width={380}
                  />
                </div>
              </>
            )}
          </form>

          {/* Footer */}
          <div className="mt-8 border-t pt-6 text-center text-xs" style={{ borderColor: 'rgba(255,255,255,0.06)', color: '#6b6585' }}>
            جديد على VELOR؟{' '}
            <Link
              to="/signup"
              className="font-bold transition-colors duration-200 hover:text-white"
              style={{ color: '#c4b5fd' }}
            >
              أنشئ مساحة عمل
            </Link>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-[10px]" style={{ color: '#6b6585' }}>
            <span className="flex items-center gap-1.5">
              <ShieldCheck className="h-3.5 w-3.5" style={{ color: '#34d399' }} />
              جلسة مشفّرة
            </span>
            <Link to="/terms" className="transition-colors duration-200 hover:text-white">الشروط</Link>
            <Link to="/privacy" className="transition-colors duration-200 hover:text-white">الخصوصية</Link>
          </div>
        </div>
      </section>
    </main>
  );
}
