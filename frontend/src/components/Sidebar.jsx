import { Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  MessageSquareText,
  Settings,
  SlidersHorizontal,
} from 'lucide-react';
import { useGlobalEvents } from '../contexts/GlobalEventContext';
import { cx } from './velor/ui';

const navigation = [
  { path: '/dashboard', label: 'مركز المتابعة', shortLabel: 'المتابعة', icon: LayoutDashboard },
  { path: '/inbox', label: 'المحادثات', shortLabel: 'المحادثات', icon: MessageSquareText },
  { path: '/onboarding', label: 'القنوات', shortLabel: 'القنوات', icon: SlidersHorizontal },
  { path: '/settings', label: 'الإعدادات', shortLabel: 'الإعدادات', title: 'الإعدادات — الكتالوج والسياسات', icon: Settings },
];

const isActiveRoute = (pathname, path) => {
  const activePath = pathname;
  return activePath === path || (path === '/inbox' && activePath.startsWith('/inbox/'));
};

export default function Sidebar({ mode = 'all' }) {
  const location = useLocation();
  const { connectionState } = useGlobalEvents();
  const connected = connectionState === 'connected';

  return (
    <>
      {mode !== 'mobile' && <nav
        className="hidden min-w-0 items-center gap-1 rounded-2xl border border-white/[0.07] bg-white/[0.025] p-1 lg:flex"
        aria-label="التنقل الرئيسي"
      >
        {navigation.map((item) => {
          const Icon = item.icon;
          const active = isActiveRoute(location.pathname, item.path);

          return (
            <Link
              key={item.path}
              to={item.path}
              title={item.title}
              className={cx(
                'group relative flex h-10 items-center gap-2 rounded-xl px-3 text-xs font-semibold transition-all duration-200 xl:px-4',
                active
                  ? 'bg-white/[0.09] text-white shadow-[0_1px_0_rgba(255,255,255,0.08)_inset]'
                  : 'text-velor-secondary hover:bg-white/[0.045] hover:text-white',
              )}
              aria-current={active ? 'page' : undefined}
            >
              <Icon className={cx('h-4 w-4 shrink-0', active ? 'text-velor-violet' : 'text-velor-muted group-hover:text-velor-secondary')} />
              <span>{item.label}</span>
              {active && <span className="absolute inset-x-3 -bottom-[5px] h-px bg-gradient-to-r from-transparent via-velor-purple to-transparent" aria-hidden="true" />}
            </Link>
          );
        })}

      </nav>}

      {mode !== 'desktop' && <nav
        className="fixed inset-x-3 z-20 grid h-[68px] grid-cols-4 items-center rounded-[22px] border border-white/[0.09] bg-[#0b0e18]/95 px-1.5 shadow-[0_24px_80px_rgba(0,0,0,.62),0_1px_0_rgba(255,255,255,.06)_inset] backdrop-blur-2xl lg:hidden"
        style={{ bottom: 'max(.75rem, env(safe-area-inset-bottom))' }}
        aria-label="التنقل على الهاتف"
      >
        {navigation.map((item) => {
          const Icon = item.icon;
          const active = isActiveRoute(location.pathname, item.path);

          return (
            <Link
              key={item.path}
              to={item.path}
              className={cx(
                'relative flex min-h-14 flex-col items-center justify-center gap-1 rounded-2xl px-1 text-[10px] font-bold transition-all duration-200',
                active ? 'text-white' : 'text-velor-muted active:bg-white/[0.05]',
              )}
              aria-current={active ? 'page' : undefined}
            >
              <span className={cx(
                'flex h-7 w-10 items-center justify-center rounded-full transition-all duration-200',
                active ? 'bg-velor-purple/20 text-velor-violet' : 'text-velor-muted',
              )}>
                <Icon className="h-[17px] w-[17px]" />
              </span>
              <span>{item.shortLabel}</span>
              {active && <span className="absolute -bottom-0.5 h-1 w-1 rounded-full bg-velor-purple" aria-hidden="true" />}
            </Link>
          );
        })}
      </nav>}
    </>
  );
}
