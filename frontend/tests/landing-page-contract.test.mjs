import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../src/pages/LandingPage.jsx', import.meta.url), 'utf8');

test('landing page positions VELOR as truthful revenue recovery for customer conversations', () => {
  assert.match(source, /المحادثات اللي بتضيع منك،/);
  assert.match(source, /Revenue recovery for customer conversations/);
  assert.match(source, /Web Chat وWhatsApp workflows/);
  assert.match(source, /الإيراد غير المعروف يظهر غير معروف/);
  assert.match(source, /أي رسالة عميل أحدث تجعل الاقتراح القديم غير صالح/);
  assert.doesNotMatch(source, /مليون|ضاعف مبيعاتك|عملاءنا يثقون بنا/);
});

test('landing page exposes accessible public navigation and real product routes', () => {
  assert.match(source, /aria-label="التنقل الرئيسي"/);
  assert.match(source, /to="\/signup"/);
  assert.match(source, /to="\/login"/);
  assert.match(source, /to="\/terms"/);
  assert.match(source, /to="\/privacy"/);
  assert.match(source, /aria-expanded=\{menuOpen\}/);
  assert.match(source, /dir="rtl"/);
});
