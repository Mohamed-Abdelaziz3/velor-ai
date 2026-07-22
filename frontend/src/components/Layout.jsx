import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { ChevronDown, Command, LogOut, Search, UserRound, X } from 'lucide-react';
import Sidebar from './Sidebar';
import api, { logout } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { VelorLogo, VelorMark } from './velor/VelorLogo';

const commandItems = [
  { label: 'افتح مركز المتابعة',            path: '/dashboard',   keywords: 'الرئيسية ملخص مؤشرات overview metrics home' },
  { label: 'افتح المحادثات',               path: '/inbox',        keywords: 'دردشة واتساب عملاء chat whatsapp customers' },
  { label: 'افتح التحليلات',               path: '/analytics',    keywords: 'تقارير تحويل analytics reports conversion' },
  { label: 'عدّل سلوك الذكاء الاصطناعي',   path: '/automations',  keywords: 'بوت أتمتة تعليمات ضوابط bot automation prompt guardrails' },
  { label: 'أدر القنوات',                  path: '/onboarding',   keywords: 'إعداد واتساب دردشة الموقع ربط setup whatsapp web chat connect' },
  { label: 'افتح الإعدادات',               path: '/settings',     keywords: 'حساب ملف إشعارات account profile notifications' },
  { label: 'افتح الاشتراك والفوترة',       path: '/billing',      keywords: 'باقة استخدام فواتير plan usage invoices' },
];

const routeNames = {
  dashboard:   'مركز المتابعة',
  inbox:       'المحادثات',
  analytics:   'التحليلات',
  automations: 'سلوك الذكاء الاصطناعي',
  onboarding:  'إعداد القنوات',
  settings:    'الإعدادات',
  billing:     'الاشتراك والفوترة',
};

export default function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { logoutUser } = useAuth();
  const searchRef = useRef(null);
  const [commandOpen, setCommandOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [profile, setProfile] = useState({ company_name: 'مساحة عمل VELOR', email: '' });
  const [activeIdx, setActiveIdx] = useState(-1);

  useEffect(() => {
    api.get('/me').then(({ data }) => setProfile(data)).catch(() => {});
  }, []);

  useEffect(() => {
    const handleKeyDown = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setCommandOpen((open) => !open);
      }
      if (event.key === 'Escape') {
        setCommandOpen(false);
        setProfileOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  useEffect(() => {
    if (commandOpen) {
      window.setTimeout(() => searchRef.current?.focus(), 30);
      setActiveIdx(-1);
    }
  }, [commandOpen]);

  const filteredCommands = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return commandItems;
    return commandItems.filter((item) => `${item.label} ${item.keywords}`.toLowerCase().includes(needle));
  }, [query]);

  const goTo = (path) => {
    navigate(path);
    setCommandOpen(false);
    setQuery('');
  };

  const handleLogout = async () => {
    try {
      await logout();
    } catch {
      // Clear the client session even when the server is unreachable.
    } finally {
      logoutUser();
      navigate('/login');
    }
  };

  const handleCommandKeyDown = (event) => {
    if (!filteredCommands.length) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, filteredCommands.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (event.key === 'Enter' && activeIdx >= 0) {
      goTo(filteredCommands[activeIdx].path);
    }
  };

  const routeKey = location.pathname.split('/')[1];
  const currentRoute = routeNames[routeKey] || 'VELOR';
  const isWorkspaceDetail = /^\/inbox(\/.*)?\/?$/.test(location.pathname);

  return (
    <div className="flex h-screen overflow-hidden text-velor-text" dir="rtl" lang="ar" style={{ background: 'var(--velor-bg)' }}>
      <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="pointer-events-none fixed inset-0 overflow-hidden" aria-hidden="true">
          <div className="absolute -right-52 -top-72 h-[560px] w-[560px] rounded-full bg-violet-500/[0.055] blur-[190px]" />
          <div className="absolute -bottom-72 -left-48 h-[480px] w-[480px] rounded-full bg-sky-500/[0.035] blur-[180px]" />
        </div>

        <header className="relative z-30 h-[72px] shrink-0 border-b border-white/[0.065] bg-[#080b13]/88 px-3 backdrop-blur-2xl sm:px-5">
          <div className="mx-auto flex h-full w-full max-w-[1680px] items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-4">
              <Link to="/dashboard" className="hidden shrink-0 items-center lg:flex" aria-label="VELOR — مركز المتابعة">
                <VelorLogo size={30} wordmarkClassName="text-[14px] font-extrabold tracking-[.2em] text-white" />
              </Link>

              <Link to="/dashboard" className="flex min-w-0 items-center gap-2.5 lg:hidden" aria-label="VELOR — مركز المتابعة">
                <VelorMark size={31} decorative />
                <div className="min-w-0">
                  <p className="truncate text-[13px] font-extrabold text-white">{currentRoute}</p>
                  <p className="truncate text-[9px] text-velor-muted">{profile.company_name || 'مساحة عمل VELOR'}</p>
                </div>
              </Link>

              <span className="hidden h-6 w-px bg-white/[0.08] lg:block" aria-hidden="true" />
              <Sidebar mode="desktop" />
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={() => setCommandOpen(true)}
                className="hidden h-10 min-w-[176px] items-center justify-between rounded-xl border border-white/[0.07] bg-white/[0.025] px-3 text-[11px] text-velor-muted transition hover:border-white/[0.12] hover:bg-white/[0.045] hover:text-velor-secondary 2xl:flex"
              >
                <span className="inline-flex items-center gap-2"><Search className="h-3.5 w-3.5" /> ابحث أو انتقل</span>
                <span className="inline-flex items-center gap-1 rounded-md border border-white/[0.08] bg-white/[0.035] px-1.5 py-0.5 text-[9px]"><Command className="h-2.5 w-2.5" /> K</span>
              </button>
              <button
                type="button"
                onClick={() => setCommandOpen(true)}
                className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/[0.07] bg-white/[0.025] text-velor-muted transition hover:bg-white/[0.05] hover:text-white 2xl:hidden"
                aria-label="البحث والانتقال السريع"
              >
                <Search className="h-[17px] w-[17px]" />
              </button>

              <div className="relative">
                <button
                  type="button"
                  onClick={() => setProfileOpen((open) => !open)}
                  className="flex h-10 items-center gap-2 rounded-xl border border-white/[0.07] bg-white/[0.025] px-2 text-right transition hover:border-white/[0.12] hover:bg-white/[0.045]"
                  aria-label="قائمة الحساب"
                  aria-expanded={profileOpen}
                >
                  <span className="flex h-7 w-7 items-center justify-center rounded-lg border border-violet-400/15 bg-violet-400/10 text-velor-violet">
                    <UserRound className="h-3.5 w-3.5" />
                  </span>
                  <span className="hidden max-w-[112px] truncate text-[11px] font-bold text-white xl:block">{profile.company_name || 'VELOR'}</span>
                  <ChevronDown className="hidden h-3 w-3 text-velor-muted xl:block" />
                </button>

                {profileOpen && (
                  <div className="absolute left-0 top-12 w-64 overflow-hidden rounded-2xl border border-white/[0.09] bg-[#0c101b]/98 p-2 shadow-[0_32px_100px_rgba(0,0,0,.65)] backdrop-blur-2xl animate-velor-in">
                    <div className="border-b border-white/[0.07] px-3 py-3">
                      <p className="truncate text-xs font-bold text-white">{profile.company_name || 'مساحة عمل VELOR'}</p>
                      <p className="mt-1 truncate text-[10px] text-velor-muted">{profile.email || 'حساب مساحة العمل'}</p>
                    </div>
                    <button type="button" onClick={handleLogout} className="mt-1 flex min-h-11 w-full items-center gap-2 rounded-xl px-3 text-xs font-semibold text-rose-300 transition hover:bg-rose-400/[0.08]">
                      <LogOut className="h-4 w-4" /> تسجيل الخروج
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </header>

        <Sidebar mode="mobile" />

        {/* Main content */}
        <main className={`relative flex min-h-0 flex-1 flex-col pb-24 lg:pb-0 ${isWorkspaceDetail ? 'overflow-hidden' : 'overflow-y-auto'}`}>
          <Outlet />
        </main>
      </div>

      {/* ─── Command Palette ─── */}
      {commandOpen && (
        <div
          className="fixed inset-0 z-[80] flex items-start justify-center px-4 pt-[10vh]"
          role="dialog"
          aria-modal="true"
          aria-label="لوحة الانتقال السريع"
          style={{ background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)' }}
          onMouseDown={(event) => { if (event.target === event.currentTarget) setCommandOpen(false); }}
        >
          <div
            className="w-full max-w-xl overflow-hidden rounded-2xl animate-velor-in"
            style={{
              background: 'rgba(10,10,22,0.97)',
              border: '1px solid rgba(130,120,220,0.15)',
              boxShadow: '0 1px 0 0 rgba(255,255,255,0.06) inset, 0 60px 180px rgba(0,0,0,0.7), 0 0 1px rgba(0,0,0,0.5)',
            }}
          >
            {/* Search input */}
            <div className="flex items-center border-b px-4" style={{ borderColor: 'rgba(130,120,220,0.1)' }}>
              <Search className="h-4 w-4 shrink-0" style={{ color: '#6b6585' }} />
              <input
                ref={searchRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={handleCommandKeyDown}
                className="h-14 min-w-0 flex-1 bg-transparent px-3 text-sm text-white outline-none"
                style={{ caretColor: '#8b5cf6' }}
                placeholder="ابحث في الصفحات والإجراءات…"
              />
              <button
                type="button"
                onClick={() => setCommandOpen(false)}
                className="flex h-8 w-8 items-center justify-center rounded-lg transition-all duration-200 hover:bg-white/5"
                style={{ color: '#6b6585' }}
                aria-label="إغلاق لوحة الانتقال"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Results */}
            <div className="max-h-[380px] overflow-y-auto p-2">
              {filteredCommands.map((item, i) => (
                <button
                  key={item.path}
                  type="button"
                  onClick={() => goTo(item.path)}
                  className="flex min-h-12 w-full items-center gap-3 rounded-xl px-3 text-right text-sm transition-all duration-150"
                  style={{
                    background: i === activeIdx ? 'rgba(139,92,246,0.1)' : 'transparent',
                    color: i === activeIdx ? '#c4b5fd' : '#b0aacb',
                  }}
                  onMouseEnter={() => setActiveIdx(i)}
                >
                  <span
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
                    style={{
                      background: 'linear-gradient(135deg, rgba(139,92,246,0.15), rgba(99,102,241,0.1))',
                      border: '1px solid rgba(139,92,246,0.15)',
                    }}
                  >
                    <VelorMark size={14} variant="monochrome" decorative className="text-purple-400" />
                  </span>
                  <span className="flex-1">{item.label}</span>
                  {i === activeIdx && (
                    <span
                      className="rounded-md border px-1.5 py-0.5 text-[9px]"
                      style={{ border: '1px solid rgba(139,92,246,0.3)', color: '#a78bfa' }}
                    >
                      ↩
                    </span>
                  )}
                </button>
              ))}
              {filteredCommands.length === 0 && (
                <p className="px-3 py-10 text-center text-xs" style={{ color: '#6b6585' }}>
                  لا توجد صفحة أو إجراء مطابق.
                </p>
              )}
            </div>

            {/* Footer hint */}
            <div className="flex items-center justify-between border-t px-4 py-2" style={{ borderColor: 'rgba(130,120,220,0.08)' }}>
              <div className="flex items-center gap-3 text-[10px]" style={{ color: '#8882a2' }}>
                <span className="flex items-center gap-1">
                  <kbd className="rounded border px-1" style={{ border: '1px solid rgba(255,255,255,0.1)' }}>↑↓</kbd> للتنقل
                </span>
                <span className="flex items-center gap-1">
                  <kbd className="rounded border px-1" style={{ border: '1px solid rgba(255,255,255,0.1)' }}>↩</kbd> للفتح
                </span>
                <span className="flex items-center gap-1">
                  <kbd className="rounded border px-1" style={{ border: '1px solid rgba(255,255,255,0.1)' }}>Esc</kbd> للإغلاق
                </span>
              </div>
              <span className="text-[10px]" style={{ color: '#8882a2' }}>VELOR</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
