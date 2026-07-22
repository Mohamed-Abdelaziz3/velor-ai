import { useMemo } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  ChevronsLeft,
  ChevronsRight,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  Settings,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import { logout } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { useGlobalEvents } from '../contexts/GlobalEventContext';
import { VelorLogo, VelorMark } from './velor/VelorLogo';
import { cx } from './velor/ui';
import { formatClockTime } from '../utils/timeUtils';

const primaryNavigation = [
  { path: '/dashboard', label: 'مركز المتابعة', shortLabel: 'المتابعة', icon: LayoutDashboard, color: 'purple' },
  { path: '/inbox', label: 'المحادثات', shortLabel: 'المحادثات', icon: MessageSquareText, color: 'blue' },
];

const workspaceNavigation = [
  { path: '/onboarding', label: 'إعداد القنوات', shortLabel: 'القنوات', icon: SlidersHorizontal, color: 'blue' },
  { path: '/settings', label: 'الكتالوج والسياسات', shortLabel: 'المصادر', icon: Settings, color: 'neutral' },
];

const _streamStates = {
  connected:    { label: 'متصل',           tone: 'green',   title: 'التحديثات المباشرة متصلة',   detail: 'نستقبل أحداث مساحة العمل الموثقة.' },
  connecting:   { label: 'جاري الاتصال',   tone: 'blue',    title: 'جاري ربط التحديثات',         detail: 'لم يبدأ تدفق الأحداث بعد.' },
  reconnecting: { label: 'إعادة اتصال',    tone: 'amber',   title: 'انقطع التحديث المباشر',      detail: 'قد تتأخر البيانات حتى يكتمل الاتصال.' },
  disconnected: { label: 'غير متصل',       tone: 'red',     title: 'التحديثات المباشرة متوقفة',  detail: 'حدّث الصفحة لإعادة محاولة الاتصال.' },
  idle:         { label: 'غير متصل',       tone: 'neutral', title: 'التحديثات غير مفعّلة',       detail: 'لا يوجد اتصال نشط بمصدر الأحداث.' },
};

export default function Sidebar({ collapsed, onToggle, mobileOpen, onMobileClose }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { logoutUser } = useAuth();
  const { connectionState, connectedAt } = useGlobalEvents();
  const connectedTime = connectionState === 'connected' ? formatClockTime(connectedAt, 'ar-EG') : '';

  const navGroups = useMemo(() => [
    { label: 'مساحة العمل', items: primaryNavigation },
    { label: 'الإدارة', items: workspaceNavigation },
  ], []);

  const handleLogout = async () => {
    try {
      await logout();
    } catch {
      // The client session still needs to be cleared when the server is unreachable.
    } finally {
      logoutUser();
      navigate('/login');
    }
  };

  const sidebarContent = (
    <div className="flex h-full flex-col overflow-hidden" style={{
      background: 'linear-gradient(180deg, rgba(11,11,25,0.98) 0%, rgba(8,8,18,0.99) 100%)',
      borderInlineEnd: '1px solid rgba(130,120,220,0.12)',
      borderStartEndRadius: 'var(--velor-radius-panel)',
      borderEndEndRadius: 'var(--velor-radius-panel)',
    }}>
      {/* Logo area */}
      <div className={cx(
        'relative z-10 flex h-16 shrink-0 items-center px-4',
        collapsed ? 'justify-center' : 'justify-between',
      )}>
        <Link to="/dashboard" aria-label="مركز متابعة VELOR" onClick={onMobileClose} className="flex items-center gap-3">
          {collapsed ? (
            <VelorMark size={32} decorative />
          ) : (
            <VelorLogo size={30} wordmarkClassName="text-[15px] font-bold tracking-widest text-white" />
          )}
        </Link>
        {!collapsed && (
          <button
            type="button"
            onClick={onToggle}
            className="hidden h-8 w-8 items-center justify-center rounded-xl text-[#6b6585] transition-all duration-200 hover:bg-white/[0.06] hover:text-white lg:flex"
            aria-label="طي قائمة التنقل"
          >
            <ChevronsRight className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Navigation */}
      <nav className="relative z-10 mt-3 flex-1 space-y-5 overflow-y-auto px-3 pb-2 scrollbar-hide" aria-label="التنقل الرئيسي">
        {navGroups.map((group) => (
          <div key={group.label}>
            {!collapsed && (
              <p className="mb-2 px-2 text-[11px] font-bold" style={{ color: 'var(--velor-text-secondary)', opacity: 0.7 }}>
                {group.label}
              </p>
            )}
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const Icon = item.icon;
                const href = item.path;
                const activePath = location.pathname;
                const active = activePath === item.path || (item.path === '/inbox' && activePath.startsWith('/inbox/'));

                return (
                  <Link
                    key={item.path}
                    to={href}
                    onClick={onMobileClose}
                    title={collapsed ? item.label : undefined}
                    className={cx(
                      'group relative flex min-h-[42px] items-center rounded-xl text-sm font-medium transition-all duration-200',
                      collapsed ? 'justify-center px-0' : 'gap-3 px-3',
                      active
                        ? 'bg-white/[0.055]'
                        : 'hover:bg-white/[0.03]',
                    )}
                    aria-current={active ? 'page' : undefined}
                  >
                    {active && <span className="nav-active-indicator" />}

                    <Icon className={cx(
                      'h-[18px] w-[18px] shrink-0 transition-colors duration-200',
                      active ? 'text-white' : 'text-[#7b7597] group-hover:text-white',
                    )} />

                    {!collapsed && (
                      <span className={cx(
                        'truncate transition-colors duration-200',
                        active ? 'text-white' : 'text-[#8882a2] group-hover:text-[#c8c4e4]',
                      )}>
                        {item.label}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Bottom section */}
      <div className="relative z-10 mt-2 px-3 pb-5">
        {/* Connection status indicator */}
        {!collapsed && (
          <div className="mb-3.5 flex items-center justify-between px-2 text-[10px]" style={{ color: '#6b6585' }}>
            <span className="flex items-center gap-1.5 font-medium">
              <span 
                className={cx(
                  "h-1.5 w-1.5 rounded-full",
                  connectionState === 'connected' ? "bg-[#34d399] animate-pulse" : "bg-red-500"
                )}
                style={{
                  boxShadow: connectionState === 'connected' ? '0 0 6px rgba(52,211,153,0.6)' : '0 0 6px rgba(239,68,68,0.6)',
                }}
              />
              <span>{connectionState === 'connected' ? 'تحديث مباشر نشط' : 'التحديث متوقف'}</span>
            </span>
            {connectedTime && <span className="opacity-60">{connectedTime}</span>}
          </div>
        )}

        {/* Gradient separator */}
        <div className="mb-3 velor-separator" />

        {/* Logout button */}
        <button
          type="button"
          onClick={handleLogout}
          className={cx(
            'group flex min-h-10 w-full items-center rounded-xl text-sm font-medium transition-all duration-200',
            'hover:bg-red-500/10',
            collapsed ? 'justify-center' : 'gap-3 px-3',
          )}
          style={{ color: '#6b6585' }}
          title={collapsed ? 'تسجيل الخروج' : undefined}
        >
          <LogOut className="h-[18px] w-[18px] shrink-0 transition-colors duration-200 group-hover:text-red-400" />
          {!collapsed && (
            <span className="transition-colors duration-200 group-hover:text-red-400">تسجيل الخروج</span>
          )}
        </button>

        {/* Expand when collapsed */}
        {collapsed && (
          <button
            type="button"
            onClick={onToggle}
            className="mt-2 hidden min-h-10 w-full items-center justify-center rounded-xl text-[#6b6585] transition-all duration-200 hover:bg-white/[0.05] hover:text-white lg:flex"
            aria-label="توسيع قائمة التنقل"
          >
            <ChevronsLeft className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <aside className={cx(
        'relative z-30 hidden h-screen shrink-0 transition-[width] duration-300 lg:block',
        collapsed ? 'w-[72px]' : 'w-[252px]',
      )}>
        {sidebarContent}
      </aside>

      {/* Mobile overlay */}
      <div
        className={cx('fixed inset-0 z-50 lg:hidden', mobileOpen ? 'pointer-events-auto' : 'pointer-events-none')}
        aria-hidden={!mobileOpen}
      >
        <button
          type="button"
          className={cx(
            'absolute inset-0 bg-black/80 backdrop-blur-md transition-opacity duration-300',
            mobileOpen ? 'opacity-100' : 'opacity-0',
          )}
          onClick={onMobileClose}
          aria-label="إغلاق قائمة التنقل"
        />
        <aside className={cx(
          'absolute inset-y-0 right-0 w-[280px] shadow-2xl transition-transform duration-300',
          mobileOpen ? 'translate-x-0' : 'translate-x-full',
        )}>
          <button
            type="button"
            onClick={onMobileClose}
            className="absolute left-3 top-4 z-10 flex h-9 w-9 items-center justify-center rounded-xl hover:bg-white/5"
            style={{ color: '#6b6585' }}
            aria-label="إغلاق قائمة التنقل"
          >
            <X className="h-4 w-4" />
          </button>
          {sidebarContent}
        </aside>
      </div>

      {/* Mobile bottom nav */}
      <nav
        className="fixed inset-x-3 bottom-3 z-40 flex h-16 items-center justify-around rounded-2xl px-1 shadow-2xl lg:hidden"
        style={{
          background: 'rgba(10,10,22,0.92)',
          backdropFilter: 'blur(32px)',
          WebkitBackdropFilter: 'blur(32px)',
          border: '1px solid rgba(130,120,220,0.12)',
          boxShadow: '0 -1px 0 0 rgba(255,255,255,0.04) inset, 0 20px 60px rgba(0,0,0,0.5)',
        }}
        aria-label="التنقل على الهاتف"
      >
        {[...primaryNavigation, workspaceNavigation[1]].map((item) => {
          const Icon = item.icon;
          const href = item.path;
          const activePath = location.pathname;
          const active = activePath === item.path || (item.path === '/inbox' && activePath.startsWith('/inbox/'));
          return (
            <Link
              key={item.path}
              to={href}
              className={cx(
                'flex min-h-12 min-w-[58px] flex-col items-center justify-center gap-1 rounded-xl px-2 text-[9px] font-bold transition-all duration-200',
                active
                  ? 'text-purple-400'
                  : 'text-[#6b6585] hover:text-[#9090c0]',
              )}
            >
              <span className={cx(
                'flex h-7 w-7 items-center justify-center rounded-lg transition-all duration-200',
                active ? 'bg-purple-500/15 text-purple-400' : '',
              )}>
                <Icon className="h-[16px] w-[16px]" />
              </span>
              <span>{item.shortLabel}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}
