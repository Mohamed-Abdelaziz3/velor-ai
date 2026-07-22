import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
    allowedKnowledgeFile,
    allowedCatalogFile,
    buildReadinessChecks,
    normalizeProductsData,
    serializeProducts,
    settingsFingerprint,
    sourceStatus,
    validateProducts,
} from '../src/pages/dashboard/settings/settingsUi.js';

test('catalog hydration preserves the supported structured fields', () => {
    const products = normalizeProductsData(JSON.stringify([{
        id: 'ergo-one',
        name: 'Arvena Ergo One',
        category: 'كراسي مكتب',
        price: 6900,
        currency: 'egp',
        description: 'ظهر شبكي',
        active: false,
    }]));
    assert.deepEqual(products[0], {
        id: 'ergo-one',
        name: 'Arvena Ergo One',
        category: 'كراسي مكتب',
        price: '6900',
        currency: 'EGP',
        description: 'ظهر شبكي',
        active: false,
    });
});

test('catalog validation exposes missing facts and duplicates without silently dropping rows', () => {
    const products = normalizeProductsData([
        { id: 'one', name: 'Ergo One', category: '', price: '6900', currency: 'EGP', active: true },
        { id: 'two', name: 'ergo one', category: 'chairs', price: '-2', currency: 'EGP', active: true },
    ]);
    const result = validateProducts(products);
    assert.equal(result.isValid, false);
    assert.equal(result.duplicateIds.length, 2);
    assert.ok(result.errorsById.one.includes('الفئة مطلوبة للمنتج النشط.'));
    assert.ok(result.errorsById.two.includes('السعر يجب أن يكون رقمًا غير سالب.'));
    assert.equal(JSON.parse(serializeProducts(products)).length, 2);
});

test('readiness is derived from actual diagnostics and declares fallback honestly', () => {
    const checks = buildReadinessChecks({
        companyName: 'ARVENA',
        industry: 'Office furniture',
        selectedTone: 'friendly',
        hasUnsavedSettings: false,
        engineStatus: { selected_public_engine: 'v2', provider_available: false, fallback_active: true },
        catalogStatus: { active_records: 4, priced_records: 4 },
        sources: [{ id: 1, active: true, status: 'processed' }],
        isWebChatEnabled: true,
        publicChatSlug: 'arvena-demo',
    });
    assert.equal(checks.every((check) => check.status === 'ready'), true);
    assert.match(checks.find((check) => check.key === 'provider').detail, /وضع الرد الآمن البديل/);

    const unknown = buildReadinessChecks({ engineStatus: {}, catalogStatus: {}, sources: [], sourceLoadError: true, channelStatusError: true });
    assert.equal(unknown.find((check) => check.key === 'engine').status, 'blocked');
    assert.equal(unknown.find((check) => check.key === 'knowledge').status, 'blocked');
    assert.equal(unknown.find((check) => check.key === 'channel').status, 'blocked');
});

test('knowledge uploads enforce one supported non-empty file within the UI limit', () => {
    assert.deepEqual(allowedKnowledgeFile({ name: 'policy.pdf', size: 1024 }), { valid: true, message: '' });
    assert.equal(allowedKnowledgeFile({ name: 'macro.exe', size: 1024 }).valid, false);
    assert.equal(allowedKnowledgeFile({ name: 'empty.txt', size: 0 }).valid, false);
    assert.equal(allowedKnowledgeFile({ name: 'large.csv', size: 6 * 1024 * 1024 }).valid, false);
});

test('catalog import accepts only non-empty bounded CSV or XLSX files', () => {
    assert.deepEqual(allowedCatalogFile({ name: 'catalog.csv', size: 1024 }), { valid: true, message: '' });
    assert.equal(allowedCatalogFile({ name: 'catalog.xlsx', size: 2048 }).valid, true);
    assert.equal(allowedCatalogFile({ name: 'catalog.json', size: 1024 }).valid, false);
    assert.equal(allowedCatalogFile({ name: 'empty.csv', size: 0 }).valid, false);
    assert.equal(allowedCatalogFile({ name: 'large.xlsx', size: 6 * 1024 * 1024 }).valid, false);
});

test('knowledge source labels reflect retrievability rather than upload existence', () => {
    assert.deepEqual(sourceStatus({ active: true, status: 'processed' }), { label: 'نشط وقابل للاسترجاع', tone: 'ready' });
    assert.equal(sourceStatus({ active: false, status: 'disabled' }).tone, 'disabled');
    assert.equal(sourceStatus({ active: true, status: 'error', error_category: 'parse' }).tone, 'error');
});

test('settings fingerprint changes only with merchant-editable settings data', () => {
    const base = {
        companyName: 'ARVENA',
        industry: 'Furniture',
        selectedTone: 'friendly',
        welcomeMessage: 'أهلًا',
        products: normalizeProductsData([{ id: 'one', name: 'Ergo One', category: 'chairs', price: 6900, currency: 'EGP' }]),
    };
    assert.equal(settingsFingerprint(base), settingsFingerprint({ ...base }));
    assert.notEqual(settingsFingerprint(base), settingsFingerprint({ ...base, industry: 'Desks' }));
});

test('settings render failed alert and Web Chat reads as unknown and block mutations', () => {
    const source = readFileSync(new URL('../src/pages/velor/Settings.jsx', import.meta.url), 'utf8');
    assert.match(source, /alertsKnown/);
    assert.match(source, /webChatKnown/);
    assert.match(source, /!webChatKnown \? 'غير معروف'/);
    assert.match(source, /disabled=\{!webChatKnown\}/);
    assert.match(source, /disabled=\{!alertsKnown\}/);
    assert.match(source, /تعذر التحقق من إعدادات التنبيهات/);
    assert.match(source, /تعذر التحقق من حالة دردشة الموقع المستضافة/);
});
