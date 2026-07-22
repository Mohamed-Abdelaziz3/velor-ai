import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Bot,
  Building2,
  Check,
  CheckCircle2,
  ClipboardCheck,
  Copy,
  ExternalLink,
  FileText,
  Globe2,
  Languages,
  MessageCircle,
  QrCode,
  RefreshCw,
  Rocket,
  ShieldCheck,
  Smartphone,
  Sparkles,
  Wifi,
  WifiOff,
} from 'lucide-react';
import api from '../../services/api';
import { VelorLogo } from '../../components/velor/VelorLogo';
import {
  Badge,
  Button,
  Card,
  CheckItem,
  DataStateNotice,
  Field,
  ProgressBar,
  SelectField,
  TextArea,
  Toggle,
  cx,
} from '../../components/velor/ui';

const STEPS = [
  {
    id: 'workspace',
    label: 'مساحة العمل',
    title: 'عرّفنا بنشاطك',
    prompt: 'سنستخدم هذه الهوية في كل مكان يظهر فيه VELOR لفريقك وعند استقبال العميل في دردشة الموقع.',
    icon: Building2,
  },
  {
    id: 'channel',
    label: 'القناة',
    title: 'أين ستصل محادثات العملاء؟',
    prompt: 'اربط مسارًا حقيقيًا واحدًا على الأقل للعملاء. يمكنك إضافة القناة الأخرى لاحقًا من الإعدادات.',
    icon: MessageCircle,
  },
  {
    id: 'knowledge',
    label: 'المعرفة',
    title: 'زوّد VELOR بسياق نشاطك',
    prompt: 'أضف إرشادات مختصرة وقابلة للتحقق عما تبيعه وكيف يتعامل المساعد مع المعلومات غير المعروفة.',
    icon: BookOpen,
  },
  {
    id: 'voice',
    label: 'نبرة VELOR',
    title: 'شكّل تجربة العميل',
    prompt: 'اختر نبرة وترحيبًا يناسبان نشاطك. تظل هذه الإعدادات قابلة للتعديل.',
    icon: Sparkles,
  },
  {
    id: 'launch',
    label: 'الاختبار والتشغيل',
    title: 'راجع واختبر ثم ادخل مركز المتابعة',
    prompt: 'كل شيء واضح: راجع كل إعداد محفوظ واستخدم اختبار قناة حقيقيًا عندما يكون متاحًا.',
    icon: Rocket,
  },
];

const TONES = [
  { value: 'professional', label: 'احترافية', description: 'واضحة ومتزنة ومباشرة.' },
  { value: 'friendly', label: 'ودودة', description: 'دافئة ومفيدة وطبيعية.' },
  { value: 'luxury', label: 'راقية', description: 'متزنة ومختصرة وتناسب العلامات الراقية.' },
  { value: 'sales', label: 'مساعدة بيعية', description: 'تدفع المحادثة للأمام من دون ضغط.' },
];

const LANGUAGES = [
  { value: 'Arabic', label: 'العربية' },
  { value: 'English', label: 'الإنجليزية' },
  { value: 'Arabic/English', label: 'العربية والإنجليزية' },
];

const CONNECTED_STATES = new Set(['connected', 'open', 'ready']);
const POLLING_STATES = new Set(['initializing', 'already_running', 'waiting_qr', 'connecting']);
const SAFE_STARTER = 'أجب فقط من الكتالوج والسياسات الموثقة. إذا كان السعر أو المخزون أو الخصم أو الضمان أو تفاصيل التوصيل غير معروفة، وضّح ذلك واعرض التأكد من صاحب النشاط.';

const initialWorkspace = {
  companyName: '',
  industry: '',
  systemPrompt: '',
  tone: 'professional',
  welcomeMessage: '',
  language: 'Arabic',
  leadCollection: true,
};

const normalizeStatus = (value) => String(value || 'unknown').trim().toLowerCase();

const getErrorMessage = (error, fallback) => {
  const detail = error?.response?.data?.detail || error?.response?.data?.message;
  if (typeof detail === 'string' && /[\u0600-\u06FF]/.test(detail)) return detail;
  if (typeof detail?.message === 'string' && /[\u0600-\u06FF]/.test(detail.message)) return detail.message;
  return fallback;
};

const displayChannelReason = (value, fallback) => (
  typeof value === 'string' && /[\u0600-\u06FF]/.test(value) ? value : fallback
);

const getWhatsAppPresentation = (status) => {
  const normalized = normalizeStatus(status);
  if (CONNECTED_STATES.has(normalized)) {
    return { label: 'متصل', tone: 'green', icon: Wifi, description: 'جلسة QR التجريبية متصلة.' };
  }
  if (normalized === 'waiting_qr') {
    return { label: 'امسح رمز QR', tone: 'purple', icon: QrCode, description: 'افتح الأجهزة المرتبطة في واتساب وامسح الرمز.' };
  }
  if (POLLING_STATES.has(normalized)) {
    return { label: 'جاري التجهيز', tone: 'blue', icon: RefreshCw, description: 'يجهّز VELOR جلسة QR تجريبية.' };
  }
  if (normalized === 'logged_out') {
    return { label: 'تم تسجيل الخروج', tone: 'amber', icon: WifiOff, description: 'ابدأ جلسة جديدة لإعادة الاتصال.' };
  }
  if (normalized === 'unknown') {
    return { label: 'غير متاح', tone: 'neutral', icon: WifiOff, description: 'لم يتم تأكيد حالة القناة.' };
  }
  return { label: 'غير متصل', tone: 'neutral', icon: WifiOff, description: 'ابدأ جلسة QR تجريبية عندما تكون جاهزًا.' };
};

function StepRail({ currentStep, onSelect, hasCompletedAllSteps }) {
  return (
    <ol className="grid min-w-[620px] grid-cols-5 gap-2 lg:min-w-0" aria-label="تقدم الإعداد">
      {STEPS.map((step, index) => {
        const Icon = step.icon;
        const complete = index < currentStep || (hasCompletedAllSteps && index !== currentStep);
        const active = index === currentStep;
        return (
          <li key={step.id}>
            <button
              type="button"
              onClick={() => onSelect(index)}
              disabled={!hasCompletedAllSteps && index > currentStep}
              aria-current={active ? 'step' : undefined}
              className={cx(
                'group flex w-full items-center gap-2 rounded-xl border px-2.5 py-2 text-right transition sm:px-3',
                active && 'border-velor-purple/45 bg-velor-purple/10 text-white shadow-[0_0_24px_rgba(155,92,255,0.10)]',
                complete && 'border-velor-green/20 bg-velor-green/[0.055] text-velor-secondary hover:border-velor-green/35',
                !active && !complete && 'cursor-not-allowed border-white/[0.055] bg-white/[0.02] text-velor-muted',
              )}
            >
              <span
                className={cx(
                  'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border transition',
                  active && 'border-velor-purple/30 bg-velor-purple/15 text-velor-violet',
                  complete && 'border-velor-green/25 bg-velor-green/10 text-velor-green',
                  !active && !complete && 'border-white/[0.07] bg-white/[0.025]',
                )}
              >
                {complete ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : <Icon className="h-3.5 w-3.5" aria-hidden="true" />}
              </span>
              <span className="min-w-0">
                <span className="block text-[10px] font-semibold uppercase tracking-[0.12em] opacity-60">0{index + 1}</span>
                <span className="block truncate text-xs font-semibold">{step.label}</span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function WorkspaceStep({ form, updateForm, errors }) {
  return (
    <div className="grid gap-5 sm:grid-cols-2">
      <Field
        label="اسم مساحة العمل"
        hint="مطلوب"
        icon={Building2}
        value={form.companyName}
        onChange={(event) => updateForm('companyName', event.target.value)}
        placeholder="مثال: النور للأثاث"
        maxLength={100}
        autoComplete="organization"
        error={errors.companyName}
      />
      <Field
        label="مجال النشاط"
        hint="مطلوب"
        icon={Globe2}
        value={form.industry}
        onChange={(event) => updateForm('industry', event.target.value)}
        placeholder="مثال: أثاث المكاتب"
        maxLength={100}
        error={errors.industry}
      />
      <Card className="overflow-hidden p-4 sm:col-span-2" glow>
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-velor-blue/20 bg-velor-blue/10 text-velor-blue">
            <ShieldCheck className="h-5 w-5" aria-hidden="true" />
          </span>
          <div>
            <p className="text-sm font-semibold text-white">هوية واضحة الآن تمنع الارتباك لاحقًا.</p>
            <p className="mt-1 text-xs leading-5 text-velor-muted">
              يستخدم VELOR هذين الحقلين في أسماء مساحة العمل وسياق دردشة الموقع. لا ينشئان ادعاءات عامة عن نشاطك.
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
}

function ChannelStep({
  whatsapp,
  webChat,
  onStartWhatsApp,
  onRefreshWhatsApp,
  onToggleWebChat,
  onCopyLink,
  copied,
}) {
  const wa = getWhatsAppPresentation(whatsapp.status);
  const WaIcon = wa.icon;
  const connected = CONNECTED_STATES.has(normalizeStatus(whatsapp.status));
  const publicUrl = webChat.slug && typeof window !== 'undefined' ? `${window.location.origin}/c/${webChat.slug}` : '';

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card className={cx('overflow-hidden p-5', connected && 'border-velor-green/20')} interactive>
        <div className="flex items-start justify-between gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-velor-green/20 bg-velor-green/10 text-velor-green">
            <Smartphone className="h-5 w-5" aria-hidden="true" />
          </span>
          <span className={cx(
            "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-semibold leading-none",
            connected ? "border-emerald-500/25 bg-emerald-500/[0.04] text-emerald-300" : "border-white/10 bg-white/[0.02] text-velor-muted"
          )}>
            <span className={cx(
              "h-1.5 w-1.5 rounded-full",
              connected ? "bg-emerald-400 animate-pulse" : "bg-velor-muted"
            )} />
            <span>{wa.label}</span>
          </span>
        </div>
        <h3 className="mt-5 text-base font-semibold text-white">واتساب QR التجريبي</h3>
        <p className="mt-1 min-h-10 text-xs leading-5 text-velor-muted">
          اتصال QR مستضاف ذاتيًا في نسخة VELOR التجريبية الحالية. هذا ليس اتصال WhatsApp Business Cloud API الرسمي.
        </p>

        <div className="mt-4 rounded-xl border border-white/[0.07] bg-black/20 p-3">
          <div className="flex items-start gap-2.5">
            <WaIcon className={cx('mt-0.5 h-4 w-4 shrink-0', connected ? 'text-velor-green' : 'text-velor-secondary')} aria-hidden="true" />
            <div>
              <p className="text-xs font-semibold text-white">{wa.label}</p>
              <p className="mt-0.5 text-[11px] leading-5 text-velor-muted">{displayChannelReason(whatsapp.reason, wa.description)}</p>
            </div>
          </div>
        </div>

        {whatsapp.qrCode && !connected && (
          <div className="mt-4 flex flex-col items-center rounded-xl border border-velor-purple/20 bg-white p-3 text-center">
            <img src={whatsapp.qrCode} alt="رمز اتصال واتساب QR التجريبي" className="h-44 w-44 rounded-lg" />
            <p className="mt-2 text-[10px] font-semibold text-[#211a2d]">واتساب ← الأجهزة المرتبطة ← ربط جهاز</p>
          </div>
        )}

        <div className="mt-4 grid grid-cols-2 gap-2">
          <Button
            className="w-full"
            variant={connected ? 'secondary' : 'primary'}
            onClick={onStartWhatsApp}
            loading={whatsapp.busy}
          >
            {connected ? 'إعادة الاتصال' : 'بدء جلسة QR'}
          </Button>
          <Button className="w-full" variant="secondary" onClick={onRefreshWhatsApp} disabled={whatsapp.busy}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            تحديث
          </Button>
        </div>
      </Card>

      <Card className={cx('overflow-hidden p-5', webChat.enabled && 'border-velor-blue/20')} interactive>
        <div className="flex items-start justify-between gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-velor-blue/20 bg-velor-blue/10 text-velor-blue">
            <Globe2 className="h-5 w-5" aria-hidden="true" />
          </span>
          <span className={cx(
            "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-semibold leading-none",
            webChat.enabled ? "border-blue-500/25 bg-blue-500/[0.04] text-blue-300" : "border-white/10 bg-white/[0.02] text-velor-muted"
          )}>
            <span className={cx(
              "h-1.5 w-1.5 rounded-full",
              webChat.enabled ? "bg-blue-400 animate-pulse" : "bg-velor-muted"
            )} />
            <span>{webChat.enabled ? 'مفعّلة' : 'متوقفة'}</span>
          </span>
        </div>
        <h3 className="mt-5 text-base font-semibold text-white">دردشة الموقع المستضافة</h3>
        <p className="mt-1 min-h-10 text-xs leading-5 text-velor-muted">
          صفحة دردشة قابلة للمشاركة يستضيفها VELOR. ودجت التضمين داخل الموقع ليست جزءًا من التكامل الحالي.
        </p>

        <div className="mt-4 rounded-xl border border-white/[0.07] bg-black/20 p-3.5">
          <Toggle
            checked={webChat.enabled}
            onChange={onToggleWebChat}
            disabled={webChat.busy}
            label="تفعيل دردشة الموقع"
            description="ينشئ أو يفعّل رابط دردشة عامًا خاصًا بنشاطك."
          />
        </div>

        {webChat.enabled && publicUrl && (
          <div className="mt-4 rounded-xl border border-velor-blue/15 bg-velor-blue/[0.045] p-3">
            <p className="text-[10px] font-bold tracking-[0.12em] text-velor-blue">الرابط المستضاف</p>
            <p className="mt-1 truncate text-xs text-velor-secondary" dir="ltr">{publicUrl}</p>
            <div className="mt-3 flex gap-2">
              <Button className="flex-1" variant="secondary" onClick={() => onCopyLink(publicUrl)}>
                <Copy className="h-4 w-4" aria-hidden="true" />
                {copied ? 'تم النسخ' : 'نسخ'}
              </Button>
              <a className="velor-button-secondary flex-1" href={publicUrl} target="_blank" rel="noreferrer">
                <ExternalLink className="h-4 w-4" aria-hidden="true" />
                فتح
              </a>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function KnowledgeStep({ form, updateForm, promptLimit, catalogStatus, sourceStatus, errors }) {
  const used = form.systemPrompt.length;
  return (
    <div className="space-y-5">
      <div>
        <TextArea
          label="إرشادات وضوابط النشاط"
          hint={`${used.toLocaleString()} / ${promptLimit.toLocaleString()}`}
          value={form.systemPrompt}
          onChange={(event) => updateForm('systemPrompt', event.target.value)}
          maxLength={promptLimit}
          rows={7}
          placeholder="اشرح المنتجات والسياسات والحدود الموثقة وما الذي يجب أن يفعله VELOR عند نقص المعلومات."
          className={cx('min-h-44', errors.systemPrompt && 'border-velor-red/70')}
        />
        {errors.systemPrompt && <p className="mt-2 text-xs text-velor-red" role="alert">{errors.systemPrompt}</p>}
        {!form.systemPrompt.trim() && (
          <Button className="mt-3" variant="secondary" onClick={() => updateForm('systemPrompt', SAFE_STARTER)}>
            <ShieldCheck className="h-4 w-4" aria-hidden="true" />
            استخدم بداية آمنة
          </Button>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Card className="p-4">
          <div className="flex items-center justify-between gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-velor-purple/20 bg-velor-purple/10 text-velor-violet">
              <FileText className="h-4 w-4" aria-hidden="true" />
            </span>
            <span className="metric-numbers text-xl font-semibold text-white">{Number(catalogStatus.total_records || 0).toLocaleString()}</span>
          </div>
          <p className="mt-3 text-xs font-semibold text-white">سجلات الكتالوج</p>
          <p className="mt-1 text-[11px] leading-5 text-velor-muted">بيانات كتالوج مُدارة ومتاحة بالفعل لمساحة العمل.</p>
        </Card>
        <Card className="p-4">
          <div className="flex items-center justify-between gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-velor-blue/20 bg-velor-blue/10 text-velor-blue">
              <BookOpen className="h-4 w-4" aria-hidden="true" />
            </span>
            <span className="metric-numbers text-xl font-semibold text-white">{Number(sourceStatus.active || 0).toLocaleString()}</span>
          </div>
          <p className="mt-3 text-xs font-semibold text-white">المصادر النشطة</p>
          <p className="mt-1 text-[11px] leading-5 text-velor-muted">مصادر معرفة تمت معالجتها وتفعيلها لردود مبنية على الحقائق.</p>
        </Card>
      </div>

      <DataStateNotice
        tone="blue"
        title="المعلومات الموثقة هي المرجع"
        description="تحفظ هذه الخطوة إرشادات المساعد المدعومة فقط. يظل استيراد الكتالوج وإدارة المستندات متاحين من الإعدادات بعد الانتهاء."
      />
    </div>
  );
}

function VoiceStep({ form, updateForm, errors }) {
  return (
    <div className="space-y-6">
      <fieldset>
        <legend className="text-xs font-semibold text-velor-secondary">نبرة المحادثة</legend>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {TONES.map((tone) => {
            const active = form.tone === tone.value;
            return (
              <button
                key={tone.value}
                type="button"
                onClick={() => updateForm('tone', tone.value)}
                aria-pressed={active}
                className={cx(
                  'group rounded-xl border p-4 text-right transition active:scale-[.99]',
                  active
                    ? 'border-velor-purple/45 bg-velor-purple/10 shadow-[0_0_26px_rgba(155,92,255,0.10)]'
                    : 'border-white/[0.07] bg-white/[0.025] hover:border-white/15 hover:bg-white/[0.045]',
                )}
              >
                <span className="flex items-start justify-between gap-3">
                  <span>
                    <span className="block text-sm font-semibold text-white">{tone.label}</span>
                    <span className="mt-1 block text-xs leading-5 text-velor-muted">{tone.description}</span>
                  </span>
                  <span className={cx('flex h-5 w-5 shrink-0 items-center justify-center rounded-full border', active ? 'border-velor-purple bg-velor-purple text-white' : 'border-white/15')}>
                    {active && <Check className="h-3 w-3" aria-hidden="true" />}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </fieldset>

      <SelectField
        label="لغة الرد الأساسية"
        value={form.language}
        onChange={(event) => updateForm('language', event.target.value)}
      >
        {LANGUAGES.map((language) => <option key={language.value} value={language.value}>{language.label}</option>)}
      </SelectField>

      <div>
        <TextArea
          label="رسالة الترحيب"
          hint="تظهر في بداية دردشة الموقع"
          value={form.welcomeMessage}
          onChange={(event) => updateForm('welcomeMessage', event.target.value)}
          maxLength={1000}
          rows={4}
          placeholder="أهلًا بك! إزاي نقدر نساعدك النهارده؟"
          className={cx('min-h-28', errors.welcomeMessage && 'border-velor-red/70')}
        />
        {errors.welcomeMessage && <p className="mt-2 text-xs text-velor-red" role="alert">{errors.welcomeMessage}</p>}
      </div>

      <Card className="p-4">
        <Toggle
          checked={form.leadCollection}
          onChange={(checked) => updateForm('leadCollection', checked)}
          label="السماح بجمع بيانات التواصل"
          description="يسمح لـ VELOR بجمع بيانات تواصل العميل عندما تحتاج المحادثة إلى متابعة بشكل طبيعي."
        />
      </Card>
    </div>
  );
}

function LaunchStep({ form, webChat, whatsapp, onCopyLink, copied }) {
  const waConnected = CONNECTED_STATES.has(normalizeStatus(whatsapp.status));
  const publicUrl = webChat.slug && typeof window !== 'undefined' ? `${window.location.origin}/c/${webChat.slug}` : '';

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(280px,.9fr)]">
      <Card className="overflow-hidden p-5" glow>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-velor-purple/20 bg-velor-purple/10 text-velor-violet">
              <Bot className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <p className="text-sm font-semibold text-white">بداية المحادثة</p>
              <p className="text-[11px] text-velor-muted">رسالة الترحيب المحفوظة</p>
            </div>
          </div>
        </div>

        <div className="mt-6 rounded-2xl border border-white/[0.07] bg-[#090a11] p-4 sm:p-5">
          <div className="ml-auto max-w-[88%] rounded-2xl rounded-br-md border border-velor-purple/20 bg-velor-purple/10 px-4 py-3 text-sm leading-6 text-white">
            {form.welcomeMessage || 'ستظهر رسالة الترحيب هنا.'}
          </div>
        </div>

        {webChat.enabled && publicUrl ? (
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            <Button variant="secondary" onClick={() => onCopyLink(publicUrl)}>
              <Copy className="h-4 w-4" aria-hidden="true" />
              {copied ? 'تم نسخ الرابط' : 'نسخ رابط الدردشة'}
            </Button>
            <a className="velor-button-primary" href={publicUrl} target="_blank" rel="noreferrer">
              <ExternalLink className="h-4 w-4" aria-hidden="true" />
              فتح دردشة اختبار حقيقية
            </a>
          </div>
        ) : waConnected ? (
          <div className="mt-4">
            <DataStateNotice
              title="اختبر عبر واتساب"
              description="أرسل رسالة حقيقية إلى الرقم المرتبط ثم عد إلى هنا. لا يختلق VELOR نتيجة اختبار ناجحة."
            />
          </div>
        ) : null}
      </Card>

      <Card className="p-5">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-velor-green/20 bg-velor-green/10 text-velor-green">
            <ClipboardCheck className="h-5 w-5" aria-hidden="true" />
          </span>
          <div>
            <p className="text-sm font-semibold text-white">قائمة التشغيل</p>
            <p className="text-[11px] text-velor-muted">تُحفظ عند التشغيل</p>
          </div>
        </div>
        <ul className="mt-5 space-y-3">
          <CheckItem>هوية مساحة العمل: {form.companyName}</CheckItem>
          <CheckItem>{webChat.enabled ? 'دردشة الموقع مفعّلة' : 'واتساب QR التجريبي متصل'}</CheckItem>
          <CheckItem>تمت إضافة إرشادات نشاط مبنية على حقائق</CheckItem>
          <CheckItem>نبرة VELOR: {TONES.find((tone) => tone.value === form.tone)?.label || 'مختارة'}</CheckItem>
          <CheckItem>لغة الرد: {LANGUAGES.find((language) => language.value === form.language)?.label || form.language}</CheckItem>
        </ul>
        <div className="mt-5 rounded-xl border border-velor-green/15 bg-velor-green/[0.055] p-3.5">
          <p className="flex items-center gap-2 text-xs font-semibold text-velor-green">
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            جاهز للانتقال إلى مركز المتابعة
          </p>
          <p className="mt-1 text-[11px] leading-5 text-velor-muted">
            يحفظ التشغيل إعدادات مساحة العمل والمساعد المدعومة فقط.
          </p>
        </div>
      </Card>
    </div>
  );
}

function SetupSummary({ form, currentStep, webChat, whatsapp }) {
  const connected = CONNECTED_STATES.has(normalizeStatus(whatsapp.status));
  const tone = TONES.find((item) => item.value === form.tone)?.label || 'غير مختارة';
  const language = LANGUAGES.find((item) => item.value === form.language)?.label || form.language;
  return (
    <Card className="p-5 xl:sticky xl:top-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-bold tracking-[0.15em] text-velor-purple">ملخص الإعداد</p>
          <h2 className="mt-1 text-sm font-semibold text-white">{form.companyName || 'مساحة عملك'}</h2>
        </div>
        <Badge tone="purple">الخطوة {currentStep + 1}</Badge>
      </div>
      <div className="mt-5 space-y-4">
        <div className="flex items-center justify-between gap-3 border-b border-white/[0.06] pb-3 text-xs">
          <span className="text-velor-muted">مجال النشاط</span>
          <span className="max-w-[58%] truncate font-medium text-velor-secondary">{form.industry || 'لم يُضف'}</span>
        </div>
        <div className="flex items-center justify-between gap-3 border-b border-white/[0.06] pb-3 text-xs">
          <span className="text-velor-muted">WhatsApp</span>
          <Badge tone={connected ? 'green' : 'neutral'}>{connected ? 'متصل' : 'غير متصل'}</Badge>
        </div>
        <div className="flex items-center justify-between gap-3 border-b border-white/[0.06] pb-3 text-xs">
          <span className="text-velor-muted">دردشة الموقع</span>
          <Badge tone={webChat.enabled ? 'blue' : 'neutral'}>{webChat.enabled ? 'مفعّلة' : 'متوقفة'}</Badge>
        </div>
        <div className="flex items-center justify-between gap-3 border-b border-white/[0.06] pb-3 text-xs">
          <span className="text-velor-muted">النبرة</span>
          <span className="font-medium text-velor-secondary">{tone}</span>
        </div>
        <div className="flex items-center justify-between gap-3 text-xs">
          <span className="text-velor-muted">اللغة</span>
          <span className="font-medium text-velor-secondary">{language}</span>
        </div>
      </div>
      <div className="mt-5 rounded-xl border border-white/[0.06] bg-black/20 p-3">
        <p className="flex items-center gap-2 text-[11px] font-semibold text-velor-secondary">
          <ShieldCheck className="h-3.5 w-3.5 text-velor-green" aria-hidden="true" />
          إعداد مرتبط بالقدرات المدعومة
        </p>
        <p className="mt-1 text-[10px] leading-5 text-velor-muted">يتم حفظ الإعدادات التي يدعمها خادم VELOR الحالي فقط.</p>
      </div>
    </Card>
  );
}

function VelorWorkspaceIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <path d="M8 21h8" />
      <path d="M12 17v4" />
      <circle cx="7" cy="8" r="1.5" fill="currentColor" />
      <circle cx="17" cy="6" r="1" />
      <circle cx="17" cy="10" r="1" />
      <path d="M8.5 8h4c1 0 1.5-.5 1.5-1.5v0C14 5.5 14.5 5 15.5 5h.5" />
      <path d="M12.5 8c0 1 .5 1.5 1.5 1.5h2" />
    </svg>
  );
}

function VelorChannelsIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <rect x="2" y="4" width="13" height="10" rx="1.5" />
      <path d="M2 7h13" />
      <rect x="12" y="8" width="8" height="13" rx="1.5" />
      <circle cx="16" cy="18" r="0.75" fill="currentColor" />
      <path d="M9 17a3 3 0 0 1 3-3" strokeDasharray="2 2" />
    </svg>
  );
}

function VelorKnowledgeIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
      <ellipse cx="12" cy="11" rx="4" ry="1.5" />
      <path d="M8 11v3c0 .8 1.8 1.5 4 1.5s4-.7 4-1.5v-3" />
      <path d="M8 14v3c0 .8 1.8 1.5 4 1.5s4-.7 4-1.5v-3" />
    </svg>
  );
}

function VelorPersonaIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      <path d="M7 10h1M10 8v4M13 7v6M16 9v2" />
    </svg>
  );
}

function OnboardingSummary({ form, webChat, whatsapp, catalogStatus, sourceStatus, onEdit, onGoToDashboard }) {
  const wa = getWhatsAppPresentation(whatsapp.status);
  const waConnected = CONNECTED_STATES.has(normalizeStatus(whatsapp.status));
  const publicUrl = webChat.slug && typeof window !== 'undefined' ? `${window.location.origin}/c/${webChat.slug}` : '';
  const toneLabel = TONES.find((t) => t.value === form.tone)?.label || form.tone;
  const languageLabel = LANGUAGES.find((l) => l.value === form.language)?.label || form.language;

  return (
    <div className="space-y-8">
      {/* ── Header ── */}
      <div className="animate-velor-in flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="mb-3 flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-velor-green" />
            <span className="text-[10px] font-bold uppercase tracking-[0.18em]" style={{ color: '#6b6585' }}>الإعداد مكتمل</span>
          </div>
          <h1 className="text-2xl font-bold tracking-[-0.025em] text-white">ملخص إعداد VELOR المكتمل</h1>
          <p className="mt-2 max-w-lg text-[13px] leading-relaxed" style={{ color: '#6b6585' }}>
            تم تهيئة المساعد بنجاح. راجع التفاصيل أدناه أو اضغط على تعديل لتحديث الإعدادات.
          </p>
        </div>
        <div className="flex shrink-0 gap-2.5 pt-1">
          <Button variant="secondary" onClick={onEdit}>
            <Sparkles className="ml-2 h-4 w-4" aria-hidden="true" />
            تعديل الإعدادات
          </Button>
          <Button onClick={onGoToDashboard}>
            الدخول إلى مركز المتابعة
            <ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      {/* ── Cards grid ── */}
      <div className="grid gap-5 md:grid-cols-2">
        {/* 1. مساحة العمل */}
        <Card className="group relative overflow-hidden p-0" interactive style={{ animationDelay: '60ms' }}>
          <div className="absolute inset-x-0 top-0 h-px" style={{ background: 'linear-gradient(90deg, rgba(139,92,246,0.4), rgba(99,102,241,0.15), transparent)' }} />
          <div className="p-6">
            <div className="flex items-center gap-2.5 pb-4" style={{ borderBottom: '1px solid rgba(130,120,220,0.07)' }}>
              <VelorWorkspaceIcon className="h-4 w-4 shrink-0" style={{ color: '#6b6585' }} />
              <h3 className="text-sm font-semibold text-white">مساحة العمل والنشاط</h3>
            </div>
            <div className="mt-5 space-y-0">
              <div className="flex items-center justify-between py-2.5" style={{ borderBottom: '1px dashed rgba(130,120,220,0.06)' }}>
                <span className="text-xs" style={{ color: '#6b6585' }}>اسم مساحة العمل</span>
                <span className="text-sm font-medium text-white">{form.companyName}</span>
              </div>
              <div className="flex items-center justify-between py-2.5">
                <span className="text-xs" style={{ color: '#6b6585' }}>مجال النشاط</span>
                <span className="text-sm font-medium text-white">{form.industry}</span>
              </div>
            </div>
          </div>
        </Card>

        {/* 2. قنوات الاتصال */}
        <Card className="group relative overflow-hidden p-0" interactive style={{ animationDelay: '120ms' }}>
          <div className="absolute inset-x-0 top-0 h-px" style={{ background: 'linear-gradient(90deg, rgba(139,92,246,0.4), rgba(99,102,241,0.15), transparent)' }} />
          <div className="p-6">
            <div className="flex items-center gap-2.5 pb-4" style={{ borderBottom: '1px solid rgba(130,120,220,0.07)' }}>
              <VelorChannelsIcon className="h-4 w-4 shrink-0" style={{ color: '#6b6585' }} />
              <h3 className="text-sm font-semibold text-white">قنوات الاتصال</h3>
            </div>
            <div className="mt-5 space-y-0">
              <div className="flex items-center justify-between py-2.5" style={{ borderBottom: '1px dashed rgba(130,120,220,0.06)' }}>
                <span className="text-xs" style={{ color: '#6b6585' }}>واتساب QR التجريبي</span>
                <Badge tone={waConnected ? 'green' : 'neutral'}>{wa.label}</Badge>
              </div>
              <div className="flex items-center justify-between py-2.5">
                <span className="text-xs" style={{ color: '#6b6585' }}>دردشة الموقع المستضافة</span>
                <Badge tone={webChat.enabled ? 'blue' : 'neutral'}>{webChat.enabled ? 'مفعّلة' : 'متوقفة'}</Badge>
              </div>
            </div>
            {webChat.enabled && publicUrl && (
              <div
                className="mt-4 rounded-xl p-3 text-right"
                style={{ background: 'rgba(0,0,0,0.15)', border: '1px solid rgba(130,120,220,0.07)' }}
              >
                <p className="text-[10px] font-medium" style={{ color: '#6b6585' }}>رابط الدردشة العام</p>
                <a href={publicUrl} target="_blank" rel="noreferrer" className="mt-1 block truncate text-xs text-velor-purple-hi transition-colors duration-150 hover:text-velor-violet" dir="ltr">
                  {publicUrl}
                </a>
              </div>
            )}
          </div>
        </Card>

        {/* 3. المعرفة والضوابط */}
        <Card className="group relative overflow-hidden p-0 md:col-span-2" interactive style={{ animationDelay: '180ms' }}>
          <div className="absolute inset-x-0 top-0 h-px" style={{ background: 'linear-gradient(90deg, rgba(139,92,246,0.4), rgba(99,102,241,0.15), transparent)' }} />
          <div className="p-6">
            <div className="flex items-center gap-2.5 pb-4" style={{ borderBottom: '1px solid rgba(130,120,220,0.07)' }}>
              <VelorKnowledgeIcon className="h-4 w-4 shrink-0" style={{ color: '#6b6585' }} />
              <h3 className="text-sm font-semibold text-white">المعرفة وإرشادات المساعد</h3>
            </div>
            <div className="mt-5 grid gap-6 sm:grid-cols-2">
              <div className="space-y-0">
                <div className="flex items-center justify-between py-2.5" style={{ borderBottom: '1px dashed rgba(130,120,220,0.06)' }}>
                  <span className="text-xs" style={{ color: '#6b6585' }}>سجلات الكتالوج المتاحة</span>
                  <span className="metric-numbers text-sm font-medium text-white">{Number(catalogStatus.total_records || 0).toLocaleString()} سجل</span>
                </div>
                <div className="flex items-center justify-between py-2.5">
                  <span className="text-xs" style={{ color: '#6b6585' }}>المصادر النشطة الموثوقة</span>
                  <span className="metric-numbers text-sm font-medium text-white">{Number(sourceStatus.active || 0).toLocaleString()} مصدر</span>
                </div>
              </div>
              <div className="space-y-2 sm:border-r sm:pr-5" style={{ borderColor: 'rgba(130,120,220,0.07)' }}>
                <span className="block text-xs font-semibold" style={{ color: '#b0aacb' }}>إرشادات وضوابط النشاط (Prompt)</span>
                <div
                  className="max-h-36 overflow-y-auto rounded-xl p-3.5 font-mono text-xs leading-[1.75] whitespace-pre-wrap"
                  style={{
                    color: '#b0aacb',
                    background: 'linear-gradient(180deg, rgba(0,0,0,0.2), rgba(0,0,0,0.12))',
                    border: '1px solid rgba(130,120,220,0.07)',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.15) inset',
                  }}
                >
                  {form.systemPrompt}
                </div>
              </div>
            </div>
          </div>
        </Card>

        {/* 4. نبرة المحادثة والتجربة */}
        <Card className="group relative overflow-hidden p-0 md:col-span-2" interactive style={{ animationDelay: '240ms' }}>
          <div className="absolute inset-x-0 top-0 h-px" style={{ background: 'linear-gradient(90deg, rgba(139,92,246,0.4), rgba(99,102,241,0.15), transparent)' }} />
          <div className="p-6">
            <div className="flex items-center gap-2.5 pb-4" style={{ borderBottom: '1px solid rgba(130,120,220,0.07)' }}>
              <VelorPersonaIcon className="h-4 w-4 shrink-0" style={{ color: '#6b6585' }} />
              <h3 className="text-sm font-semibold text-white">نبرة وتجربة المحادثة</h3>
            </div>
            <div className="mt-5 grid gap-6 sm:grid-cols-2">
              <div className="space-y-0">
                <div className="flex items-center justify-between py-2.5" style={{ borderBottom: '1px dashed rgba(130,120,220,0.06)' }}>
                  <span className="text-xs" style={{ color: '#6b6585' }}>نبرة الحوار</span>
                  <span className="text-sm font-medium text-white">{toneLabel}</span>
                </div>
                <div className="flex items-center justify-between py-2.5" style={{ borderBottom: '1px dashed rgba(130,120,220,0.06)' }}>
                  <span className="text-xs" style={{ color: '#6b6585' }}>لغة الرد الأساسية</span>
                  <span className="text-sm font-medium text-white">{languageLabel}</span>
                </div>
                <div className="flex items-center justify-between py-2.5">
                  <span className="text-xs" style={{ color: '#6b6585' }}>جمع بيانات التواصل</span>
                  <span className="text-sm font-medium text-white">{form.leadCollection ? 'مسموح به' : 'غير مفعل'}</span>
                </div>
              </div>
              <div className="space-y-2 sm:border-r sm:pr-5" style={{ borderColor: 'rgba(130,120,220,0.07)' }}>
                <span className="block text-xs font-semibold" style={{ color: '#b0aacb' }}>رسالة الترحيب</span>
                <div
                  className="rounded-xl p-3.5 text-xs leading-[1.75] text-white"
                  style={{
                    background: 'linear-gradient(180deg, rgba(0,0,0,0.2), rgba(0,0,0,0.12))',
                    border: '1px solid rgba(130,120,220,0.07)',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.15) inset',
                  }}
                >
                  {form.welcomeMessage || 'لم يتم تعيين رسالة ترحيب.'}
                </div>
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

export default function Onboarding() {
  const navigate = useNavigate();
  const [currentStep, setCurrentStep] = useState(0);
  const [form, setForm] = useState(initialWorkspace);
  const [promptLimit, setPromptLimit] = useState(12000);
  const [catalogStatus, setCatalogStatus] = useState({});
  const [sourceStatus, setSourceStatus] = useState({});
  const [webChat, setWebChat] = useState({ enabled: false, slug: '', busy: false });
  const [whatsapp, setWhatsapp] = useState({ status: 'unknown', qrCode: '', reason: '', busy: false });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [stepErrors, setStepErrors] = useState({});
  const [copied, setCopied] = useState(false);
  const [viewSummary, setViewSummary] = useState(false);
  const [hasCompletedAllSteps, setHasCompletedAllSteps] = useState(false);

  const loadSetup = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    setActionError('');

    const [settingsResult, webChatResult, whatsappResult] = await Promise.allSettled([
      api.get('/whatsapp/settings'),
      api.get('/api/company/bot/web-chat'),
      api.get('/whatsapp/status'),
    ]);

    let loadedForm = initialWorkspace;
    let isWebChatEnabled = false;
    let isWhatsappConnected = false;

    if (settingsResult.status === 'fulfilled' && settingsResult.value.data?.success) {
      const knowledge = settingsResult.value.data?.knowledge || {};
      const normalizedTone = String(knowledge.tone || 'professional').toLowerCase();
      const normalizedLanguage = String(knowledge.language || 'Arabic');
      loadedForm = {
        companyName: knowledge.company_name || '',
        industry: knowledge.industry || '',
        systemPrompt: knowledge.system_prompt || '',
        tone: TONES.some((tone) => tone.value === normalizedTone) ? normalizedTone : 'professional',
        welcomeMessage: knowledge.welcome_message || '',
        language: LANGUAGES.some((language) => language.value === normalizedLanguage) ? normalizedLanguage : 'Arabic',
        leadCollection: knowledge.lead_collection ?? true,
      };
      setForm(loadedForm);
      setPromptLimit(Number(knowledge.system_prompt_max_chars) || 12000);
      setCatalogStatus(knowledge.catalog_status || {});
      setSourceStatus(knowledge.knowledge_source_status || {});
    } else {
      setLoadError('تعذر تحميل إعدادات مساحة العمل المحفوظة. أعد المحاولة قبل المتابعة حتى لا تُستبدل البيانات الحالية.');
    }

    if (webChatResult.status === 'fulfilled') {
      isWebChatEnabled = Boolean(webChatResult.value.data?.is_web_chat_enabled);
      setWebChat({
        enabled: isWebChatEnabled,
        slug: webChatResult.value.data?.public_chat_slug || '',
        busy: false,
      });
    }

    if (whatsappResult.status === 'fulfilled') {
      const waStatus = normalizeStatus(whatsappResult.value.data?.status || whatsappResult.value.data?.state);
      isWhatsappConnected = CONNECTED_STATES.has(waStatus);
      setWhatsapp({
        status: waStatus,
        qrCode: whatsappResult.value.data?.qr_code || whatsappResult.value.data?.qr || '',
        reason: whatsappResult.value.data?.reason || '',
        busy: false,
      });
    } else {
      setWhatsapp({ status: 'unknown', qrCode: '', reason: 'تعذر التحقق من حالة القناة.', busy: false });
    }

    // Determine initial step based on saved data
    const step0Valid = loadedForm.companyName.trim().length >= 2 && loadedForm.industry.trim().length >= 2;
    const step1Valid = isWebChatEnabled || isWhatsappConnected;
    const step2Valid = loadedForm.systemPrompt.trim().length >= 20;
    const step3Valid = Boolean(loadedForm.tone && loadedForm.language && loadedForm.welcomeMessage.trim().length >= 5);

    const allStepsValid = step0Valid && step1Valid && step2Valid && step3Valid;
    setHasCompletedAllSteps(allStepsValid);

    if (allStepsValid) {
      setViewSummary(true);
      setCurrentStep(4);
    } else if (step0Valid) {
      // Step 0 is complete.
      let targetStep = 1;
      if (step1Valid) {
        // Step 1 is complete.
        targetStep = 2;
        if (step2Valid) {
          // Step 2 is complete.
          targetStep = 3;
        }
      }
      setCurrentStep(targetStep);
      setViewSummary(false);
    } else {
      setCurrentStep(0);
      setViewSummary(false);
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    loadSetup();
  }, [loadSetup]);

  const refreshWhatsApp = useCallback(async (silent = false) => {
    if (!silent) setWhatsapp((current) => ({ ...current, busy: true }));
    try {
      const response = await api.get('/whatsapp/status');
      setWhatsapp({
        status: normalizeStatus(response.data?.status || response.data?.state),
        qrCode: response.data?.qr_code || response.data?.qr || '',
        reason: response.data?.reason || '',
        busy: false,
      });
      if (!silent) setActionError('');
    } catch (error) {
      if (!silent) setActionError(getErrorMessage(error, 'حالة واتساب QR التجريبي غير متاحة حاليًا.'));
      setWhatsapp({ status: 'unknown', qrCode: '', reason: 'تعذر التحقق من حالة القناة.', busy: false });
    }
  }, []);

  useEffect(() => {
    if (!POLLING_STATES.has(normalizeStatus(whatsapp.status))) return undefined;
    const interval = window.setInterval(() => refreshWhatsApp(true), 2500);
    return () => window.clearInterval(interval);
  }, [refreshWhatsApp, whatsapp.status]);

  const startWhatsApp = async () => {
    setActionError('');
    setWhatsapp((current) => ({ ...current, busy: true, reason: '' }));
    try {
      const response = await api.post('/whatsapp/start');
      setWhatsapp((current) => ({
        ...current,
        status: normalizeStatus(response.data?.status || 'initializing'),
        busy: false,
      }));
    } catch (error) {
      setActionError(getErrorMessage(error, 'تعذر بدء جلسة واتساب QR التجريبية.'));
      setWhatsapp((current) => ({ ...current, busy: false }));
    }
  };

  const toggleWebChat = async () => {
    const enabled = !webChat.enabled;
    setActionError('');
    setWebChat((current) => ({ ...current, busy: true }));
    try {
      const response = await api.post('/api/company/bot/web-chat', { enabled });
      setWebChat({
        enabled: Boolean(response.data?.is_web_chat_enabled),
        slug: response.data?.public_chat_slug || '',
        busy: false,
      });
    } catch (error) {
      setActionError(getErrorMessage(error, 'تعذر تحديث دردشة الموقع المستضافة.'));
      setWebChat((current) => ({ ...current, busy: false }));
    }
  };

  const updateForm = (field, value) => {
    setForm((current) => ({ ...current, [field]: value }));
    setStepErrors((current) => ({ ...current, [field]: undefined, general: undefined }));
  };

  const validateStep = useCallback((stepIndex) => {
    const errors = {};
    if (stepIndex === 0) {
      if (form.companyName.trim().length < 2) errors.companyName = 'أدخل حرفين على الأقل.';
      if (form.industry.trim().length < 2) errors.industry = 'أدخل حرفين على الأقل.';
    }
    if (stepIndex === 1) {
      const whatsappConnected = CONNECTED_STATES.has(normalizeStatus(whatsapp.status));
      if (!whatsappConnected && !webChat.enabled) errors.general = 'اربط واتساب QR التجريبي أو فعّل دردشة الموقع للمتابعة.';
    }
    if (stepIndex === 2 && form.systemPrompt.trim().length < 20) {
      errors.systemPrompt = 'أضف 20 حرفًا على الأقل من إرشادات النشاط القابلة للتحقق.';
    }
    if (stepIndex === 3) {
      if (!form.tone) errors.general = 'اختر نبرة للمحادثة.';
      if (!form.language) errors.general = 'اختر لغة للرد.';
      if (form.welcomeMessage.trim().length < 5) errors.welcomeMessage = 'اكتب رسالة ترحيب من 5 أحرف على الأقل.';
    }
    setStepErrors(errors);
    return Object.keys(errors).length === 0;
  }, [form, webChat.enabled, whatsapp.status]);

  const handleNext = () => {
    if (!validateStep(currentStep)) return;
    setStepErrors({});
    setCurrentStep((step) => Math.min(STEPS.length - 1, step + 1));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleBack = () => {
    setStepErrors({});
    setActionError('');
    setCurrentStep((step) => Math.max(0, step - 1));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const copyLink = async (url) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setActionError('تعذر النسخ. حدّد الرابط وانسخه يدويًا.');
    }
  };

  const handleLaunch = async () => {
    const allValid = [0, 1, 2, 3].every((step) => {
      if (step === 0) return form.companyName.trim().length >= 2 && form.industry.trim().length >= 2;
      if (step === 1) return webChat.enabled || CONNECTED_STATES.has(normalizeStatus(whatsapp.status));
      if (step === 2) return form.systemPrompt.trim().length >= 20;
      return Boolean(form.tone && form.language && form.welcomeMessage.trim().length >= 5);
    });

    if (!allValid) {
      setActionError('هناك خطوة إعداد واحدة أو أكثر غير مكتملة. راجع شريط التقدم قبل التشغيل.');
      return;
    }

    setSaving(true);
    setActionError('');
    try {
      const response = await api.post('/whatsapp/settings/update', {
        company_name: form.companyName.trim(),
        industry: form.industry.trim(),
        system_prompt: form.systemPrompt.trim(),
        tone: form.tone,
        welcome_message: form.welcomeMessage.trim(),
        language: form.language,
        lead_collection: form.leadCollection,
      });
      if (!response.data?.success) throw new Error('settings_save_failed');
      navigate('/dashboard');
    } catch (error) {
      setActionError(getErrorMessage(error, 'تعذر على VELOR حفظ الإعداد بأمان. لم يتم استبداله بقيم تجريبية.'));
    } finally {
      setSaving(false);
    }
  };

  const step = STEPS[currentStep];
  const StepIcon = step.icon;
  const progress = ((currentStep + 1) / STEPS.length) * 100;

  if (loading) {
    return (
      <main className="velor-grid-bg flex min-h-screen items-center justify-center bg-velor-bg px-5" dir="rtl" lang="ar">
        <Card className="w-full max-w-sm p-7 text-center" glow>
          <VelorLogo className="justify-center" size={38} wordmarkClassName="text-lg" />
          <div className="mx-auto mt-7 h-8 w-8 animate-spin rounded-full border-2 border-velor-purple/20 border-t-velor-purple" />
          <p className="mt-4 text-sm font-semibold text-white">جاري تجهيز مساحة العمل</p>
          <p className="mt-1 text-xs text-velor-muted">جاري تحميل الإعدادات المحفوظة وحالة القنوات…</p>
        </Card>
      </main>
    );
  }

  return (
    <main className="velor-grid-bg min-h-screen bg-velor-bg text-white" dir="rtl" lang="ar">
      <div className="pointer-events-none fixed inset-0 overflow-hidden" aria-hidden="true">
        <div className="absolute -right-28 -top-40 h-[34rem] w-[34rem] rounded-full bg-velor-purple/[0.09] blur-[110px]" />
        <div className="absolute -bottom-44 -left-24 h-[30rem] w-[30rem] rounded-full bg-velor-blue/[0.055] blur-[120px]" />
      </div>

      <header className="relative z-10 border-b border-white/[0.06] bg-[#080910]/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
          <VelorLogo size={34} wordmarkClassName="text-base" />
          <div className="flex items-center gap-2">
            <Badge tone="purple">إعداد موجّه</Badge>
          </div>
        </div>
      </header>

      <div className="relative z-10 mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        {loadError && (
          <div className="mb-5 rounded-xl border border-velor-red/25 bg-velor-red/[0.07] p-4">
            <p className="text-sm font-semibold text-white">الإعداد المحفوظ غير متاح</p>
            <p className="mt-1 text-xs leading-5 text-velor-muted">{loadError}</p>
            <Button className="mt-3" variant="secondary" onClick={loadSetup}>
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              إعادة التحميل
            </Button>
          </div>
        )}

        {viewSummary ? (
          <OnboardingSummary
            form={form}
            webChat={webChat}
            whatsapp={whatsapp}
            catalogStatus={catalogStatus}
            sourceStatus={sourceStatus}
            onEdit={() => setViewSummary(false)}
            onGoToDashboard={() => navigate('/dashboard')}
          />
        ) : (
          <>
            <div className="overflow-x-auto pb-2 scrollbar-hide">
              <StepRail currentStep={currentStep} onSelect={setCurrentStep} hasCompletedAllSteps={hasCompletedAllSteps} />
            </div>
            <ProgressBar value={progress} className="mt-3" detail={`${currentStep + 1} من ${STEPS.length}`} />

            <div className="mt-7 grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">
              <Card className="animate-velor-in overflow-hidden p-0 shadow-velor-card">
                <div className="border-b border-white/[0.06] bg-gradient-to-r from-velor-purple/[0.09] via-transparent to-velor-blue/[0.055] px-5 py-5 sm:px-7 sm:py-6">
                  <div className="flex items-start gap-4">
                    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-velor-purple/25 bg-velor-purple/10 text-velor-violet shadow-[0_0_25px_rgba(155,92,255,0.12)]">
                      <StepIcon className="h-5 w-5" aria-hidden="true" />
                    </span>
                    <div className="min-w-0">
                      <p className="text-[10px] font-bold tracking-[0.17em] text-velor-purple">إعداد VELOR · {step.label}</p>
                      <h1 className="mt-1 text-xl font-semibold tracking-[-0.025em] text-white sm:text-2xl">{step.title}</h1>
                      <p className="mt-2 max-w-2xl text-xs leading-5 text-velor-muted sm:text-sm sm:leading-6">{step.prompt}</p>
                    </div>
                  </div>
                </div>

                <div className="p-5 sm:p-7">
                  {currentStep === 0 && <WorkspaceStep form={form} updateForm={updateForm} errors={stepErrors} />}
                  {currentStep === 1 && (
                    <ChannelStep
                      whatsapp={whatsapp}
                      webChat={webChat}
                      onStartWhatsApp={startWhatsApp}
                      onRefreshWhatsApp={() => refreshWhatsApp(false)}
                      onToggleWebChat={toggleWebChat}
                      onCopyLink={copyLink}
                      copied={copied}
                    />
                  )}
                  {currentStep === 2 && (
                    <KnowledgeStep
                      form={form}
                      updateForm={updateForm}
                      promptLimit={promptLimit}
                      catalogStatus={catalogStatus}
                      sourceStatus={sourceStatus}
                      errors={stepErrors}
                    />
                  )}
                  {currentStep === 3 && <VoiceStep form={form} updateForm={updateForm} errors={stepErrors} />}
                  {currentStep === 4 && (
                    <LaunchStep
                      form={form}
                      webChat={webChat}
                      whatsapp={whatsapp}
                      onCopyLink={copyLink}
                      copied={copied}
                    />
                  )}

                  {(stepErrors.general || actionError) && (
                    <div className="mt-5 rounded-xl border border-velor-red/25 bg-velor-red/[0.07] px-4 py-3 text-xs leading-5 text-[#ffb0bd]" role="alert">
                      {stepErrors.general || actionError}
                    </div>
                  )}

                  <div className="mt-7 flex flex-col-reverse gap-3 border-t border-white/[0.06] pt-5 sm:flex-row sm:items-center sm:justify-between">
                    <Button variant="ghost" onClick={handleBack} disabled={currentStep === 0 || saving}>
                      <ArrowRight className="h-4 w-4" aria-hidden="true" />
                      رجوع
                    </Button>
                    {currentStep < STEPS.length - 1 ? (
                      <Button onClick={handleNext} disabled={Boolean(loadError)}>
                        متابعة
                        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    ) : (
                      <Button onClick={handleLaunch} loading={saving} disabled={Boolean(loadError)}>
                        <Rocket className="h-4 w-4" aria-hidden="true" />
                        حفظ والدخول إلى مركز المتابعة
                      </Button>
                    )}
                  </div>
                </div>
              </Card>

              <SetupSummary
                form={form}
                currentStep={currentStep}
                webChat={webChat}
                whatsapp={whatsapp}
              />
            </div>
          </>
        )}

        <footer className="mt-6 flex flex-col gap-2 pb-4 text-[10px] leading-5 text-velor-muted sm:flex-row sm:items-center sm:justify-between">
          <span className="flex items-center gap-2"><ShieldCheck className="h-3.5 w-3.5 text-velor-green" />الإعدادات المدعومة فقط · من دون ادعاء قدرات غير موجودة</span>
          <span className="flex items-center gap-2"><Languages className="h-3.5 w-3.5" />يمكنك تعديل كل اختيار من الإعدادات</span>
        </footer>
      </div>
    </main>
  );
}
