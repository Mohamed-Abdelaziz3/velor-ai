# Contributing to VELOR

شكرًا لمساهمتك. الهدف هو منتج مبيعات عربي موثوق للتجار المصريين؛ أي تغيير يجب أن يحافظ على عزل الشركات، صدق البيانات المعروضة، وسهولة الاستخدام على الهاتف.

## قبل البدء

1. اقرأ [README.md](README.md) و[SECURITY.md](SECURITY.md).
2. افتح Issue غير أمنية تصف المشكلة أو القرار المقترح قبل التغييرات الكبيرة.
3. أنشئ فرعًا صغير النطاق من أحدث نسخة للفرع الأساسي.
4. لا تضع بيانات عملاء، قواعد بيانات، screenshots حساسة، API keys، أو ملفات `.env` في commit.

## إعداد بيئة التطوير

اتبع [دليل الإعداد القابل للتكرار](docs/setup/LOCAL_SETUP.md). ثبّت Python من `backend/requirements-dev.lock` واستخدم `npm ci` مع ملفات القفل الملتزم بها. استخدم SQLite للاختبارات والتطوير فقط، وطبّق migrations عبر Alembic بدل تعديل الجداول يدويًا.

## بوابات الجودة المطلوبة

```powershell
python tools\check_repository_hygiene.py --inventory-local

Set-Location backend
python -m pytest -q

Set-Location ..\frontend
npm test
npm run lint
npm run build

Set-Location ..\backend
node --check whatsapp_gate.js
```

إذا غيّرت نموذج بيانات، أضف migration واختبار ترحيل. إذا غيّرت عقد API أو سلوك Web Chat، أضف regression test يغطي عزل `company_id` والحالات الفاشلة. إذا غيّرت الواجهة، اختبر RTL، الهاتف، لوحة المفاتيح، والحالات loading/empty/error.

## معايير التغيير

- لا تعرض رقمًا أو نسبة أو حالة `live` دون مصدر ووقت تحديث واضحين.
- ميّز صراحة بين البيانات المقاسة، التقديرات، والبيانات غير المتاحة.
- لا تضف claims تسويقية مطلقة أو testimonials غير موثقة.
- حافظ على fallback آمن؛ لا تخفِ فشل مزود AI كنجاح كامل.
- لا تسجّل tokens أو prompts حساسة أو محتوى العملاء في logs غير ضرورية.
- استخدم UTF-8 وتحقق من العربية وRTL دون mojibake.

## Pull Requests

- اجعل العنوان واضحًا، ويفضل نمطًا مثل `feat:`, `fix:`, `docs:`, `test:`, أو `security:`.
- اشرح المشكلة، الحل، المخاطر، وطريقة التحقق.
- أرفق screenshots فقط لتغيير مرئي، بعد إزالة أي بيانات حساسة.
- اربط Issue المناسبة، واذكر migrations أو متغيرات البيئة الجديدة.
- لا تطلب الدمج قبل نجاح GitHub Actions ومراجعة أي ملاحظات أمنية.

## English summary

Keep contributions small, tested, tenant-safe, and evidence-based. Run backend tests plus frontend tests, lint, and build before opening a PR. Never commit secrets or customer data. Schema changes require Alembic migrations; API and Web Chat changes require regression coverage; UI changes must be checked in Arabic RTL and on mobile.
