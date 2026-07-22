/* eslint-disable react-refresh/only-export-components */
import { ArrowUpRight, Check, ChevronDown, LoaderCircle } from 'lucide-react';
import { motion, useMotionTemplate, useMotionValue } from 'framer-motion';

export const cx = (...classes) => classes.filter(Boolean).join(' ');

/* ══════════════════════════════════════════════════════════
   BUTTON
   ══════════════════════════════════════════════════════════ */

const buttonVariants = {
  primary: 'velor-button-primary',
  secondary: 'velor-button-secondary',
  ghost: [
    'inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-transparent',
    'px-3 text-sm font-semibold transition-all duration-200',
    'text-[#8882a2] hover:border-[rgba(130,120,220,0.15)] hover:bg-white/[0.04] hover:text-white',
  ].join(' '),
  danger: [
    'inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border px-4 text-sm font-semibold',
    'border-red-500/25 bg-red-500/[0.07] text-red-400 transition-all duration-200',
    'hover:border-red-500/40 hover:bg-red-500/12',
  ].join(' '),
  success: [
    'inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border px-4 text-sm font-semibold',
    'border-emerald-500/25 bg-emerald-500/[0.07] text-emerald-400 transition-all duration-200',
    'hover:border-emerald-500/40 hover:bg-emerald-500/12',
  ].join(' '),
};

export function Button({ variant = 'primary', className, loading = false, children, disabled, type = 'button', ...props }) {
  return (
    <motion.button
      type={type}
      whileHover={disabled || loading ? {} : { scale: 1.015 }}
      whileTap={disabled || loading ? {} : { scale: 0.98 }}
      className={cx(buttonVariants[variant], className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />}
      {children}
    </motion.button>
  );
}

/* ══════════════════════════════════════════════════════════
   CARD (WITH MOUSE-TRACKING SPOTLIGHT)
   ══════════════════════════════════════════════════════════ */

export function Card({ as: Component = 'section', className, interactive = false, glow = false, children, ...props }) {
  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);

  function handleMouseMove({ currentTarget, clientX, clientY }) {
    const { left, top } = currentTarget.getBoundingClientRect();
    mouseX.set(clientX - left);
    mouseY.set(clientY - top);
  }

  // Handle generic elements like `section` dynamically with framer-motion
  const MotionComponent = Component === 'section' ? motion.section : motion(Component);

  return (
    <MotionComponent
      className={cx(
        'velor-card group relative',
        interactive && 'velor-card-interactive cursor-pointer',
        glow && 'velor-gradient-border',
        className,
      )}
      onMouseMove={interactive ? handleMouseMove : undefined}
      whileHover={interactive ? { y: -2 } : {}}
      whileTap={interactive ? { scale: 0.99 } : {}}
      {...props}
    >
      {interactive && (
        <motion.div
          className="pointer-events-none absolute -inset-px rounded-[inherit] opacity-0 transition duration-300 group-hover:opacity-100"
          style={{
            background: useMotionTemplate`
              radial-gradient(
                450px circle at ${mouseX}px ${mouseY}px,
                rgba(139, 92, 246, 0.1),
                transparent 80%
              )
            `,
          }}
        />
      )}
      {glow && (
        <div className="pointer-events-none absolute inset-0 rounded-[inherit] opacity-50" aria-hidden="true"
          style={{ background: 'linear-gradient(135deg, rgba(139,92,246,0.08) 0%, transparent 50%)' }}
        />
      )}
      <div className="relative z-10">{children}</div>
    </MotionComponent>
  );
}

/* ══════════════════════════════════════════════════════════
   BADGE
   ══════════════════════════════════════════════════════════ */

const badgeTones = {
  neutral: {
    border: 'rgba(180,170,220,0.14)',
    bg: 'rgba(255,255,255,0.055)',
    color: '#a09ab8',
    dot: '#8882a2',
    glow: 'none',
    shimmer: 'rgba(255,255,255,0.06)',
  },
  purple: {
    border: 'rgba(139,92,246,0.40)',
    bg: 'linear-gradient(135deg, rgba(139,92,246,0.18) 0%, rgba(99,102,241,0.12) 100%)',
    color: '#d4b8ff',
    dot: '#a78bfa',
    glow: '0 0 12px rgba(139,92,246,0.25)',
    shimmer: 'rgba(192,132,252,0.12)',
  },
  blue: {
    border: 'rgba(56,189,248,0.40)',
    bg: 'linear-gradient(135deg, rgba(56,189,248,0.15) 0%, rgba(59,130,246,0.10) 100%)',
    color: '#bae6fd',
    dot: '#38bdf8',
    glow: '0 0 12px rgba(56,189,248,0.22)',
    shimmer: 'rgba(125,211,252,0.12)',
  },
  green: {
    border: 'rgba(52,211,153,0.40)',
    bg: 'linear-gradient(135deg, rgba(52,211,153,0.15) 0%, rgba(16,185,129,0.10) 100%)',
    color: '#6ee7b7',
    dot: '#34d399',
    glow: '0 0 12px rgba(52,211,153,0.25)',
    shimmer: 'rgba(110,231,183,0.12)',
  },
  amber: {
    border: 'rgba(245,158,11,0.40)',
    bg: 'linear-gradient(135deg, rgba(245,158,11,0.15) 0%, rgba(251,146,60,0.10) 100%)',
    color: '#fde68a',
    dot: '#f59e0b',
    glow: '0 0 12px rgba(245,158,11,0.22)',
    shimmer: 'rgba(252,211,77,0.12)',
  },
  red: {
    border: 'rgba(248,113,113,0.40)',
    bg: 'linear-gradient(135deg, rgba(248,113,113,0.15) 0%, rgba(239,68,68,0.10) 100%)',
    color: '#fca5a5',
    dot: '#f87171',
    glow: '0 0 12px rgba(248,113,113,0.22)',
    shimmer: 'rgba(252,165,165,0.10)',
  },
};

export function Badge({ tone = 'neutral', dot = false, className, style: extraStyle, children }) {
  const cfg = badgeTones[tone] || badgeTones.neutral;
  return (
    <motion.span
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.3 }}
      className={cx(
        'relative inline-flex items-center gap-1.5 overflow-hidden rounded-full border px-3 py-1 text-[11px] font-semibold leading-none tracking-[0.04em]',
        className,
      )}
      style={{
        borderColor: cfg.border,
        background: cfg.bg,
        color: cfg.color,
        boxShadow: cfg.glow,
        ...extraStyle,
      }}
    >
      <span
        className="pointer-events-none absolute inset-0 rounded-full"
        style={{ background: `linear-gradient(135deg, ${cfg.shimmer} 0%, transparent 60%)` }}
        aria-hidden="true"
      />
      {dot && (
        <span
          className="relative h-1.5 w-1.5 rounded-full"
          style={{
            backgroundColor: cfg.dot,
            boxShadow: `0 0 6px ${cfg.dot}`,
            animation: tone === 'green' ? 'signal-pulse 2.4s ease-in-out infinite' : 'none',
          }}
          aria-hidden="true"
        />
      )}
      <span className="relative">{children}</span>
    </motion.span>
  );
}

/* ══════════════════════════════════════════════════════════
   FIELD
   ══════════════════════════════════════════════════════════ */

export function Field({ label, hint, error, icon: Icon, className, inputClassName, ...props }) {
  return (
    <label className={cx('block group', className)}>
      <span className="mb-2 flex items-center justify-between gap-3 text-xs font-semibold" style={{ color: '#b0aacb' }}>
        <span>{label}</span>
        {hint && <span className="font-normal" style={{ color: '#6b6585' }}>{hint}</span>}
      </span>
      <span className="relative block">
        {Icon && <Icon className="pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 transition-colors group-focus-within:text-purple-400" style={{ color: '#6b6585' }} aria-hidden="true" />}
        <input
          className={cx('velor-input', Icon && 'pr-10', error && 'border-red-500/60 focus:border-red-500/70', inputClassName)}
          {...props}
        />
      </span>
      {error && (
        <motion.span initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} className="mt-2 block text-xs text-red-400" role="alert">
          {error}
        </motion.span>
      )}
    </label>
  );
}

/* ══════════════════════════════════════════════════════════
   TEXTAREA
   ══════════════════════════════════════════════════════════ */

export function TextArea({ label, hint, className, ...props }) {
  return (
    <label className="block group">
      <span className="mb-2 flex items-center justify-between gap-3 text-xs font-semibold" style={{ color: '#b0aacb' }}>
        <span>{label}</span>
        {hint && <span className="font-normal" style={{ color: '#6b6585' }}>{hint}</span>}
      </span>
      <textarea className={cx('velor-input min-h-28 resize-y leading-6', className)} {...props} />
    </label>
  );
}

/* ══════════════════════════════════════════════════════════
   SELECT FIELD
   ══════════════════════════════════════════════════════════ */

export function SelectField({ label, children, className, ...props }) {
  return (
    <label className="block group">
      {label && <span className="mb-2 block text-xs font-semibold" style={{ color: '#b0aacb' }}>{label}</span>}
      <span className="relative block">
        <select className={cx('velor-input appearance-none pr-10', className)} {...props}>
          {children}
        </select>
        <ChevronDown className="pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 transition-colors group-focus-within:text-purple-400" style={{ color: '#6b6585' }} aria-hidden="true" />
      </span>
    </label>
  );
}

/* ══════════════════════════════════════════════════════════
   TOGGLE
   ══════════════════════════════════════════════════════════ */

export function Toggle({ checked, onChange, label, description, disabled = false }) {
  return (
    <label className={cx('flex cursor-pointer items-start justify-between gap-4', disabled && 'cursor-not-allowed opacity-50')}>
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-white">{label}</span>
        {description && <span className="mt-1 block text-xs leading-5" style={{ color: '#6b6585' }}>{description}</span>}
      </span>
      <input
        className="peer sr-only"
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange?.(event.target.checked)}
        disabled={disabled}
      />
      <div
        className="relative mt-0.5 flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-300"
        style={{
          background: checked ? 'linear-gradient(135deg, #8b5cf6, #6366f1)' : 'rgba(255,255,255,0.06)',
          border: `1px solid ${checked ? 'rgba(139,92,246,0.4)' : 'rgba(255,255,255,0.08)'}`,
          boxShadow: checked ? '0 0 16px rgba(139,92,246,0.4)' : 'none',
        }}
      >
        <motion.div
          layout
          transition={{ type: "spring", stiffness: 700, damping: 40 }}
          className="h-5 w-5 rounded-full bg-white shadow-lg"
          style={{
            marginLeft: checked ? '22px' : '2px',
            boxShadow: '0 1px 4px rgba(0,0,0,0.3)',
          }}
        />
      </div>
    </label>
  );
}

/* ══════════════════════════════════════════════════════════
   SEGMENTED CONTROL
   ══════════════════════════════════════════════════════════ */

export function SegmentedControl({ options, value, onChange, label = 'Select view', className }) {
  return (
    <div
      className={cx('inline-flex rounded-xl p-1', className)}
      role="group"
      aria-label={label}
      style={{
        background: 'rgba(0,0,0,0.25)',
        border: '1px solid rgba(130,120,220,0.1)',
      }}
    >
      {options.map((option) => {
        const item = typeof option === 'string' ? { value: option, label: option } : option;
        const active = value === item.value;
        return (
          <button
            key={item.value}
            type="button"
            onClick={() => onChange(item.value)}
            aria-pressed={active}
            className="relative min-h-8 rounded-lg px-3.5 text-xs font-semibold transition-colors duration-200"
            style={{ color: active ? '#ffffff' : '#6b6585' }}
          >
            {active && (
              <motion.div
                layoutId="segmentedControlIndicator"
                className="absolute inset-0 rounded-lg"
                style={{
                  background: 'rgba(255,255,255,0.08)',
                  boxShadow: '0 1px 0 0 rgba(255,255,255,0.04) inset',
                }}
                transition={{ type: "spring", bounce: 0.2, duration: 0.6 }}
              />
            )}
            <span className="relative z-10">{item.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/* ══════════════════════════════════════════════════════════
   PROGRESS BAR
   ══════════════════════════════════════════════════════════ */

const progressColors = {
  purple: 'linear-gradient(90deg, #7c3aed, #8b5cf6, #a78bfa)',
  blue: 'linear-gradient(90deg, #2563eb, #3b82f6, #60a5fa)',
  green: 'linear-gradient(90deg, #059669, #10b981, #34d399)',
  amber: 'linear-gradient(90deg, #d97706, #f59e0b, #fcd34d)',
};

export function ProgressBar({ value, label, detail, tone = 'purple', className }) {
  const safe = Math.max(0, Math.min(100, Number(value) || 0));
  const gradientColor = progressColors[tone] || progressColors.purple;

  return (
    <div className={className}>
      {(label || detail) && (
        <div className="mb-2 flex items-center justify-between gap-3 text-xs">
          <span className="font-medium" style={{ color: '#b0aacb' }}>{label}</span>
          <span className="metric-numbers font-semibold" style={{ color: '#8882a2' }}>{detail ?? `${safe}%`}</span>
        </div>
      )}
      <div className="relative h-2 overflow-hidden rounded-full" style={{ background: 'rgba(255,255,255,0.05)' }}>
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${safe}%` }}
          transition={{ duration: 1, ease: "easeOut" }}
          className="h-full rounded-full"
          style={{
            background: gradientColor,
            boxShadow: safe > 0 ? `0 0 8px ${tone === 'purple' ? 'rgba(139,92,246,0.5)' : tone === 'green' ? 'rgba(52,211,153,0.4)' : tone === 'blue' ? 'rgba(56,189,248,0.4)' : 'rgba(245,158,11,0.4)'}` : 'none',
          }}
        />
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════
   PAGE HEADER
   ══════════════════════════════════════════════════════════ */

export function PanelHeader({ eyebrow, title, description, action, className }) {
  return (
    <div className={cx('flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between', className)}>
      <div className="min-w-0">
        {eyebrow && (
          <p className="mb-1.5 text-[11px] font-bold" style={{ color: 'var(--velor-purple-hi)' }}>
            {eyebrow}
          </p>
        )}
        <h2 className="text-base font-bold tracking-[-0.02em] text-white">{title}</h2>
        {description && <p className="mt-1.5 max-w-2xl text-xs leading-5" style={{ color: '#6b6585' }}>{description}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function PageHeader({ eyebrow, title, description, actions, badge }) {
  return (
    <header className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {eyebrow && (
            <p className="text-[11px] sm:text-xs font-bold" style={{ color: 'var(--velor-purple-hi)' }}>
              {eyebrow}
            </p>
          )}
          {badge}
        </div>
        <h1 className="text-[1.9rem] font-extrabold tracking-tight text-white sm:text-[2.2rem]">{title}</h1>
        {description && (
          <p className="mt-2 max-w-2xl text-sm leading-6" style={{ color: '#6b6585' }}>{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/* ══════════════════════════════════════════════════════════
   METRIC CARD
   ══════════════════════════════════════════════════════════ */

const metricTones = {
  purple: {
    icon: { background: 'linear-gradient(135deg, rgba(139,92,246,0.15), rgba(99,102,241,0.1))', border: '1px solid rgba(139,92,246,0.2)', color: '#c4b5fd' },
    glow: 'rgba(139,92,246,0.08)',
  },
  blue: {
    icon: { background: 'linear-gradient(135deg, rgba(56,189,248,0.15), rgba(59,130,246,0.1))', border: '1px solid rgba(56,189,248,0.2)', color: '#93c5fd' },
    glow: 'rgba(56,189,248,0.06)',
  },
  green: {
    icon: { background: 'linear-gradient(135deg, rgba(52,211,153,0.15), rgba(16,185,129,0.1))', border: '1px solid rgba(52,211,153,0.2)', color: '#6ee7b7' },
    glow: 'rgba(52,211,153,0.06)',
  },
  amber: {
    icon: { background: 'linear-gradient(135deg, rgba(245,158,11,0.15), rgba(251,146,60,0.1))', border: '1px solid rgba(245,158,11,0.2)', color: '#fcd34d' },
    glow: 'rgba(245,158,11,0.06)',
  },
  red: {
    icon: { background: 'rgba(248,113,113,0.10)', border: '1px solid rgba(248,113,113,0.18)', color: '#fca5a5' },
    glow: 'rgba(248,113,113,0.05)',
  },
};

export function MetricCard({ label, value, detail, delta, icon: Icon, tone = 'purple', unavailable = false, children }) {
  const config = metricTones[tone] || metricTones.purple;
  return (
    <Card className="group relative min-h-[138px] overflow-hidden p-4 sm:p-5">
      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-velor-secondary">{label}</p>
          <motion.p
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className={cx(
              'metric-numbers mt-3 text-[1.8rem] font-black leading-none tracking-tight',
              unavailable ? 'text-[#3d3a52]' : 'text-white',
            )}
          >
            {value}
          </motion.p>
        </div>
        {Icon && (
          <span
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl"
            style={config.icon}
          >
            <Icon className="h-4.5 w-4.5" style={{ color: config.icon.color }} aria-hidden="true" />
          </span>
        )}
      </div>

      <div className="mt-3 flex min-h-5 items-center justify-between gap-2">
        <span className="text-[11px] leading-5 text-velor-muted">{detail}</span>
        {delta && (
          <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold" style={{
            borderColor: 'rgba(52,211,153,0.2)',
            background: 'rgba(52,211,153,0.07)',
            color: '#34d399',
          }}>
            <ArrowUpRight className="h-3 w-3" />
            {delta}
          </span>
        )}
      </div>
      {children}
    </Card>
  );
}

/* ══════════════════════════════════════════════════════════
   CHECK ITEM
   ══════════════════════════════════════════════════════════ */

export function CheckItem({ children, complete = true }) {
  return (
    <li className="flex items-start gap-2.5 text-xs leading-5" style={{ color: '#b0aacb' }}>
      <span
        className={cx('mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border transition-all duration-200')}
        style={complete ? {
          borderColor: 'rgba(52,211,153,0.3)',
          background: 'rgba(52,211,153,0.1)',
          color: '#34d399',
        } : {
          borderColor: 'rgba(255,255,255,0.08)',
          color: 'transparent',
        }}
      >
        <Check className="h-2.5 w-2.5" aria-hidden="true" />
      </span>
      {children}
    </li>
  );
}

/* ══════════════════════════════════════════════════════════
   DATA STATE NOTICE
   ══════════════════════════════════════════════════════════ */

export function DataStateNotice({ title, description, action, tone = 'purple' }) {
  const styles = {
    purple: {
      border: 'rgba(139,92,246,0.15)',
      bg: 'linear-gradient(135deg, rgba(139,92,246,0.05), rgba(99,102,241,0.03))',
      iconBg: 'rgba(139,92,246,0.12)',
      iconColor: '#a78bfa',
    },
    blue: {
      border: 'rgba(56,189,248,0.15)',
      bg: 'linear-gradient(135deg, rgba(56,189,248,0.05), rgba(59,130,246,0.03))',
      iconBg: 'rgba(56,189,248,0.12)',
      iconColor: '#60a5fa',
    },
    warning: {
      border: 'rgba(245,158,11,0.18)',
      bg: 'rgba(245,158,11,0.055)',
      iconBg: 'rgba(245,158,11,0.12)',
      iconColor: '#fbbf24',
    },
  };
  const s = styles[tone] || styles.purple;

  return (
    <motion.div
      initial={{ opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border p-4"
      style={{ borderColor: s.border, background: s.bg }}
    >
      <p className="text-xs font-bold text-white">{title}</p>
      <p className="mt-1.5 text-[11px] leading-5" style={{ color: '#6b6585' }}>{description}</p>
      {action && <div className="mt-3">{action}</div>}
    </motion.div>
  );
}
