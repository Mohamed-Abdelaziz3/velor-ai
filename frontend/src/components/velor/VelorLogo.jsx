import { useId } from 'react';

const MARK_PATH = 'M4.5 8.5h15.8c3.9 0 7.5 2.09 9.45 5.48L36 24.82l6.25-10.84A10.91 10.91 0 0 1 51.7 8.5h7.8L40.8 47.52A10 10 0 0 1 32 53a10 10 0 0 1-8.8-5.48L4.5 8.5Z';

/**
 * Standalone VELOR mark.
 *
 * Use `variant="monochrome"` to inherit the surrounding `color` value.
 * Set `decorative` when adjacent text already supplies the accessible name.
 */
export function VelorMark({
    size = 32,
    variant = 'gradient',
    title = 'VELOR mark',
    decorative = false,
    className = '',
    ...svgProps
}) {
    const reactId = useId();
    const instanceId = `velor-${reactId.replace(/[^a-zA-Z0-9_-]/g, '')}`;
    const gradientId = `${instanceId}-gradient`;
    const titleId = `${instanceId}-title`;
    const monochrome = variant === 'monochrome';

    return (
        <svg
            {...svgProps}
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 64 64"
            width={size}
            height={size}
            className={className}
            role={decorative ? undefined : 'img'}
            aria-hidden={decorative ? true : undefined}
            aria-labelledby={decorative ? undefined : titleId}
            focusable="false"
        >
            {!decorative && <title id={titleId}>{title}</title>}
            {!monochrome && (
                <defs>
                    <linearGradient
                        id={gradientId}
                        x1="8"
                        y1="7"
                        x2="56"
                        y2="55"
                        gradientUnits="userSpaceOnUse"
                    >
                        <stop stopColor="#D44BFF" />
                        <stop offset="0.5" stopColor="#8B3DFF" />
                        <stop offset="1" stopColor="#3978FF" />
                    </linearGradient>
                </defs>
            )}
            <path
                d={MARK_PATH}
                fill={monochrome ? 'currentColor' : `url(#${gradientId})`}
                fillRule="evenodd"
                clipRule="evenodd"
            />
        </svg>
    );
}

/** Horizontal VELOR brand lockup with an accessible combined name. */
export function VelorLogo({
    size = 32,
    variant = 'gradient',
    wordmark = 'VELOR',
    label = wordmark,
    className = '',
    markClassName = '',
    wordmarkClassName = '',
    ...lockupProps
}) {
    return (
        <span
            {...lockupProps}
            role="img"
            aria-label={label}
            className={`inline-flex items-center gap-2.5 ${className}`.trim()}
        >
            <VelorMark
                size={size}
                variant={variant}
                decorative
                className={`shrink-0 ${markClassName}`.trim()}
            />
            <span
                aria-hidden="true"
                className={`text-xl font-semibold leading-none tracking-[0.16em] text-current ${wordmarkClassName}`.trim()}
            >
                {wordmark}
            </span>
        </span>
    );
}

export default VelorLogo;
