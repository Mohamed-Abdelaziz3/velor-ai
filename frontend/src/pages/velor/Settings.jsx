import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  BellRing,
  BookOpenText,
  Building2,
  Check,
  Copy,
  ExternalLink,
  KeyRound,
  Link2,
  LockKeyhole,
  Mail,
  MessageCircleMore,
  PackageSearch,
  RefreshCw,
  Save,
  Settings2,
  ShieldCheck,
  Smartphone,
  UserRound,
  X,
} from 'lucide-react';
import toast from 'react-hot-toast';
import api, { getAlertSettings, getBotKnowledge, rotateApiKey, saveAlertSettings, saveBotKnowledge } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { Badge, Button, Card, Field, PageHeader, PanelHeader, SelectField, Toggle, cx } from '../../components/velor/ui';
import { CatalogEditor } from '../dashboard/settings/CatalogEditor';
import { KnowledgeSourcesPanel } from '../dashboard/settings/KnowledgeSourcesPanel';
import {
  allowedCatalogFile,
  allowedKnowledgeFile,
  createProduct,
  normalizeProductsData,
  serializeProducts,
  validateProducts,
} from '../dashboard/settings/settingsUi';

const tabs = [
  { id: 'workspace', label: 'مساحة العمل', icon: Building2 },
  { id: 'knowledge', label: 'المعرفة والكتالوج', icon: BookOpenText },
  { id: 'channels', label: 'القنوات', icon: Link2 },
  { id: 'notifications', label: 'الإشعارات', icon: BellRing },
  { id: 'security', label: 'الأمان وواجهة API', icon: ShieldCheck },
];

const defaultKnowledge = {
  company_name: '', industry: '', tone: 'professional', welcome_message: '', system_prompt: '', language: 'English', lead_collection: true,
};

const errorDetail = (error, fallback) => {
  const detail = error?.response?.data?.detail || error?.response?.data?.message;
  if (typeof detail === 'string' && /[\u0600-\u06FF]/.test(detail)) return detail;
  if (detail?.message && /[\u0600-\u06FF]/.test(detail.message)) return detail.message;
  return fallback;
};

const planLabels = {
  free: 'المجانية',
  starter: 'الأساسية',
  pro: 'الاحترافية',
  business: 'الأعمال',
  enterprise: 'المؤسسات',
};

const roleLabels = {
  tenant: 'مدير مساحة العمل',
  admin: 'مدير',
  owner: 'المالك',
};

const displayPlan = (value) => planLabels[String(value || '').toLowerCase()] || (value ? String(value) : 'غير معروف');
const displayRole = (value) => roleLabels[String(value || '').toLowerCase()] || 'مدير مساحة العمل';

export default function Settings() {
  const navigate = useNavigate();
  const { plan } = useAuth();
  const [activeTab, setActiveTab] = useState('workspace');
  const [profile, setProfile] = useState(null);
  const [knowledge, setKnowledge] = useState(defaultKnowledge);
  const [savedKnowledge, setSavedKnowledge] = useState(null);
  const [alerts, setAlerts] = useState({ is_alerts_enabled: false, alert_whatsapp_number: '' });
  const [alertsKnown, setAlertsKnown] = useState(false);
  const [webChat, setWebChat] = useState({ enabled: false, slug: '' });
  const [webChatKnown, setWebChatKnown] = useState(false);
  const [whatsApp, setWhatsApp] = useState('unknown');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [rotateOpen, setRotateOpen] = useState(false);
  const [newApiKey, setNewApiKey] = useState('');
  const [copied, setCopied] = useState(false);
  const [loadVersion, setLoadVersion] = useState(0);
  const [settingsLoadError, setSettingsLoadError] = useState('');

  const [products, setProducts] = useState([]);
  const [savedCatalog, setSavedCatalog] = useState(null);
  const [catalogStatus, setCatalogStatus] = useState(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState('');
  const [catalogSaving, setCatalogSaving] = useState(false);
  const [catalogImportFile, setCatalogImportFile] = useState(null);
  const [catalogImportPreview, setCatalogImportPreview] = useState(null);
  const [catalogImportError, setCatalogImportError] = useState('');
  const [catalogImporting, setCatalogImporting] = useState(false);
  const [catalogCommitting, setCatalogCommitting] = useState(false);

  const [sources, setSources] = useState([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [sourcesError, setSourcesError] = useState('');
  const [sourceUploading, setSourceUploading] = useState(false);
  const [busySourceId, setBusySourceId] = useState(null);

  const dirty = savedKnowledge && JSON.stringify(knowledge) !== JSON.stringify(savedKnowledge);
  const currentPlan = profile?.plan || plan || null;
  const catalogValidation = useMemo(() => validateProducts(products), [products]);
  const currentCatalog = useMemo(() => serializeProducts(products), [products]);
  const catalogDirty = savedCatalog !== null && currentCatalog !== savedCatalog;

  useEffect(() => {
    let mounted = true;
    setCatalogLoading(true);
    setSourcesLoading(true);
    setSettingsLoadError('');
    setAlertsKnown(false);
    setWebChatKnown(false);
    setCatalogError('');
    setSourcesError('');
    Promise.allSettled([
      api.get('/me'),
      getBotKnowledge(),
      getAlertSettings(),
      api.get('/api/company/bot/web-chat'),
      api.get('/whatsapp/status'),
      api.get('/api/v1/knowledge/sources'),
    ]).then(([meResult, knowledgeResult, alertsResult, webChatResult, whatsAppResult, sourcesResult]) => {
      if (!mounted) return;
      if (meResult.status === 'fulfilled') {
        setProfile(meResult.value.data);
      } else {
        setSettingsLoadError('تعذر التحقق من هوية الحساب من الخادم. أعد المحاولة قبل تغيير إعدادات مساحة العمل.');
      }

      if (knowledgeResult.status === 'fulfilled' && knowledgeResult.value.data?.success !== false) {
        const nextKnowledge = { ...defaultKnowledge, ...(knowledgeResult.value.data?.knowledge || {}) };
        const hydratedProducts = normalizeProductsData(nextKnowledge.products_data);
        setKnowledge(nextKnowledge);
        setSavedKnowledge(nextKnowledge);
        setProducts(hydratedProducts);
        setSavedCatalog(serializeProducts(hydratedProducts));
        setCatalogStatus(nextKnowledge.catalog_status || null);
      } else {
        const message = 'تعذر تحميل معرفة مساحة العمل والكتالوج. لن يتم عرض كتالوج افتراضي بدلًا منهما.';
        setSettingsLoadError((current) => current || message);
        setCatalogError(message);
      }
      setCatalogLoading(false);

      if (alertsResult.status === 'fulfilled' && alertsResult.value.data?.settings && typeof alertsResult.value.data.settings.is_alerts_enabled === 'boolean') {
        setAlerts((current) => ({ ...current, ...alertsResult.value.data.settings }));
        setAlertsKnown(true);
      } else {
        setAlertsKnown(false);
        setSettingsLoadError((current) => current || 'تعذر التحقق من إعدادات التنبيهات. ستظهر حالتها كغير معروفة.');
      }
      if (webChatResult.status === 'fulfilled' && typeof webChatResult.value.data?.is_web_chat_enabled === 'boolean') {
        setWebChat({ enabled: webChatResult.value.data.is_web_chat_enabled, slug: webChatResult.value.data?.public_chat_slug || '' });
        setWebChatKnown(true);
      } else {
        setWebChatKnown(false);
        setSettingsLoadError((current) => current || 'تعذر التحقق من حالة دردشة الموقع المستضافة. ستظهر حالتها كغير معروفة.');
      }
      if (whatsAppResult.status === 'fulfilled') {
        const rawStatus = String(whatsAppResult.value.data?.status || whatsAppResult.value.data?.connection || '').toLowerCase();
        setWhatsApp(['connected', 'open', 'ready'].includes(rawStatus) ? 'connected' : rawStatus ? 'disconnected' : 'unknown');
      }
      if (sourcesResult.status === 'fulfilled') {
        setSources(sourcesResult.value.data?.sources || []);
      } else {
        setSourcesError('تعذر تحميل حالة مصادر المعرفة من الخادم.');
      }
      setSourcesLoading(false);
    }).finally(() => mounted && setLoading(false));
    return () => { mounted = false; };
  }, [loadVersion]);

  const loadSources = useCallback(async () => {
    setSourcesLoading(true);
    setSourcesError('');
    try {
      const response = await api.get('/api/v1/knowledge/sources');
      setSources(response.data?.sources || []);
    } catch (requestError) {
      setSourcesError(errorDetail(requestError, 'تعذر تحميل حالة مصادر المعرفة من الخادم.'));
    } finally {
      setSourcesLoading(false);
    }
  }, []);

  const refreshCatalog = useCallback(async () => {
    setCatalogLoading(true);
    setCatalogError('');
    try {
      const response = await getBotKnowledge();
      if (response.data?.success === false) throw new Error('catalog_refresh_failed');
      const serverKnowledge = response.data?.knowledge || {};
      const hydratedProducts = normalizeProductsData(serverKnowledge.products_data);
      const serialized = serializeProducts(hydratedProducts);
      setProducts(hydratedProducts);
      setSavedCatalog(serialized);
      setCatalogStatus(serverKnowledge.catalog_status || null);
      setKnowledge((current) => ({ ...current, products_data: serverKnowledge.products_data, catalog_status: serverKnowledge.catalog_status }));
      setSavedKnowledge((current) => current ? ({ ...current, products_data: serverKnowledge.products_data, catalog_status: serverKnowledge.catalog_status }) : current);
    } catch (requestError) {
      setCatalogError(errorDetail(requestError, 'تعذر تحديث الكتالوج المحفوظ. لن يتم عرض سجلات افتراضية بدلًا منه.'));
    } finally {
      setCatalogLoading(false);
    }
  }, []);

  const updateProduct = (id, field, value) => {
    setProducts((current) => current.map((product) => product.id === id ? { ...product, [field]: value } : product));
    setCatalogImportFile(null);
    setCatalogImportPreview(null);
  };

  const addProduct = () => {
    setProducts((current) => [...current, createProduct()]);
    setCatalogImportFile(null);
    setCatalogImportPreview(null);
  };
  const removeProduct = (id) => {
    setProducts((current) => current.filter((product) => product.id !== id));
    setCatalogImportFile(null);
    setCatalogImportPreview(null);
  };

  const previewCatalogImport = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (catalogDirty) {
      setCatalogImportError('احفظ التعديلات اليدوية أو تجاهلها قبل الاستيراد. يدمج الخادم الملف مع آخر كتالوج محفوظ.');
      return;
    }
    const result = allowedCatalogFile(file);
    if (!result.valid) {
      setCatalogImportFile(null);
      setCatalogImportPreview(null);
      setCatalogImportError(result.message);
      return;
    }
    setCatalogImporting(true);
    setCatalogImportError('');
    setCatalogImportPreview(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await api.post('/api/v1/catalog/import?commit=false', formData);
      const serverPreview = response.data?.preview;
      if (!serverPreview) throw new Error('catalog_preview_missing');
      setCatalogImportFile(file);
      setCatalogImportPreview({
        ...serverPreview,
        fileName: file.name,
        canCommit: Boolean(response.data?.success && serverPreview.records?.length),
      });
    } catch (requestError) {
      setCatalogImportFile(null);
      setCatalogImportError(errorDetail(requestError, 'تعذر التحقق من ملف الكتالوج. راجع صيغته وعناوين الأعمدة ثم حاول مرة أخرى.'));
    } finally {
      setCatalogImporting(false);
    }
  };

  const commitCatalogImport = async () => {
    if (!catalogImportFile || !catalogImportPreview?.canCommit || catalogDirty) return;
    setCatalogCommitting(true);
    setCatalogImportError('');
    try {
      const formData = new FormData();
      formData.append('file', catalogImportFile);
      const response = await api.post('/api/v1/catalog/import?commit=true', formData);
      if (!response.data?.committed) throw new Error('catalog_commit_failed');
      toast.success(`تم حفظ الكتالوج (${response.data?.merge?.effective_records ?? 'العدد غير متاح'} سجل فعّال).`);
      setCatalogImportFile(null);
      setCatalogImportPreview(null);
      await refreshCatalog();
    } catch (requestError) {
      setCatalogImportError(errorDetail(requestError, 'لم يتم حفظ الكتالوج. بقيت السجلات المحفوظة الحالية دون استبدال.'));
    } finally {
      setCatalogCommitting(false);
    }
  };

  const saveCatalog = async () => {
    if (!catalogValidation.isValid) {
      toast.error('أصلح أخطاء التحقق من الكتالوج قبل الحفظ.');
      return;
    }
    setCatalogSaving(true);
    setCatalogError('');
    try {
      const response = await saveBotKnowledge({ products_data: currentCatalog });
      if (response.data?.success === false) throw new Error('catalog_save_failed');
      setSavedCatalog(currentCatalog);
      setKnowledge((current) => ({ ...current, products_data: currentCatalog }));
      setSavedKnowledge((current) => current ? ({ ...current, products_data: currentCatalog }) : current);
      toast.success(products.length ? 'تم حفظ الكتالوج.' : 'تم إفراغ الكتالوج. سيتعامل VELOR مع حقائق المنتجات باعتبارها غير متاحة.');
      await refreshCatalog();
    } catch (requestError) {
      setCatalogError(errorDetail(requestError, 'تعذر حفظ الكتالوج. ظل آخر إصدار مؤكد على الخادم دون تغيير.'));
    } finally {
      setCatalogSaving(false);
    }
  };

  const discardCatalogChanges = () => {
    if (savedCatalog === null) return;
    setProducts(normalizeProductsData(savedCatalog));
    setCatalogImportError('');
  };

  const uploadKnowledge = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    const result = allowedKnowledgeFile(file);
    if (!result.valid) {
      toast.error(result.message);
      return;
    }
    setSourceUploading(true);
    setSourcesError('');
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await api.post('/api/v1/knowledge/upload', formData);
      if (!response.data?.source) throw new Error('knowledge_source_missing');
      setSources((current) => [response.data.source, ...current.filter((source) => source.id !== response.data.source.id)]);
      toast.success('تمت معالجة المصدر وإضافته إلى المعرفة النشطة.');
    } catch (requestError) {
      toast.error(errorDetail(requestError, 'تعذر رفع المصدر أو معالجته.'));
    } finally {
      setSourceUploading(false);
    }
  };

  const updateSource = async (source, action) => {
    if (action === 'delete' && !window.confirm(`هل تريد حذف «${source.source_name}» من المعرفة النشطة؟`)) return;
    setBusySourceId(source.id);
    setSourcesError('');
    try {
      let response;
      if (action === 'toggle') response = await api.patch(`/api/v1/knowledge/sources/${source.id}`, { active: !source.active });
      if (action === 'reprocess') response = await api.post(`/api/v1/knowledge/sources/${source.id}/reprocess`);
      if (action === 'delete') response = await api.delete(`/api/v1/knowledge/sources/${source.id}`);
      if (action === 'delete') setSources((current) => current.filter((item) => item.id !== source.id));
      else if (response?.data?.source) setSources((current) => current.map((item) => item.id === source.id ? response.data.source : item));
      toast.success(action === 'delete' ? 'تم حذف مصدر المعرفة.' : 'تم تحديث مصدر المعرفة.');
    } catch (requestError) {
      setSourcesError(errorDetail(requestError, 'تعذر تحديث مصدر المعرفة.'));
    } finally {
      setBusySourceId(null);
    }
  };

  const saveWorkspace = async () => {
    setSaving(true);
    try {
      await saveBotKnowledge({
        company_name: knowledge.company_name,
        industry: knowledge.industry,
        tone: knowledge.tone,
        welcome_message: knowledge.welcome_message,
        system_prompt: knowledge.system_prompt,
        language: knowledge.language,
        lead_collection: knowledge.lead_collection,
      });
      setSavedKnowledge(knowledge);
      setProfile((current) => ({ ...current, company_name: knowledge.company_name || current?.company_name }));
      toast.success('تم حفظ إعدادات مساحة العمل');
    } catch (requestError) {
      console.error('Workspace settings save failed:', requestError);
      toast.error('تعذر حفظ إعدادات مساحة العمل بأمان.');
    } finally {
      setSaving(false);
    }
  };

  const toggleWebChat = async (enabled) => {
    if (!webChatKnown) {
      toast.error('حالة دردشة الموقع غير معروفة. أعد تحميل الإعدادات قبل تغييرها.');
      return;
    }
    const previous = webChat;
    setWebChat((current) => ({ ...current, enabled }));
    try {
      const { data } = await api.post('/api/company/bot/web-chat', { enabled });
      if (typeof data?.is_web_chat_enabled !== 'boolean') throw new Error('web_chat_status_missing');
      setWebChat({ enabled: data.is_web_chat_enabled, slug: data.public_chat_slug || previous.slug });
      setWebChatKnown(true);
      toast.success(enabled ? 'تم تفعيل دردشة الموقع المستضافة' : 'تم تعطيل دردشة الموقع المستضافة');
    } catch {
      setWebChat(previous);
      toast.error('تعذر تغيير حالة دردشة الموقع.');
    }
  };

  const saveNotifications = async () => {
    if (!alertsKnown) {
      toast.error('إعدادات التنبيهات غير معروفة. أعد تحميل الإعدادات قبل تغييرها.');
      return;
    }
    setSaving(true);
    try {
      await saveAlertSettings(alerts);
      toast.success('تم حفظ إعدادات التنبيهات');
    } catch (requestError) {
      console.error('Alert settings save failed:', requestError);
      toast.error('تعذر حفظ إعدادات التنبيهات.');
    } finally {
      setSaving(false);
    }
  };

  const confirmRotation = async () => {
    setRotating(true);
    try {
      const { data } = await rotateApiKey();
      const rotatedKey = data.api_key || data.new_api_key;
      if (!rotatedKey) throw new Error('rotated_api_key_missing');
      setNewApiKey(rotatedKey);
      toast.success('تم تدوير مفتاح API. احفظ القيمة الجديدة الآن.');
    } catch (requestError) {
      console.error('API key rotation failed:', requestError);
      toast.error('تعذر تدوير مفتاح API.');
      setRotateOpen(false);
    } finally {
      setRotating(false);
    }
  };

  const copyApiKey = async () => {
    if (!newApiKey) return;
    await navigator.clipboard.writeText(newApiKey);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  if (loading) return <div className="flex min-h-[calc(100vh-68px)] items-center justify-center"><span className="h-8 w-8 animate-spin rounded-full border-2 border-white/10 border-t-velor-purple" /></div>;

  return (
    <div className="mx-auto w-full max-w-[1380px] space-y-6 p-4 sm:p-5 xl:p-7" dir="rtl" lang="ar">
      <PageHeader
        eyebrow="إدارة مساحة العمل"
        title="الإعدادات"
        description="أدر هوية النشاط والكتالوج والمعرفة الموثوقة والقنوات المدعومة والتنبيهات وبيانات الوصول."
        actions={<Link to="/billing" className="velor-button-secondary">الباقة والاستخدام <ExternalLink className="h-4 w-4" /></Link>}
      />

      {settingsLoadError && <Card className="flex flex-col justify-between gap-3 border-rose-400/20 bg-rose-500/[0.06] p-4 sm:flex-row sm:items-center" role="alert"><div><p className="text-xs font-semibold text-rose-100">بعض الإعدادات المرتبطة بالخادم غير متاحة</p><p className="mt-1 text-[11px] leading-5 text-velor-muted">{settingsLoadError}</p></div><Button variant="secondary" onClick={() => { setLoading(true); setLoadVersion((version) => version + 1); }}><RefreshCw className="h-3.5 w-3.5" /> إعادة المحاولة</Button></Card>}

      <div className="grid gap-5 lg:grid-cols-[230px_minmax(0,1fr)]">
        <Card as="nav" className="h-fit p-2 lg:sticky lg:top-4" aria-label="أقسام الإعدادات">
          <div className="space-y-1">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <button key={tab.id} type="button" onClick={() => setActiveTab(tab.id)} className={cx('flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-right text-xs font-semibold transition', activeTab === tab.id ? 'bg-velor-purple/[0.09] text-white' : 'text-velor-muted hover:bg-white/[0.035] hover:text-velor-secondary')} aria-current={activeTab === tab.id ? 'page' : undefined}>
                  <Icon className={cx('h-4 w-4', activeTab === tab.id ? 'text-velor-purple' : 'text-velor-muted')} />{tab.label}
                </button>
              );
            })}
          </div>
          <div className="mx-2 my-3 h-px bg-white/[0.07]" />
          <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-3">
            <p className="text-[10px] font-bold text-velor-secondary">الباقة</p>
            <div className="mt-2 flex items-center justify-between"><span className="text-xs font-semibold text-white">{displayPlan(currentPlan)}</span><Badge tone={currentPlan ? 'green' : 'neutral'}>{currentPlan ? 'مُبلغ من الخادم' : 'غير معروف'}</Badge></div>
            <button type="button" onClick={() => navigate('/billing')} className="mt-3 text-[10px] font-semibold text-[#d8c1ff] hover:text-white">عرض الاستخدام ←</button>
          </div>
        </Card>

        <div className="min-w-0 space-y-5">
          {activeTab === 'workspace' && (
            <>
              <Card className="p-5 sm:p-6">
                <PanelHeader eyebrow="هوية النشاط" title="ملف مساحة العمل" description="تُستخدم هذه الهوية في لوحة التحكم وإعداد سلوك الذكاء الاصطناعي." action={dirty ? <Badge tone="amber">تغييرات غير محفوظة</Badge> : <Badge tone="green">محفوظ</Badge>} />
                <div className="mt-6 grid gap-5 md:grid-cols-2">
                  <Field label="اسم النشاط" icon={Building2} value={knowledge.company_name} onChange={(event) => setKnowledge((current) => ({ ...current, company_name: event.target.value }))} placeholder="اسم نشاطك" />
                  <Field label="بريد الحساب" icon={Mail} value={profile?.email || ''} disabled hint="تتم إدارته من حسابك" />
                  <Field label="مجال النشاط" icon={Settings2} value={knowledge.industry} onChange={(event) => setKnowledge((current) => ({ ...current, industry: event.target.value }))} placeholder="مثال: تجارة الأثاث المكتبي" />
                  <SelectField label="لغة الرد الافتراضية" value={knowledge.language} onChange={(event) => setKnowledge((current) => ({ ...current, language: event.target.value }))}><option value="English">الإنجليزية</option><option value="Arabic">العربية</option><option value="Bilingual">العربية والإنجليزية</option></SelectField>
                </div>
                <div className="mt-6 flex justify-end"><Button onClick={saveWorkspace} loading={saving} disabled={!dirty}><Save className="h-4 w-4" /> حفظ مساحة العمل</Button></div>
              </Card>

              <Card className="p-5 sm:p-6">
                <PanelHeader eyebrow="الوصول" title="مالك مساحة العمل" description="يتم جلب الدور وهوية مساحة العمل من جلسة الدخول الموثقة." />
                <div className="mt-5 flex flex-col gap-4 rounded-xl border border-white/[0.07] bg-white/[0.025] p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-velor-purple/10 text-velor-violet"><UserRound className="h-4 w-4" /></span><div><p className="text-xs font-semibold text-white">{profile?.email || 'مالك مساحة العمل'}</p><p className="mt-0.5 text-[10px] text-velor-muted">{displayRole(profile?.role)} · {profile?.company_id}</p></div></div>
                  <Badge tone="green"><LockKeyhole className="h-3 w-3" /> معزول داخل مساحة العمل</Badge>
                </div>
              </Card>
            </>
          )}

          {activeTab === 'knowledge' && (
              <>
                <Card className="p-5 sm:p-6">
                  <PanelHeader
                    eyebrow="حقائق تجارية موثوقة"
                    title="الكتالوج"
                    description="عدّل حقائق المنتجات المحفوظة يدويًا أو تحقّق من ملف منظّم وادمجه. التعديلات غير المحفوظة لا تُعرض كبيانات حية."
                    action={catalogDirty ? <Badge tone="amber">تعديلات غير محفوظة</Badge> : savedCatalog !== null ? <Badge tone="green">تم تحميل إصدار الخادم</Badge> : <Badge tone="neutral">غير متاح</Badge>}
                  />
                  {catalogStatus ? <div className="mt-5 flex flex-wrap gap-2"><Badge tone="neutral">سجلات الخادم المقروءة: {catalogStatus.total_records ?? 'غير مُبلغ'}</Badge><Badge tone="purple">سجلات لها سعر محفوظ: {catalogStatus.priced_records ?? 'غير مُبلغ'}</Badge></div> : <p className="mt-5 text-[11px] text-velor-muted">لم يرسل الخادم تشخيصات الكتالوج.</p>}
                  {catalogError && <p className="mt-5 rounded-xl border border-rose-400/20 bg-rose-500/10 p-3 text-xs leading-5 text-rose-100" role="alert">{catalogError}</p>}
                  {catalogLoading ? <div className="flex min-h-48 items-center justify-center" role="status" aria-label="جاري تحميل الكتالوج"><RefreshCw className="h-5 w-5 animate-spin text-velor-purple" /></div> : savedCatalog === null ? <div className="mt-5 rounded-2xl border border-dashed border-white/10 p-6 text-center"><PackageSearch className="mx-auto h-6 w-6 text-velor-muted" /><p className="mt-3 text-xs font-semibold text-white">لا يمكن عرض كتالوج موثوق الآن</p><p className="mt-1 text-[11px] text-velor-muted">أعد طلب الإعدادات لتحميل إصدار الخادم الحالي.</p></div> : <div className="mt-6"><CatalogEditor products={products} validation={catalogValidation} onAdd={addProduct} onRemove={removeProduct} onChange={updateProduct} onImportSelect={previewCatalogImport} onImportCommit={commitCatalogImport} importPreview={catalogImportPreview} importError={catalogImportError} importing={catalogImporting} committing={catalogCommitting} importDisabled={catalogDirty} /><div className="mt-6 flex flex-col justify-end gap-2 border-t border-white/[0.07] pt-5 sm:flex-row"><Button variant="secondary" onClick={discardCatalogChanges} disabled={!catalogDirty || catalogSaving}>تجاهل التعديلات</Button><Button onClick={saveCatalog} loading={catalogSaving} disabled={!catalogDirty || !catalogValidation.isValid}><Save className="h-4 w-4" /> حفظ الكتالوج</Button></div></div>}
                </Card>

                <Card className="p-5 sm:p-6">
                  <KnowledgeSourcesPanel sources={sources} loading={sourcesLoading} error={sourcesError} uploading={sourceUploading} busySourceId={busySourceId} onUpload={uploadKnowledge} onToggle={(source) => updateSource(source, 'toggle')} onReprocess={(source) => updateSource(source, 'reprocess')} onDelete={(source) => updateSource(source, 'delete')} onRetry={loadSources} />
                </Card>
              </>
          )}

          {activeTab === 'channels' && (
            <Card className="p-5 sm:p-6">
              <PanelHeader eyebrow="القنوات المتصلة" title="قنوات المبيعات" description="يدعم VELOR حاليًا صفحة دردشة موقع مستضافة واتصال واتساب QR تجريبي. ربط Cloud API الرسمي وودجت التضمين غير متاحين كخدمات حية." action={<Button variant="secondary" onClick={() => navigate('/onboarding')}>فتح الإعداد الموجّه <ExternalLink className="h-3.5 w-3.5" /></Button>} />
              <div className="mt-6 grid gap-4 md:grid-cols-2">
                <Card className="p-5" interactive>
                  <div className="flex items-start justify-between gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-xl border border-velor-green/15 bg-velor-green/10 text-velor-green"><Smartphone className="h-5 w-5" /></span><Badge tone={whatsApp === 'connected' ? 'green' : whatsApp === 'disconnected' ? 'amber' : 'neutral'} dot={whatsApp === 'connected'}>{whatsApp === 'connected' ? 'متصل' : whatsApp === 'disconnected' ? 'غير متصل' : 'غير معروف'}</Badge></div>
                  <h3 className="mt-5 text-sm font-semibold text-white">واتساب QR التجريبي</h3>
                  <p className="mt-2 text-xs leading-5 text-velor-muted">جلسة QR مستضافة ذاتيًا عبر البوابة الحالية. هذا ليس ربط WhatsApp Business Cloud API الرسمي.</p>
                  <Button variant="secondary" onClick={() => navigate('/onboarding')} className="mt-5 w-full">إدارة الاتصال <ChevronRightIcon /></Button>
                </Card>

                <Card className="p-5" interactive>
                  <div className="flex items-start justify-between gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-xl border border-velor-blue/15 bg-velor-blue/10 text-velor-blue"><MessageCircleMore className="h-5 w-5" /></span><Badge tone={!webChatKnown ? 'neutral' : webChat.enabled ? 'green' : 'neutral'} dot={webChatKnown && webChat.enabled}>{!webChatKnown ? 'غير معروف' : webChat.enabled ? 'مفعّلة' : 'معطّلة'}</Badge></div>
                  <h3 className="mt-5 text-sm font-semibold text-white">دردشة الموقع المستضافة</h3>
                  <p className="mt-2 text-xs leading-5 text-velor-muted">صفحة دردشة عامة يستضيفها VELOR. لم يتم ربط ودجت تضمين أو عقد تحقق من النطاق حتى الآن.</p>
                  <div className="mt-5 border-t border-white/[0.07] pt-4"><Toggle checked={webChatKnown && webChat.enabled} onChange={toggleWebChat} disabled={!webChatKnown} label="استقبال محادثات الموقع" description={!webChatKnown ? 'الحالة غير متاحة. أعد تحميل الإعدادات قبل تغيير هذه القناة.' : webChat.slug ? `المسار العام: /c/${webChat.slug}` : 'يتم إنشاء معرّف رابط عام عند التفعيل.'} /></div>
                  {webChatKnown && webChat.enabled && webChat.slug && <a href={`/c/${webChat.slug}`} target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-1.5 text-[10px] font-semibold text-[#c8eaff] hover:text-white">فتح الصفحة المستضافة <ExternalLink className="h-3 w-3" /></a>}
                </Card>
              </div>
            </Card>
          )}

          {activeTab === 'notifications' && (
            <Card className="p-5 sm:p-6">
              <PanelHeader eyebrow="التنبيهات التشغيلية" title="إشعارات الحالات المهمة" description="أرسل تنبيهات VELOR العاجلة إلى رقم واتساب موثوق." action={<Badge tone={alertsKnown ? 'green' : 'neutral'}>{alertsKnown ? 'تم تحميل إعدادات الخادم' : 'غير معروف'}</Badge>} />
              <div className="mt-6 space-y-6">
                <Toggle checked={alertsKnown && alerts.is_alerts_enabled} onChange={(value) => setAlerts((current) => ({ ...current, is_alerts_enabled: value }))} disabled={!alertsKnown} label="تنبيهات واتساب" description={alertsKnown ? 'أبلغ مالك مساحة العمل بحالات العملاء العاجلة.' : 'الحالة غير متاحة. أعد تحميل الإعدادات قبل تغيير التنبيهات.'} />
                <Field label="رقم استقبال التنبيهات" icon={Smartphone} value={alerts.alert_whatsapp_number || ''} onChange={(event) => setAlerts((current) => ({ ...current, alert_whatsapp_number: event.target.value }))} placeholder="+20 10 0000 0000" disabled={!alertsKnown || !alerts.is_alerts_enabled} hint="أدخل كود الدولة" />
                <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-4"><p className="flex items-center gap-2 text-xs font-semibold text-white"><BellRing className="h-4 w-4 text-velor-purple" /> نطاق التنبيهات</p><p className="mt-2 text-[11px] leading-5 text-velor-muted">يحفظ العقد الحالي حالة تفعيل التنبيهات ورقم الاستقبال فقط. تفضيلات منفصلة لكل نوع حدث غير متاحة بعد.</p></div>
                <div className="flex justify-end"><Button onClick={saveNotifications} loading={saving} disabled={!alertsKnown}><Save className="h-4 w-4" /> حفظ التنبيهات</Button></div>
              </div>
            </Card>
          )}

          {activeTab === 'security' && (
            <>
              <Card className="p-5 sm:p-6">
                <PanelHeader eyebrow="المصادقة" title="أمان الجلسة" description="يستخدم VELOR جلسات ملفات ارتباط يتحقق منها الخادم مع وصول محصور داخل مساحة العمل." />
                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-4"><span className="flex h-9 w-9 items-center justify-center rounded-lg bg-velor-green/10 text-velor-green"><ShieldCheck className="h-4 w-4" /></span><p className="mt-3 text-xs font-semibold text-white">الجلسة موثقة</p><p className="mt-1 text-[10px] leading-4 text-velor-muted">يُعاد التحقق من الوصول مع الخادم عند التحميل.</p></div>
                  <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-4"><span className="flex h-9 w-9 items-center justify-center rounded-lg bg-velor-purple/10 text-velor-violet"><Building2 className="h-4 w-4" /></span><p className="mt-3 text-xs font-semibold text-white">عزل مساحة العمل</p><p className="mt-1 text-[10px] leading-4 text-velor-muted">تأتي هوية مساحة العمل من جلسة الدخول الموثقة، لا من إدخال نموذج.</p></div>
                </div>
              </Card>

              <Card className="p-5 sm:p-6">
                <PanelHeader eyebrow="وصول المطور" title="مفتاح API لمساحة العمل" description="يؤدي تدوير المفتاح إلى إبطال المفتاح السابق. تُعرض القيمة الجديدة مرة واحدة." action={<KeyRound className="h-5 w-5 text-velor-purple" />} />
                <div className="mt-5 flex flex-col gap-4 rounded-xl border border-velor-amber/15 bg-velor-amber/[0.04] p-4 sm:flex-row sm:items-center sm:justify-between"><div><p className="text-xs font-semibold text-white">••••••••••••••••••••••••</p><p className="mt-1 text-[10px] text-velor-muted">لا تعيد واجهة API المفتاح الحالي أبدًا.</p></div><Button variant="secondary" onClick={() => { setRotateOpen(true); setNewApiKey(''); }}>تدوير مفتاح API <RefreshCw className="h-3.5 w-3.5" /></Button></div>
              </Card>
            </>
          )}
        </div>
      </div>

      {rotateOpen && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/75 px-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="rotate-title" onMouseDown={(event) => { if (event.currentTarget === event.target && !rotating) setRotateOpen(false); }}>
          <Card className="w-full max-w-md border-white/12 bg-[#11131e] p-5 shadow-[0_30px_100px_rgba(0,0,0,.55)] animate-velor-in">
            <div className="flex items-start justify-between gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-xl border border-velor-amber/20 bg-velor-amber/10 text-velor-amber"><KeyRound className="h-5 w-5" /></span><button type="button" onClick={() => setRotateOpen(false)} disabled={rotating} className="flex h-9 w-9 items-center justify-center rounded-lg text-velor-muted hover:bg-white/5 hover:text-white" aria-label="إغلاق"><X className="h-4 w-4" /></button></div>
            {!newApiKey ? <><h2 id="rotate-title" className="mt-4 text-lg font-semibold text-white">هل تريد تدوير مفتاح API لمساحة العمل؟</h2><p className="mt-2 text-xs leading-5 text-velor-muted">سيتوقف أي تكامل يستخدم المفتاح الحالي فورًا. حدّث كل التكاملات الموثوقة بعد التدوير.</p><div className="mt-5 flex justify-end gap-2"><Button variant="ghost" onClick={() => setRotateOpen(false)} disabled={rotating}>إلغاء</Button><Button variant="danger" onClick={confirmRotation} loading={rotating}>تدوير المفتاح</Button></div></> : <><Badge tone="green">تم إنشاء مفتاح جديد</Badge><h2 id="rotate-title" className="mt-3 text-lg font-semibold text-white">احفظ هذا المفتاح الآن.</h2><p className="mt-2 text-xs leading-5 text-velor-muted">لن يعرض VELOR بيانات الاعتماد مرة أخرى.</p><div className="mt-4 flex items-center gap-2"><code className="min-w-0 flex-1 truncate rounded-xl border border-white/[0.08] bg-black/25 px-3 py-3 text-xs text-white" dir="ltr">{newApiKey}</code><Button variant="secondary" onClick={copyApiKey} className="shrink-0 px-3" aria-label="نسخ المفتاح">{copied ? <Check className="h-4 w-4 text-velor-green" /> : <Copy className="h-4 w-4" />}</Button></div><Button onClick={() => setRotateOpen(false)} className="mt-5 w-full">حفظت المفتاح</Button></>}
          </Card>
        </div>
      )}
    </div>
  );
}

function ChevronRightIcon() {
  return <ExternalLink className="h-3.5 w-3.5" />;
}
