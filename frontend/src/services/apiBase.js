const stripTrailingSlashes = (value) => value.replace(/\/+$/, '');

export const resolveRuntimeApiBase = (configuredBase, locationLike) => {
    const configured = String(configuredBase || '').trim();
    if (configured) return stripTrailingSlashes(configured);

    const location = locationLike || {};
    const origin = String(location.origin || '').trim();
    if (origin && origin !== 'null') return stripTrailingSlashes(origin);

    const protocol = String(location.protocol || '').trim();
    const host = String(location.host || '').trim();
    return protocol && host ? `${protocol}//${host}` : '';
};
