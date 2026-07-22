const TIMEZONE_SUFFIX = /(?:z|[+-]\d{2}:?\d{2})$/i;

export function normalizeApiTimestamp(value) {
    if (value instanceof Date) return Number.isNaN(value.getTime()) ? '' : value.toISOString();
    if (typeof value !== 'string') return '';

    const trimmed = value.trim();
    if (!trimmed) return '';

    let normalized = trimmed.replace(' ', 'T');
    // SQLite stores UTC timestamps without an offset in the current API. Treat
    // those values as UTC instead of letting the browser reinterpret them as local.
    if (!TIMEZONE_SUFFIX.test(normalized)) normalized = `${normalized}Z`;
    // JavaScript dates retain milliseconds; trim database microseconds safely.
    normalized = normalized.replace(/(\.\d{3})\d+/, '$1');
    return normalized;
}

export function parseApiTimestamp(value) {
    if (value instanceof Date) {
        return Number.isNaN(value.getTime()) ? null : new Date(value.getTime());
    }

    const normalized = normalizeApiTimestamp(value);
    if (!normalized) return null;
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
}

function resolveNow(now) {
    if (now instanceof Date) return now.getTime();
    const value = typeof now === 'number' ? now : new Date(now).getTime();
    return Number.isFinite(value) ? value : Date.now();
}

export function formatRelativeTime(value, { now = Date.now(), locale = 'en' } = {}) {
    const date = parseApiTimestamp(value);
    if (!date) return '—';

    const diffMs = date.getTime() - resolveNow(now);
    const absoluteMs = Math.abs(diffMs);
    const formatter = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });

    if (absoluteMs < 45_000) return formatter.format(0, 'second');

    const units = [
        { limit: 60 * 60_000, size: 60_000, unit: 'minute' },
        { limit: 24 * 60 * 60_000, size: 60 * 60_000, unit: 'hour' },
        { limit: 30 * 24 * 60 * 60_000, size: 24 * 60 * 60_000, unit: 'day' },
        { limit: 365 * 24 * 60 * 60_000, size: 30 * 24 * 60 * 60_000, unit: 'month' },
        { limit: Number.POSITIVE_INFINITY, size: 365 * 24 * 60 * 60_000, unit: 'year' },
    ];
    const selected = units.find(({ limit }) => absoluteMs < limit) || units[units.length - 1];
    const amount = Math.round(diffMs / selected.size);
    return formatter.format(amount || (diffMs < 0 ? -1 : 1), selected.unit);
}

export function formatClockTime(value, locale = 'en') {
    const date = parseApiTimestamp(value);
    if (!date) return '';
    return new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(date);
}

function localDayNumber(date) {
    return Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86_400_000;
}

export function getLocalDateKey(value) {
    const date = parseApiTimestamp(value);
    if (!date) return 'unknown';
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

export function formatDateSeparator(value, { now = Date.now(), locale = 'en' } = {}) {
    const date = parseApiTimestamp(value);
    if (!date) return 'Date unavailable';

    const nowDate = new Date(resolveNow(now));
    const dayDifference = localDayNumber(date) - localDayNumber(nowDate);
    if (dayDifference === 0) return 'Today';
    if (dayDifference === -1) return 'Yesterday';

    return new Intl.DateTimeFormat(locale, {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        year: date.getFullYear() === nowDate.getFullYear() ? undefined : 'numeric',
    }).format(date);
}

export function groupMessagesByDate(messages = []) {
    const groups = [];
    const byKey = new Map();

    messages.forEach((message) => {
        const timestamp = message.timestamp || message.created_at || message.date;
        const key = getLocalDateKey(timestamp);
        let group = byKey.get(key);
        if (!group) {
            group = { key, timestamp: parseApiTimestamp(timestamp)?.toISOString() || null, items: [] };
            byKey.set(key, group);
            groups.push(group);
        }
        group.items.push(message);
    });

    return groups;
}

export const formatArabicDateTime = (dateString, now = Date.now()) => {
    const date = parseApiTimestamp(dateString);
    if (!date) return { relative: '', absolute: '' };

    const relative = formatRelativeTime(dateString, { now, locale: 'ar-EG' });
    const absolute = `${date.toLocaleDateString('ar-EG', {
        month: 'long',
        day: 'numeric',
    })} - ${date.toLocaleTimeString('ar-EG', {
        hour: '2-digit',
        minute: '2-digit',
    })}`;

    return { relative, absolute };
};
