import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../src/pages/LandingPage.jsx', import.meta.url), 'utf8');

test('landing page explains the validated V2 core loop without unsupported outcomes', () => {
  assert.match(source, /اعرف المحادثات التي تحتاج انتباهك/);
  assert.match(source, /يقترح ردودًا مبنية على الكتالوج والسياسات والمحادثة/);
  assert.match(source, /ويصعّد عدم اليقين بدل ما يخمّن/);
  assert.match(source, /الكتالوج والسياسات والمحادثة هي مصدر الإجابة/);
  assert.match(source, /لو وصلت رسالة أحدث، لا تُستخدم مسودة قديمة خارج سياقها/);
  assert.doesNotMatch(source, /مليون|ضاعف مبيعاتك|عملاءنا يثقون بنا/);
  assert.doesNotMatch(source, /نتائج عملائنا|دقة 100%|جاهز للإنتاج/);
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
