# VELOR

**مساعد مبيعات للمحادثات، مصمم للتجار المصريين.** يجمع محادثات العملاء في مساحة عمل واحدة، يرد وفق بيانات التاجر، ويعرض الأدلة والخطوة التالية لفريق المبيعات.

> **حالة الإصدار:** المشروع مناسب حاليًا لتجربة Pilot مضبوطة عبر Web Chat. لا يُقدَّم بعد كخدمة مدفوعة ذاتية بالكامل؛ الدفع الإلكتروني وWhatsApp Business Platform الرسمي لم يتم ربطهما للإنتاج.

![VELOR landing page](docs/assets/landing-desktop.png)

## ما الذي يعمل الآن؟

| القدرة | الحالة | ما تعنيه عمليًا |
|---|---|---|
| Hosted Web Chat | متاح | رابط محادثة عام لكل متجر، مع جلسة زائر ومحادثات محفوظة |
| صندوق الوارد ومساحة العميل | متاح | مراجعة المحادثة، الأدلة، حالة العميل، والتدخل البشري |
| ردود VELOR المدعومة ببيانات المتجر | متاح | مسار AI مع fallback محدود عند تعذّر المزوّد؛ الجاهزية توضّح حالة المزوّد |
| استيراد المعرفة والكتالوج | متاح | مصادر وملفات منظمة مع حدود للرفع والمعالجة |
| WhatsApp QR | **Beta** | بوابة Node اختيارية تعتمد جلسة QR؛ تحتاج تشغيلًا ومراقبة منفصلين ولا تُعامل كتكامل رسمي |
| WhatsApp Business Platform (Meta) | غير جاهز للإنتاج | يوجد أساس webhook خلف feature flag، لكن الاعتماد الرسمي والإعداد التشغيلي غير مكتملين |
| الاشتراك والدفع الذاتي | غير متصل | صفحات الخطط لا تعني وجود checkout أو تحصيل فعلي حتى ربط مزود دفع |
| مؤشرات الإيراد/الفوز | غير معتمدة بعد | لا تُعرض كحقائق مالية قبل وجود حدث طلب/دفع ثابت ومصدر بيانات موثوق |

## Revenue Recovery Pilot

- لوحة المتابعة والتحليلات ومساحة العميل تستخدم قائمة موحّدة مرتبطة برسالة أو حدث مصدر، بفئات: ينتظر ردنا، جاهز لخطوة شراء، مخاطرة موثقة، ومتابعة مستحقة.
- المتابعات durable وtenant-scoped، وتدعم الإكمال والتجاهل والتأجيل والإلغاء والاستبدال عند وصول دور عميل أحدث.
- استخدام الرد المقترح يعني إرسالًا ناجحًا ومتحققًا على الخادم؛ الإدراج وحده لا يغيّر حالة الاقتراح إلى مستخدم.
- Recovery Impact يقيس سلوك المالك من الأحداث المحفوظة، ويعرض النتائج المالية `null/not_connected` إلى أن يتصل مصدر طلب أو دفع موثوق.
- `/api/engine/opportunity` و`/api/engine/lost` بقيا كمهايئات توافق بلا أموال مفترضة أو احتمال دفع.

## لماذا VELOR؟

- ردود عربية مناسبة لسياق البيع بدل chatbot عام.
- إجابات مربوطة بالكتالوج والمعرفة المملوكة للتاجر.
- تسليم واضح للإنسان عند الحاجة، مع تاريخ المحادثة وسياق القرار.
- عزل بيانات كل شركة، جلسات مصادقة، rate limiting، وسجل تدقيق.
- واجهة تشغيل واحدة لمتابعة العملاء بدل ضياع الرسائل بين القنوات.

## لقطات المنتج

<p align="center">
  <img src="docs/assets/landing-mobile.png" alt="VELOR mobile landing page" width="28%">
  <img src="docs/assets/dashboard-desktop.png" alt="VELOR merchant dashboard" width="68%">
</p>

## دليل الجودة الحالي

آخر تحقق من تثبيت نظيف في 2026-07-22: `1940/1940` اختبار Backend، و`47/47` اختبار Frontend، وESLint بخروج ناجح، وبناء Vite ناجح (`2283` modules)، و`pip check` بلا تعارضات. نجح تدقيق اعتماديات بوابة Node واعتماديات الواجهة الإنتاجية؛ بقيت تنبيهات موثقة في أدوات تطوير Vite وتتطلب ترقية رئيسية منفصلة. آخر Browser QA موثّق يظل `43/43` من 2026-07-19 ولم يُعَد في مرحلة الإعداد هذه. النتائج تثبت النسخة المختبرة فقط، ولا تستبدل staging أو اختبار خدمات الإنتاج الحقيقية.

راجع [تقرير جاهزية الإطلاق](docs/release/VELOR_LAUNCH_READINESS_AUDIT.md) لمعرفة ما تم توحيده، تعريف كل مؤشر، والبوابات الخارجية المتبقية قبل إعلان Facebook أو تحصيل اشتراك.

## البنية

```text
العميل عبر Web Chat
        │
        ▼
React + Vite ─────► FastAPI ─────► SQLAlchemy / PostgreSQL
   لوحة التاجر       API + SSE        (SQLite للتطوير فقط)
                         │
                         ├────► مزود AI + fallback محدود
                         └────► Node QR gateway (WhatsApp Beta، اختياري)
```

- `frontend/`: واجهة React، صفحة الهبوط، Web Chat، ولوحة التاجر.
- `backend/`: FastAPI، نماذج البيانات، مسارات المحادثة، المعرفة، التحليلات، والاختبارات.
- `backend/migrations/`: Alembic؛ هو المسار المعتمد لتغيير قاعدة البيانات.
- `backend/whatsapp_gate.js`: بوابة WhatsApp QR التجريبية المنفصلة.
- [`docs/`](docs/README.md): خريطة العقود الحالية وتقارير التحقق التاريخية.
- [`docs/setup/LOCAL_SETUP.md`](docs/setup/LOCAL_SETUP.md): إعداد قابل للتكرار وحدود ملفات القفل.

## التشغيل المحلي

### المتطلبات

- Python 3.11 أو 3.12
- Node.js 20+
- npm 10+
- PostgreSQL للإنتاج؛ SQLite يكفي للتطوير المحلي فقط

### 1. الخلفية

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements-dev.lock
if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env }
```

ملفا `backend/requirements.lock` و`backend/requirements-dev.lock` يثبتان الإصدارات الدقيقة ويستخدمهما CI. ملفات `requirements*.txt` تعبّر عن النطاقات المسموحة عند تحديث الاعتماديات؛ لا تستخدمها لتثبيت قابل للتكرار. هذا إعداد تطوير/تحقق وليس وصفة نشر production.

على macOS/Linux استخدم `python3 -m venv .venv` ثم `source .venv/bin/activate`، واستبدل `Copy-Item` بـ `cp`.

أنشئ قيمتين عشوائيتين منفصلتين بـ `python -c "import secrets; print(secrets.token_urlsafe(48))"`، ثم ضع إحداهما في `JWT_SECRET` والأخرى في `NODE_INTERNAL_SECRET` داخل `backend/.env`. لا تستخدم القيم نفسها في staging أو production.

```powershell
Set-Location backend
python -m alembic upgrade head
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

واجهة OpenAPI متاحة في وضع التطوير على `http://127.0.0.1:8000/docs`، وفحص الصحة على `/health`، وفحص الجاهزية على `/ready`.

### 2. الواجهة

```powershell
Set-Location frontend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm ci
npm run dev
```

افتح `http://127.0.0.1:5173`. وضع Google OAuth معطل افتراضيًا، ولا يجب تفعيله دون Client ID صحيح وإعداد backend مطابق.

### 3. بوابة WhatsApp QR الاختيارية (Beta)

```powershell
Set-Location backend
npm ci
node whatsapp_gate.js
```

اضبط `ALLOWED_FRONTEND` و`BACKEND_CHAT_URL` و`NODE_INTERNAL_SECRET` قبل التشغيل. لا تعتمد هذا المسار كبديل عن WhatsApp Business Platform الرسمي في إطلاق عام.

## الاختبارات والجودة

نفّذ قبل كل Pull Request:

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

فحص hygiene يفحص ما سيعتبره Git مصدرًا ويعرض جردًا تجميعيًا للآثار المحلية من دون أسماء أو محتوى. ملف [`.github/workflows/ci.yml`](.github/workflows/ci.yml) يشغّل بوابات الجودة وفحص الأسرار/الآثار على GitHub Actions. الاختبارات لا تحتاج مفتاح AI حقيقي، ولا ينبغي إضافة أي سر إلى إعدادات CI إلا عند وجود اختبار تكامل مخصص ومحمي.

لا تحذف أو تنقل قواعد البيانات أو الجلسات أو السجلات لتنظيف Git. هذه الملفات مستبعدة فقط من المصدر، وبقاؤها داخل مجلد OneDrive يعني أنها قد تظل متزامنة. راجع [سياسة التعامل مع الآثار المحلية](docs/security/LOCAL_ARTIFACT_HANDLING.md) قبل أي نقل لاحق.

## إدارة حساب المسؤول

لا توجد كلمة مرور مدير داخل المستودع. لإضافة/إعادة ضبط حساب، مرر كلمة المرور عبر متغير بيئة فقط:

```powershell
$env:VELOR_ADMIN_EMAIL = "owner@example.com"
$env:VELOR_ADMIN_PASSWORD = "use-a-unique-password-of-16+-characters"
python backend\reset_admin.py --role super_admin --yes
Remove-Item Env:VELOR_ADMIN_PASSWORD
```

يجب تشغيل migrations أولًا، واستخدام مدير أسرار في بيئات النشر.

## النشر المسؤول

قبل إطلاق مدفوع عام: استخدم PostgreSQL مُدارًا وHTTPS، اضبط origins والأسرار، فعّل النسخ الاحتياطي والمراقبة، اربط مزود AI موثوقًا، أكمل تكامل Meta الرسمي، اربط checkout/webhooks للدفع، ونفّذ اختبار استعادة وsmoke test على staging. ظهور حالة `degraded` في `/ready` يعني أن التطبيق يعمل في fallback وليس أن كل الاعتمادات سليمة.

راجع [SECURITY.md](SECURITY.md) للإبلاغ الأمني و[CONTRIBUTING.md](CONTRIBUTING.md) لسير المساهمة.

## English summary

VELOR is a conversation-first sales assistant for Egyptian merchants. The hosted Web Chat, merchant workspace, tenant-scoped data model, knowledge/catalog flow, and bounded AI fallback are implemented. WhatsApp QR remains beta; the official Meta integration and paid self-service checkout are not production-connected. Treat the current build as a controlled pilot, and use the release checklist above before a public paid launch.

## License

No public license has been selected yet. Do not assume permission to copy, modify, or redistribute this repository until the owner adds an explicit license.
