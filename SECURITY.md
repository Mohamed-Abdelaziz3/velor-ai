# Security Policy

## الإصدارات المدعومة | Supported versions

المشروع في مرحلة Pilot ولا يملك سلسلة إصدارات عامة مستقرة بعد. تُطبّق إصلاحات الأمان على أحدث نسخة من الفرع الأساسي فقط.

VELOR is currently a pilot-stage product without a stable public release line. Security fixes are applied only to the latest revision of the default branch.

| Version | Security support |
|---|---|
| Default branch (`main`) | Yes |
| Old commits, forks, and local snapshots | No |

## الإبلاغ عن ثغرة | Reporting a vulnerability

لا تنشر ثغرة أمنية أو بيانات عميل أو سرًا في Issue عامة. استخدم **GitHub Private Vulnerability Reporting** من تبويب Security إن كان مفعّلًا. إن لم يكن متاحًا، تواصل بصورة خاصة مع مالك المستودع واطلب قناة مشفّرة قبل إرسال التفاصيل.

Do not open a public issue containing a vulnerability, customer data, credentials, or exploit details. Use **GitHub Private Vulnerability Reporting** from the Security tab when available. Otherwise, contact the repository owner privately and request an encrypted channel before sharing details.

ضمّن في البلاغ:

- وصف الأثر والمكوّن المتأثر.
- خطوات إعادة إنتاج محدودة وآمنة أو proof of concept غير مدمر.
- الإصدار أو commit الذي اختبرته.
- أي متطلبات خاصة بعزل الشركات، المصادقة، Web Chat، webhook، أو بوابة WhatsApp.
- اقتراح إصلاح إن وُجد، دون نسخ بيانات حقيقية.

سيتم التعامل مع البلاغ بأفضل جهد ممكن: تأكيد الاستلام، التحقق، تحديد شدة الأثر، ثم تنسيق الإصلاح والإفصاح. لا يوجد SLA تعاقدي معلن في مرحلة Pilot.

## قواعد الاختبار المسؤول | Safe-harbor boundaries

- اختبر فقط نسخة محلية أو بيئة تملك تصريحًا صريحًا لاختبارها.
- لا تصل إلى بيانات شركة أخرى، ولا تستخرج بيانات أو تعطل الخدمة.
- لا تستخدم الهندسة الاجتماعية أو هجمات حجب الخدمة أو الرسائل غير المرغوبة.
- توقف فورًا إذا ظهرت بيانات حقيقية، واحفظ أقل قدر لازم لإثبات المشكلة.
- لا ترسل الأسرار بالبريد أو في screenshots أو logs؛ استخدم قناة مشفرة.

## التعامل مع الأسرار | Secret handling

- ملفات `.env` وقواعد SQLite والجلسات وملفات السجل ليست جزءًا من المستودع.
- أسرار backend لا توضع في متغيرات `VITE_*` لأنها تصبح متاحة للمتصفح.
- إذا ظهر سر في commit أو log، دوّره فورًا لدى المزوّد ثم نظّف الأثر؛ حذف النص وحده لا يبطل السر.
- استخدم مدير أسرار، قيمًا مختلفة لكل بيئة، وأقل صلاحيات ممكنة في الإنتاج.

For deployment hardening, require HTTPS, managed PostgreSQL, explicit origin allowlists, protected admin access, backup/restore testing, monitoring, and a clean `/ready` result appropriate to the enabled integrations.

The repository-specific inventory, backup-first relocation procedure, and
OneDrive caveat are documented in
[`docs/security/LOCAL_ARTIFACT_HANDLING.md`](docs/security/LOCAL_ARTIFACT_HANDLING.md).
Run `python tools/check_repository_hygiene.py --inventory-local` before creating
any public commit; the scanner suppresses matched values and artifact names.
