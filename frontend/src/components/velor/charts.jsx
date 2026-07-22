import { useId } from 'react';
import { cx } from './ui';

function normalisePoints(values, width, height, padding = 14) {
  const safe = values.length > 1 ? values : [0, 0];
  const min = Math.min(...safe);
  const max = Math.max(...safe);
  const range = Math.max(max - min, 1);
  return safe.map((value, index) => ({
    value,
    x: padding + (index / (safe.length - 1)) * (width - padding * 2),
    y: height - padding - ((value - min) / range) * (height - padding * 2),
  }));
}

export function TrendChart({ values, labels = [], height = 220, summary, className, color = '#9B5CFF' }) {
  const width = 760;
  const points = normalisePoints(values, width, height, 18);
  const line = points.map((point, index) => `${index ? 'L' : 'M'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ');
  const area = `${line} L ${points.at(-1).x.toFixed(1)} ${height - 16} L ${points[0].x.toFixed(1)} ${height - 16} Z`;
  const gradientId = `trend-${useId().replace(/:/g, '')}`;

  return (
    <div className={cx('w-full', className)}>
      <svg className="h-auto w-full overflow-visible" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={summary || 'Trend chart'}>
        <title>{summary || 'Trend over time'}</title>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={color} stopOpacity="0.26" />
            <stop offset="1" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.22, 0.48, 0.74].map((ratio) => (
          <line key={ratio} x1="16" x2={width - 16} y1={height * ratio} y2={height * ratio} stroke="rgba(255,255,255,.06)" strokeDasharray="4 8" />
        ))}
        <path d={area} fill={`url(#${gradientId})`} />
        <path d={line} fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        {points.map((point, index) => (
          <circle key={`${point.x}-${point.value}`} cx={point.x} cy={point.y} r="5" fill="#0B0C14" stroke={color} strokeWidth="2" tabIndex="0">
            <title>{`${labels[index] || `Point ${index + 1}`}: ${point.value}`}</title>
          </circle>
        ))}
      </svg>
      {labels.length > 0 && (
        <div className="mt-1 flex justify-between px-1 text-[10px] text-velor-muted">
          {labels.map((label) => <span key={label}>{label}</span>)}
        </div>
      )}
    </div>
  );
}

export function MiniSparkline({ values, tone = 'purple', className }) {
  const colors = { purple: '#9B5CFF', blue: '#38BDF8', green: '#31D6A0', amber: '#F5B546' };
  const width = 120;
  const height = 28;
  const points = normalisePoints(values, width, height, 2);
  const line = points.map((point, index) => `${index ? 'L' : 'M'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ');
  return (
    <svg className={cx('h-7 w-[120px]', className)} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <path d={line} fill="none" stroke={colors[tone]} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Heatmap({ values, rows = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'], columns = ['9', '11', '1', '3', '5', '7'], summary }) {
  const max = Math.max(...values.flat(), 1);
  return (
    <div>
      <div className="grid items-center gap-1.5" style={{ gridTemplateColumns: `2rem repeat(${columns.length}, minmax(18px, 1fr))` }} role="img" aria-label={summary || 'Conversation activity heatmap'}>
        <span />
        {columns.map((column) => <span key={column} className="text-center text-[9px] text-velor-muted">{column}</span>)}
        {rows.map((row, rowIndex) => (
          <div key={row} className="contents">
            <span className="text-[9px] text-velor-muted">{row}</span>
            {columns.map((column, columnIndex) => {
              const value = values[rowIndex]?.[columnIndex] || 0;
              const opacity = 0.08 + (value / max) * 0.84;
              return (
                <span
                  key={`${row}-${column}`}
                  className="aspect-square min-h-5 rounded-md border border-white/[0.04] transition-transform hover:scale-110 focus:scale-110"
                  style={{ backgroundColor: `rgba(155, 92, 255, ${opacity})` }}
                  tabIndex="0"
                  aria-label={`${row} at ${column}: ${value} conversations`}
                />
              );
            })}
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-end gap-1 text-[9px] text-velor-muted">
        <span>أقل</span>
        {[0.12, 0.28, 0.46, 0.68, 0.9].map((opacity) => <span key={opacity} className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: `rgba(155, 92, 255, ${opacity})` }} />)}
        <span>أكثر</span>
      </div>
    </div>
  );
}

export function RingGauge({ value, label, tone = 'purple', size = 112 }) {
  const radius = 43;
  const circumference = 2 * Math.PI * radius;
  const safe = Math.max(0, Math.min(100, Number(value) || 0));
  const colors = { purple: '#9B5CFF', blue: '#38BDF8', green: '#31D6A0', amber: '#F5B546' };
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg className="-rotate-90" width={size} height={size} viewBox="0 0 100 100" aria-hidden="true">
        <circle cx="50" cy="50" r={radius} fill="none" stroke="rgba(255,255,255,.065)" strokeWidth="7" />
        <circle cx="50" cy="50" r={radius} fill="none" stroke={colors[tone]} strokeWidth="7" strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={circumference * (1 - safe / 100)} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
        <span className="metric-numbers text-xl font-semibold text-white">{safe}%</span>
        <span className="text-[9px] text-velor-muted">{label}</span>
      </div>
    </div>
  );
}
