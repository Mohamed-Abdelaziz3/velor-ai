import { useEffect, useMemo, useRef, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Bell, Command, Menu, Search, UserRound, X } from 'lucide-react';
import Sidebar from './Sidebar';
import api from '../services/api';
import { Badge } from './velor/ui';
import { VelorMark } from './velor/VelorLogo';

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

const routeIcons = {
  dashboard:   '⚡',
  inbox:       '💬',
  analytics:   '📊',
  automations: '🤖',
  onboarding:  '⚙️',
  settings:    '⚙️',
  billing:     '💳',
};

export default function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const searchRef = useRef(null);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [notificationOpen, setNotificationOpen] = useState(false);
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
        setNotificationOpen(false);
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
    <div className="flex h-screen overflow-hidden text-[#f0eeff]" dir="rtl" lang="ar" style={{ background: 'var(--velor-bg)' }}>
      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed((value) => !value)}
        mobileOpen={mobileOpen}
        onMobileClose={() => setMobileOpen(false)}
      />

      <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* Ambient background — very subtle, just adds warmth */}
        <div className="pointer-events-none fixed inset-0 overflow-hidden" aria-hidden="true">
          <div className="absolute -right-48 -top-64 h-[500px] w-[500px] rounded-full opacity-40 blur-[200px]"
            style={{ background: 'radial-gradient(circle, rgba(139,92,246,0.06) 0%, transparent 70%)' }} />
        </div>

        {/* ─── Premium Header ─── */}
        <header
          className="relative z-30 flex h-16 shrink-0 items-center justify-between px-4 sm:px-5 xl:px-6"
          style={{
            background: 'rgba(8,8,18,0.80)',
            backdropFilter: 'blur(32px) saturate(1.4)',
            WebkitBackdropFilter: 'blur(32px) saturate(1.4)',
            borderBottom: '1px solid rgba(130,120,220,0.08)',
            boxShadow: '0 1px 0 0 rgba(255,255,255,0.02) inset',
          }}
        >
          {/* Left: Route info */}
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-all duration-200 hover:bg-white/[0.06] lg:hidden"
              style={{ color: '#6b6585' }}
              aria-label="فتح قائمة التنقل"
            >
              <Menu className="h-5 w-5" />
            </button>

            {/* Breadcrumb */}
            <div className="flex min-w-0 items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg" style={{
                background: 'linear-gradient(135deg, rgba(139,92,246,0.15), rgba(99,102,241,0.1))',
                border: '1px solid rgba(139,92,246,0.15)',
              }}>
                <span className="text-sm">{routeIcons[routeKey] || '⚡'}</span>
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm font-bold tracking-[-0.02em] text-white">{currentRoute}</p>
                <p className="mt-px hidden text-[10px] sm:block" style={{ color: '#6b6585' }}>
                  {profile.company_name || 'مساحة عمل VELOR'}
                </p>
              </div>
            </div>
          </div>

          {/* Right: Actions */}
          <div className="flex items-center gap-1.5 sm:gap-2">

            {/* Search bar — desktop */}
            <button
              type="button"
              onClick={() => setCommandOpen(true)}
              className="hidden h-9 w-[200px] items-center justify-between rounded-xl px-3 text-xs transition-all duration-200 hover:border-[rgba(130,120,220,0.2)] md:flex"
              style={{
                border: '1px solid rgba(130,120,220,0.1)',
                background: 'rgba(255,255,255,0.025)',
                color: '#6b6585',
              }}
            >
              <span className="inline-flex items-center gap-2">
                <Search className="h-3.5 w-3.5" />
                ابحث أو انتقل
              </span>
              <span className="inline-flex items-center gap-1 rounded-lg border px-1.5 py-0.5 text-[9px]"
                style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.04)' }}>
                <Command className="h-2.5 w-2.5" /> K
              </span>
            </button>

            {/* Search icon — mobile */}
            <button
              type="button"
              onClick={() => setCommandOpen(true)}
              className="flex h-9 w-9 items-center justify-center rounded-xl transition-all duration-200 hover:bg-white/[0.05] md:hidden"
              style={{ color: '#6b6585' }}
              aria-label="البحث"
            >
              <Search className="h-[17px] w-[17px]" />
            </button>

            {/* Protected badge */}
            <Badge tone="neutral" className="hidden text-[10px] sm:inline-flex">مساحة محمية</Badge>

            {/* Notifications */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setNotificationOpen((open) => !open)}
                className="relative flex h-9 w-9 items-center justify-center rounded-xl transition-all duration-200 hover:bg-white/[0.05]"
                style={{ color: '#6b6585' }}
                aria-label="الإشعارات"
                aria-expanded={notificationOpen}
              >
                <Bell className="h-[17px] w-[17px]" />
              </button>

              {notificationOpen && (
                <div
                  className="absolute right-0 top-11 w-[min(340px,calc(100vw-2rem))] rounded-2xl p-3 animate-velor-in"
                  style={{
                    background: 'rgba(10,10,22,0.96)',
                    backdropFilter: 'blur(32px)',
                    WebkitBackdropFilter: 'blur(32px)',
                    border: '1px solid rgba(130,120,220,0.12)',
                    boxShadow: '0 1px 0 0 rgba(255,255,255,0.04) inset, 0 40px 120px rgba(0,0,0,0.6)',
                  }}
                >
                  <div className="flex items-center justify-between border-b pb-3" style={{ borderColor: 'rgba(130,120,220,0.08)' }}>
                    <div className="flex items-center gap-2">
                      <span className="flex h-6 w-6 items-center justify-center rounded-lg" style={{ background: 'rgba(139,92,246,0.15)' }}>
                        <Bell className="h-3 w-3 text-purple-400" />
                      </span>
                      <p className="text-xs font-bold text-white">الإشعارات</p>
                    </div>
                    <Badge tone="neutral">المصدر غير متصل</Badge>
                  </div>
                  <div className="py-8 text-center">
                    <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl" style={{
                      background: 'linear-gradient(135deg, rgba(139,92,246,0.1), rgba(99,102,241,0.05))',
                      border: '1px solid rgba(139,92,246,0.15)',
                    }}>
                      <Bell className="h-5 w-5 text-purple-400 opacity-60" />
                    </div>
                    <p className="text-xs font-semibold" style={{ color: '#b0aacb' }}>مركز الإشعارات غير متاح حاليًا</p>
                    <p className="mt-1.5 mx-auto max-w-[240px] text-[10px] leading-5" style={{ color: '#6b6585' }}>
                      لا يوجد مصدر موثوق للأحداث غير المقروءة متصل بهذه اللوحة.
                    </p>
                  </div>
                </div>
              )}
            </div>

            {/* User avatar */}
            <div
              className="flex h-9 items-center gap-2 rounded-xl px-2 pr-2.5 transition-all duration-200 hover:border-[rgba(130,120,220,0.15)] hover:bg-white/[0.03]"
              style={{
                border: '1px solid rgba(130,120,220,0.08)',
                background: 'rgba(255,255,255,0.025)',
              }}
            >
              <div className="flex h-6 w-6 items-center justify-center rounded-lg" style={{
                background: 'linear-gradient(135deg, rgba(139,92,246,0.3), rgba(99,102,241,0.2))',
                border: '1px solid rgba(139,92,246,0.2)',
              }}>
                <UserRound className="h-3.5 w-3.5 text-purple-400" />
              </div>
              <span className="hidden max-w-[120px] truncate text-[11px] font-bold text-white xl:block">
                {profile.company_name || 'VELOR'}
              </span>
            </div>
          </div>
        </header>

        {/* Main content */}
        <main className={`relative z-10 flex min-h-0 flex-1 flex-col pb-24 lg:pb-0 ${isWorkspaceDetail ? 'overflow-hidden' : 'overflow-y-auto'}`}>
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
