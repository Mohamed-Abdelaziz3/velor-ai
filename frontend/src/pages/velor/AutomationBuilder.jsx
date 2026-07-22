import { useEffect, useState } from 'react';
import {
  BrainCircuit,
  ChevronLeft,
  CircleStop,
  GitBranch,
  GripVertical,
  Hand,
  LockKeyhole,
  MessageCircleMore,
  RotateCcw,
  Save,
  ShieldAlert,
  UserRoundCheck,
} from 'lucide-react';
import toast from 'react-hot-toast';
import api, { getBotKnowledge, saveBotKnowledge } from '../../services/api';
import { Badge, Button, Card, DataStateNotice, Field, PageHeader, PanelHeader, SegmentedControl, SelectField, TextArea, Toggle, cx } from '../../components/velor/ui';

const nodeDefinitions = [
  { id: 'trigger', label: 'وصول رسالة', type: 'بداية', description: 'واتساب QR التجريبي أو دردشة الموقع', icon: MessageCircleMore, tone: 'blue', supported: true },
  { id: 'intent', label: 'فهم نية العميل', type: 'قرار ذكي', description: 'المنتجات والأسئلة والاعتراضات وإشارات الشراء', icon: BrainCircuit, tone: 'purple', supported: true },
  { id: 'knowledge', label: 'تثبيت الرد على الحقائق', type: 'ضابط أمان', description: 'استخدام الكتالوج ومصادر المعرفة الموثقة', icon: LockKeyhole, tone: 'green', supported: true },
  { id: 'qualify', label: 'تأهيل العميل', type: 'إجراء', description: 'جمع التفاصيل التي يحتاجها فريقك', icon: UserRoundCheck, tone: 'purple', supported: true },
  { id: 'handoff', label: 'التحويل لموظف', type: 'أمان', description: 'إيقاف الرد الآلي عند تولّي أحد أعضاء الفريق', icon: Hand, tone: 'amber', supported: true },
  { id: 'followup', label: 'متابعة مجدولة', type: 'مخطط', description: 'عقد الجدولة غير متصل حتى الآن', icon: CircleStop, tone: 'neutral', supported: false },
];

const nodeTone = {
  blue: 'border-velor-blue/20 bg-velor-blue/[0.07] text-velor-blue',
  purple: 'border-velor-purple/20 bg-velor-purple/[0.07] text-velor-violet',
  green: 'border-velor-green/20 bg-velor-green/[0.07] text-velor-green',
  amber: 'border-velor-amber/20 bg-velor-amber/[0.07] text-velor-amber',
  neutral: 'border-white/[0.08] bg-white/[0.025] text-velor-muted',
};

const defaultSettings = {
  company_name: '',
  industry: '',
  tone: 'professional',
  welcome_message: 'Hi! I’m here to help you find the right option.',
  system_prompt: '',
  language: 'English',
  lead_collection: true,
  autoReply: false,
};

function BuilderNode({ node, selected, onSelect }) {
  const Icon = node.icon;
  return (
    <button type="button" onClick={() => onSelect(node.id)} className={cx('group relative flex w-full items-center gap-3 rounded-xl border p-3 text-right transition duration-200', selected ? `${nodeTone[node.tone]} shadow-[0_0_0_2px_rgba(155,92,255,.08)]` : 'border-white/[0.075] bg-[#11131d] hover:border-white/[0.14] hover:bg-[#151824]', !node.supported && 'opacity-65')} aria-pressed={selected}>
      <GripVertical className="h-4 w-4 shrink-0 text-velor-muted/50" aria-hidden="true" />
      <span className={cx('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border', nodeTone[node.tone])}><Icon className="h-4 w-4" /></span>
      <span className="min-w-0 flex-1"><span className="block text-[10px] font-bold text-velor-secondary">{node.type}</span><span className="mt-0.5 block truncate text-xs font-semibold text-white">{node.label}</span><span className="mt-0.5 block truncate text-[10px] text-velor-muted">{node.description}</span></span>
      <Badge tone={node.supported ? 'green' : 'neutral'} className="shrink-0 px-1.5 py-0.5 text-[8px]">{node.supported ? 'مدعوم' : 'مخطط'}</Badge>
    </button>
  );
}

export default function AutomationBuilder() {
  const [settings, setSettings] = useState(defaultSettings);
  const [savedSettings, setSavedSettings] = useState(defaultSettings);
  const [selectedNode, setSelectedNode] = useState('intent');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [published, setPublished] = useState(false);
  const [settingsAvailable, setSettingsAvailable] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [reloadKey, setReloadKey] = useState(0);

  const dirty = JSON.stringify(settings) !== JSON.stringify(savedSettings);
  const currentNode = nodeDefinitions.find((node) => node.id === selectedNode) || nodeDefinitions[0];

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setLoadError('');
    setSettingsAvailable(false);
    setPublished(false);
    Promise.all([
      getBotKnowledge(),
      api.get('/api/company/bot/auto-reply'),
    ]).then(([knowledgeResponse, autoReplyResponse]) => {
      if (!mounted) return;
      const knowledge = knowledgeResponse.data?.knowledge;
      const autoReplyEnabled = autoReplyResponse.data?.bot_auto_reply_enabled ?? knowledge?.bot_auto_reply_enabled;
      if (!knowledge || knowledgeResponse.data?.success === false || typeof autoReplyEnabled !== 'boolean') {
        throw new Error('behavior_configuration_incomplete');
      }
      const next = {
        ...defaultSettings,
        company_name: knowledge.company_name || '',
        industry: knowledge.industry || '',
        tone: knowledge.tone || 'professional',
        welcome_message: knowledge.welcome_message || defaultSettings.welcome_message,
        system_prompt: knowledge.system_prompt || '',
        language: knowledge.language || 'English',
        lead_collection: knowledge.lead_collection !== false,
        autoReply: autoReplyEnabled,
      };
      setSettings(next);
      setSavedSettings(next);
      setSettingsAvailable(true);
      setPublished(true);
    }).catch(() => {
      if (!mounted) return;
      setSettingsAvailable(false);
      setLoadError('تعذر على VELOR التحقق من إعدادات السلوك المحفوظة. تم تعطيل التعديل والنشر حتى تستجيب كل مصادر الإعدادات.');
      toast.error('تعذر تحميل إعدادات سلوك الذكاء الاصطناعي.');
    }).finally(() => mounted && setLoading(false));
    return () => { mounted = false; };
  }, [reloadKey]);

  const updateSetting = (key, value) => {
    setSettings((current) => ({ ...current, [key]: value }));
    setPublished(false);
  };

  const saveSettings = async () => {
    if (!settingsAvailable) return;
    setSaving(true);
    try {
      const knowledgePayload = {
        company_name: settings.company_name,
        industry: settings.industry,
        tone: settings.tone,
        welcome_message: settings.welcome_message,
        system_prompt: settings.system_prompt,
        language: settings.language,
        lead_collection: settings.lead_collection,
      };
      await Promise.all([
        saveBotKnowledge(knowledgePayload),
        api.post('/api/company/bot/auto-reply', { enabled: settings.autoReply }),
      ]);
      setSavedSettings(settings);
      setPublished(true);
      toast.success('تم نشر إعدادات سلوك الذكاء الاصطناعي');
    } catch (requestError) {
      console.error('Behavior settings save failed:', requestError);
      toast.error('تعذر حفظ هذه الإعدادات بأمان.');
    } finally {
      setSaving(false);
    }
  };

  const resetChanges = () => {
    setSettings(savedSettings);
    setPublished(true);
  };

  if (loading) return <div className="flex min-h-[calc(100vh-68px)] items-center justify-center"><span className="h-8 w-8 animate-spin rounded-full border-2 border-white/10 border-t-velor-purple" /></div>;

  if (!settingsAvailable || loadError) {
    return (
      <div className="mx-auto w-full max-w-[1100px] space-y-5 p-4 sm:p-6 xl:p-8" dir="rtl" lang="ar">
        <PageHeader
          eyebrow="إعداد سلوك الذكاء الاصطناعي"
          title="الإعدادات غير متاحة"
          description="لن يعرض VELOR قيمًا افتراضية باعتبارها سلوك المبيعات المحفوظ عندما يتعذر التحقق من مصادر الإعدادات."
          badge={<Badge tone="red">غير موثق</Badge>}
        />
        <DataStateNotice
          title="تعذر تحميل إعدادات سلوك الذكاء الاصطناعي"
          description={loadError || 'لم تعد مصادر الإعدادات باستجابة موثقة.'}
          tone="blue"
          action={<Button variant="secondary" onClick={() => setReloadKey((value) => value + 1)}><RotateCcw className="h-4 w-4" /> إعادة المحاولة</Button>}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-[1660px] space-y-5 p-4 sm:p-5 xl:p-7" dir="rtl" lang="ar">
      <PageHeader
        eyebrow="إعداد سلوك الذكاء الاصطناعي"
        title="وجّه طريقة بيع VELOR."
        description="واجهة مرئية للإعدادات المدعومة وضوابط الأمان. تظل الخطوات المخططة مقفلة بوضوح حتى تتوفر عقودها في الخادم."
        badge={<Badge tone={published ? 'green' : 'amber'} dot={published}>{published ? 'الإعدادات محفوظة' : 'تغييرات غير منشورة'}</Badge>}
        actions={(
          <>
            <Button variant="ghost" onClick={resetChanges} disabled={!dirty}><RotateCcw className="h-4 w-4" /> التراجع</Button>
            <Button onClick={saveSettings} loading={saving} disabled={(!dirty && published) || !settingsAvailable}><Save className="h-4 w-4" /> نشر التغييرات</Button>
          </>
        )}
      />

      <div className="grid min-h-[680px] gap-4 xl:grid-cols-[238px_minmax(500px,1fr)_330px]">
        <Card className="p-3">
          <PanelHeader eyebrow="الخطوات" title="سلوك المبيعات" description="اختر خطوة لمراجعة الإعداد المدعوم المرتبط بها." className="p-1" />
          <div className="mt-4 space-y-2">
            {nodeDefinitions.map((node) => (
              <button key={node.id} type="button" onClick={() => setSelectedNode(node.id)} className={cx('flex w-full items-center gap-2.5 rounded-xl border px-3 py-2.5 text-right transition', selectedNode === node.id ? 'border-velor-purple/20 bg-velor-purple/[0.07]' : 'border-transparent hover:border-white/[0.07] hover:bg-white/[0.025]')}>
                <span className={cx('flex h-8 w-8 items-center justify-center rounded-lg border', nodeTone[node.tone])}><node.icon className="h-3.5 w-3.5" /></span>
                <span className="min-w-0 flex-1"><span className="block truncate text-[11px] font-semibold text-white">{node.label}</span><span className="mt-0.5 block text-[10px] text-velor-muted">{node.type}</span></span>
                <ChevronLeft className="h-3.5 w-3.5 text-velor-muted" />
              </button>
            ))}
          </div>
          <div className="mt-4 rounded-xl border border-white/[0.07] bg-white/[0.025] p-3">
            <p className="flex items-center gap-2 text-[10px] font-semibold text-white"><ShieldAlert className="h-3.5 w-3.5 text-velor-amber" /> إعدادات مرتبطة بعقد حقيقي</p>
            <p className="mt-1.5 text-[10px] leading-4 text-velor-muted">يتم حفظ الحقول المدعومة فقط. شكل الخطوات لا يعني وجود محرك سير عمل غير محدود.</p>
          </div>
        </Card>

        <Card className="relative min-w-0 overflow-hidden bg-[#0b0d15] p-3 sm:p-5 velor-grid-bg">
          <div className="absolute left-5 top-5 z-10 flex items-center gap-2 rounded-xl border border-white/[0.08] bg-[#11131e]/92 px-3 py-2 backdrop-blur-xl">
            <GitBranch className="h-3.5 w-3.5 text-velor-purple" /><span className="text-[10px] font-semibold text-velor-secondary">مسار المبيعات الأساسي</span>
          </div>
          <div className="absolute right-5 top-5 z-10 hidden items-center gap-2 sm:flex">
            <Badge tone="green" dot>تم تحميل إعدادات الخادم</Badge><Badge tone="neutral">إعدادات الإصدار 1</Badge>
          </div>

          <div className="relative z-[1] flex min-h-[620px] items-center justify-center py-16">
            <svg className="pointer-events-none absolute inset-0 hidden h-full w-full xl:block" viewBox="0 0 1000 640" preserveAspectRatio="none" aria-hidden="true">
              <path d="M160 108 C 250 108, 235 210, 330 210 S 470 210, 520 210 S 680 210, 735 210" fill="none" stroke="rgba(155,92,255,.3)" strokeWidth="2" strokeDasharray="7 9" className="animate-flow-dash" />
              <path d="M520 210 C 545 325, 650 350, 735 420" fill="none" stroke="rgba(245,181,70,.25)" strokeWidth="2" strokeDasharray="7 9" />
              <path d="M735 210 C 850 210, 820 320, 850 320" fill="none" stroke="rgba(49,214,160,.22)" strokeWidth="2" strokeDasharray="7 9" />
            </svg>

            <div className="grid w-full max-w-[760px] gap-3 xl:grid-cols-2">
              {nodeDefinitions.map((node, index) => (
                <div key={node.id} className={cx(index === 0 && 'xl:col-span-2 xl:mx-auto xl:w-[46%]', index === 3 && 'xl:col-start-1', index === 4 && 'xl:col-start-2', index === 5 && 'xl:col-span-2 xl:mx-auto xl:w-[46%]')}>
                  <BuilderNode node={node} selected={selectedNode === node.id} onSelect={setSelectedNode} />
                </div>
              ))}
            </div>
          </div>
        </Card>

        <Card className="h-fit p-4">
          <div className="flex items-start justify-between gap-3 border-b border-white/[0.07] pb-4">
            <div><p className="text-[11px] font-bold text-velor-purple-hi" style={{ color: 'var(--velor-purple-hi)' }}>تفاصيل الخطوة</p><h2 className="mt-1 text-sm font-semibold text-white">{currentNode.label}</h2><p className="mt-1 text-[10px] leading-4 text-velor-muted">{currentNode.description}</p></div>
            <span className={cx('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border', nodeTone[currentNode.tone])}><currentNode.icon className="h-4 w-4" /></span>
          </div>

          <div className="mt-4 space-y-5">
            <Toggle checked={settings.autoReply} onChange={(value) => updateSetting('autoReply', value)} label="رد VELOR التلقائي" description="اسمح للذكاء الاصطناعي بالرد حتى يتولى أحد أعضاء الفريق المحادثة." />
            <Toggle checked={settings.lead_collection} onChange={(value) => updateSetting('lead_collection', value)} label="تأهيل العميل" description="اجمع تفاصيل العميل المهمة أثناء محادثة المبيعات." />

            <div>
              <p className="mb-2 text-xs font-semibold text-velor-secondary">نبرة الرد</p>
              <SegmentedControl value={settings.tone} onChange={(value) => updateSetting('tone', value)} options={[{ value: 'professional', label: 'دقيقة' }, { value: 'friendly', label: 'ودودة' }, { value: 'concise', label: 'مختصرة' }]} className="w-full [&>button]:flex-1 [&>button]:px-1" />
            </div>

            <SelectField label="لغة الرد" value={settings.language} onChange={(event) => updateSetting('language', event.target.value)}>
              <option value="English">الإنجليزية</option><option value="Arabic">العربية</option><option value="Bilingual">العربية والإنجليزية</option>
            </SelectField>

            <Field label="رسالة الترحيب" value={settings.welcome_message} onChange={(event) => updateSetting('welcome_message', event.target.value)} placeholder="اكتب بداية المحادثة…" />

            <TextArea label="تعليمات وضوابط النشاط" hint={`${settings.system_prompt.length}/12000`} value={settings.system_prompt} onChange={(event) => updateSetting('system_prompt', event.target.value)} placeholder="حدّد ما يجب أن يعرفه VELOR وما يجب تجنبه أو تحويله لموظف…" maxLength={12000} className="min-h-[130px]" />

            {!currentNode.supported && (
              <div className="rounded-xl border border-velor-amber/20 bg-velor-amber/[0.055] p-3">
                <p className="flex items-center gap-2 text-[10px] font-semibold text-[#f7d597]"><LockKeyhole className="h-3.5 w-3.5" /> خطوة مخططة</p>
                <p className="mt-1.5 text-[9px] leading-4 text-velor-muted">المتابعات المجدولة تحتاج خدمة جدولة موثوقة وسياسة محاولات وسجل تدقيق قبل نشرها.</p>
              </div>
            )}
          </div>
        </Card>
      </div>

    </div>
  );
}
