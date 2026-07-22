const normalizeText = (value) => String(value ?? '').trim();

export const createProduct = (seed = {}) => ({
    ...seed,
    id: seed.id || `product-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    name: normalizeText(seed.name || seed.product || seed.service),
    category: normalizeText(seed.category),
    price: seed.price === null || seed.price === undefined ? '' : String(seed.price),
    currency: normalizeText(seed.currency || seed.curr || 'EGP').toUpperCase(),
    description: normalizeText(seed.description),
    active: seed.active !== false,
});

export const normalizeProductsData = (productsData) => {
    if (!productsData) return [];
    try {
        const parsed = typeof productsData === 'string' ? JSON.parse(productsData) : productsData;
        if (!Array.isArray(parsed) || !parsed.length) return [];
        const products = parsed.filter((item) => typeof item === 'string' || (item && typeof item === 'object'))
            .map((item) => createProduct(typeof item === 'string' ? { name: item } : item));
        return products;
    } catch {
        return [];
    }
};

export const validateProducts = (products = []) => {
    const errorsById = {};
    const nameCounts = new Map();
    products.forEach((product) => {
        const name = normalizeText(product.name).toLocaleLowerCase('en');
        if (name) nameCounts.set(name, (nameCounts.get(name) || 0) + 1);
    });

    products.forEach((product) => {
        const errors = [];
        const name = normalizeText(product.name);
        const category = normalizeText(product.category);
        const priceText = normalizeText(product.price);
        const price = Number(priceText);
        const currency = normalizeText(product.currency);
        if (!name) errors.push('اسم المنتج مطلوب.');
        if (name && nameCounts.get(name.toLocaleLowerCase('en')) > 1) errors.push('اسم مكرر في الكتالوج.');
        if (product.active && !category) errors.push('الفئة مطلوبة للمنتج النشط.');
        if (product.active && !priceText) errors.push('السعر مطلوب للمنتج النشط.');
        if (priceText && (!Number.isFinite(price) || price < 0)) errors.push('السعر يجب أن يكون رقمًا غير سالب.');
        if (priceText && !currency) errors.push('العملة مطلوبة عند إدخال السعر.');
        errorsById[product.id] = errors;
    });

    const duplicateIds = products
        .filter((product) => {
            const name = normalizeText(product.name).toLocaleLowerCase('en');
            return name && nameCounts.get(name) > 1;
        })
        .map((product) => product.id);
    const activeValidCount = products.filter((product) => product.active && !(errorsById[product.id] || []).length).length;
    return {
        isValid: Object.values(errorsById).every((errors) => errors.length === 0),
        errorsById,
        duplicateIds,
        activeValidCount,
    };
};

// Preserve trusted fields that the compact editor does not expose (for example
// SKU, aliases, or import provenance) while normalizing the editable contract.
// This prevents a harmless name/price edit from silently destroying catalog data.
export const serializeProducts = (products = []) => JSON.stringify(products.map((product) => ({
    ...product,
    id: product.id,
    name: normalizeText(product.name),
    category: normalizeText(product.category),
    price: normalizeText(product.price) ? Number(product.price) : null,
    currency: normalizeText(product.currency).toUpperCase() || null,
    description: normalizeText(product.description) || null,
    active: product.active !== false,
})), null, 0);

export const settingsFingerprint = ({ companyName, industry, selectedTone, welcomeMessage, products }) => JSON.stringify({
    companyName: normalizeText(companyName),
    industry: normalizeText(industry),
    selectedTone: normalizeText(selectedTone),
    welcomeMessage: normalizeText(welcomeMessage),
    products: JSON.parse(serializeProducts(products || [])),
});

export const sourceStatus = (source = {}) => {
    if (source.status === 'error' || source.error_category) return { label: 'خطأ في المعالجة', tone: 'error' };
    if (!source.active || source.status === 'disabled') return { label: 'متوقف', tone: 'disabled' };
    if (source.status === 'processed') return { label: 'نشط وقابل للاسترجاع', tone: 'ready' };
    return { label: 'قيد المعالجة', tone: 'processing' };
};

export const buildReadinessChecks = ({
    companyName,
    industry,
    selectedTone,
    hasUnsavedSettings,
    engineStatus = {},
    catalogStatus = {},
    sources = [],
    sourceLoadError,
    isWebChatEnabled,
    publicChatSlug,
    channelStatusError,
}) => {
    const engineVersion = String(engineStatus.engine_version || engineStatus.selected_public_engine || '').toLowerCase();
    const providerAvailable = Boolean(engineStatus.provider_available);
    const fallbackActive = Boolean(engineStatus.fallback_active);
    const activeSources = sources.filter((source) => source.active && source.status === 'processed').length;
    const sourceErrors = sources.filter((source) => source.status === 'error' || source.error_category).length;
    const activeCatalog = Number(catalogStatus.active_records || 0);
    const pricedCatalog = Number(catalogStatus.priced_records || 0);

    return [
        {
            key: 'identity',
            label: 'هوية النشاط محفوظة',
            status: companyName && industry && selectedTone && !hasUnsavedSettings ? 'ready' : 'attention',
            detail: hasUnsavedSettings ? 'توجد تغييرات لم تُحفظ بعد.' : (companyName && industry && selectedTone ? 'الهوية والنبرة متاحتان.' : 'أكمل الاسم والمجال والنبرة.'),
        },
        {
            key: 'engine',
            label: 'محرك المحادثة',
            status: engineVersion === 'v2' ? 'ready' : 'blocked',
            detail: engineVersion === 'v2' ? 'VELOR V2 هو مسار المحادثة العامة.' : 'المحرك الحالي ليس V2.',
        },
        {
            key: 'provider',
            label: 'المزود أو الوضع البديل',
            status: providerAvailable || fallbackActive ? 'ready' : 'blocked',
            detail: providerAvailable
                ? `${engineStatus.provider_name || engineStatus.provider || 'المزود'} متاح.`
                : fallbackActive
                    ? 'المزود غير متاح؛ وضع الرد الآمن البديل معلن ومفعّل.'
                    : 'لا يوجد مزود متاح ولا وضع بديل معلن.',
        },
        {
            key: 'catalog',
            label: 'كتالوج صالح',
            status: !hasUnsavedSettings && activeCatalog > 0 && pricedCatalog > 0 ? 'ready' : 'blocked',
            detail: hasUnsavedSettings
                ? 'احفظ تعديلات الكتالوج لتحديث التشخيص.'
                : `${activeCatalog} منتج نشط، ${pricedCatalog} بسعر موثق.`,
        },
        {
            key: 'knowledge',
            label: 'مصادر السياسات والمعرفة',
            status: sourceLoadError || sourceErrors ? 'blocked' : activeSources ? 'ready' : 'attention',
            detail: sourceLoadError ? 'تعذر التحقق من حالة المصادر.' : sourceErrors ? `${sourceErrors} مصدر به خطأ.` : activeSources ? `${activeSources} مصدر نشط.` : 'لم تتم إضافة مصدر معرفة نشط بعد.',
        },
        {
            key: 'channel',
            label: 'قناة المحادثة العامة',
            status: channelStatusError ? 'blocked' : isWebChatEnabled && publicChatSlug ? 'ready' : 'blocked',
            detail: channelStatusError ? 'تعذر التحقق من حالة القناة.' : isWebChatEnabled && publicChatSlug ? 'الرابط العام مفعّل.' : 'فعّل Web Chat لإنشاء رابط المعاينة.',
        },
    ];
};

export const allowedKnowledgeFile = (file, maxBytes = 5 * 1024 * 1024) => {
    if (!file) return { valid: false, message: 'اختر ملفًا أولًا.' };
    const extension = `.${String(file.name || '').split('.').pop().toLowerCase()}`;
    if (!['.pdf', '.docx', '.csv', '.txt'].includes(extension)) return { valid: false, message: 'الصيغ المدعومة: PDF وDOCX وCSV وTXT.' };
    if (!file.size) return { valid: false, message: 'الملف فارغ.' };
    if (file.size > maxBytes) return { valid: false, message: 'حجم الملف يتجاوز 5MB.' };
    return { valid: true, message: '' };
};

export const allowedCatalogFile = (file, maxBytes = 5 * 1024 * 1024) => {
    if (!file) return { valid: false, message: 'اختر ملف كتالوج أولًا.' };
    const name = String(file.name || '');
    const extension = `.${name.split('.').pop().toLowerCase()}`;
    if (!['.csv', '.xlsx'].includes(extension)) return { valid: false, message: 'صيغة الكتالوج المدعومة: CSV أو XLSX.' };
    if (!file.size) return { valid: false, message: 'ملف الكتالوج فارغ.' };
    if (file.size > maxBytes) return { valid: false, message: 'حجم ملف الكتالوج يتجاوز 5MB.' };
    return { valid: true, message: '' };
};
