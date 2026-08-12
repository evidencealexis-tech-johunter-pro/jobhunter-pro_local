import React, { useState, useEffect } from 'react';
import { base44 } from '@/api/base44Client';
import { toast } from 'sonner';
import { Plus, Trash2, Link as LinkIcon, Save, Loader2, Globe, Key, CheckCircle, AlertCircle, ChevronDown } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Separator } from "@/components/ui/separator";
import { Badge } from '@/components/ui/badge';

function SettingRow({ label, description, children }) {
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-700">{label}</p>
        {description && <p className="text-xs text-slate-500 mt-0.5">{description}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

export default function Settings() {
  const [loading, setLoading] = useState(true);
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingMatching, setSavingMatching] = useState(false);
  const [savingNotifications, setSavingNotifications] = useState(false);

  const [settings, setSettings] = useState(null);
  const [settingsId, setSettingsId] = useState(null);
  const [sources, setSources] = useState([]);
  const [newSourceName, setNewSourceName] = useState('');
  const [newSourceUrl, setNewSourceUrl] = useState('');
  const [addingSource, setAddingSource] = useState(false);

  // --- AI Provider key state ---
  const [apiKey, setApiKey] = useState('');
  const [selectedProvider, setSelectedProvider] = useState(''); // '' = nothing chosen yet
  const [customBaseUrl, setCustomBaseUrl] = useState('');
  const [customModel, setCustomModel] = useState('');
  const [savingKey, setSavingKey] = useState(false);
  const [keyStatus, setKeyStatus] = useState({ active: false, provider: null, model: null });
  const [loadingKeyStatus, setLoadingKeyStatus] = useState(true);
  const [providers, setProviders] = useState([]); // [{id, label, needs_base_url}, ...]

  useEffect(() => {
    loadAll();
    fetchKeyStatus();
    fetchProviders();
  }, []);

  async function loadAll() {
    try {
      const [settingsList, sourceList] = await Promise.all([
        base44.entities.AppSettings.list(),
        base44.entities.ScrapeSource.list('-created_date', 50),
      ]);
      if (settingsList.length > 0) {
        setSettings(settingsList[0]);
        setSettingsId(settingsList[0].id);
      } else {
        const defaults = {
          user_name: '',
          match_threshold: 70,
          skills_weight: 40,
          semantic_weight: 25,
          seniority_weight: 15,
          domain_weight: 20,
          telegram_enabled: false,
          telegram_bot_token: '',
          telegram_chat_id: '',
          interview_alerts: false,
        };
        setSettings(defaults);
      }
      setSources(sourceList);
    } catch (error) {
      console.error('Failed to load settings:', error);
      toast.error('Failed to load settings.');
    } finally {
      setLoading(false);
    }
  }

  // --- AI Provider: fetch current key status ---
  async function fetchKeyStatus() {
    try {
      const res = await fetch('/api/settings/api-key/status');
      if (res.ok) setKeyStatus(await res.json());
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingKeyStatus(false);
    }
  }

  // --- AI Provider: fetch the list of providers for the dropdown ---
  async function fetchProviders() {
    try {
      const res = await fetch('/api/settings/providers');
      if (res.ok) {
        const data = await res.json();
        setProviders(data.providers || []); // [{id, label, needs_base_url}, ...]
      }
    } catch (e) {
      console.error(e);
    }
  }

  function update(field, value) {
    setSettings((prev) => ({ ...prev, [field]: value }));
  }

  async function commitSettingsPayload() {
    if (settingsId) {
      return await base44.entities.AppSettings.update(settingsId, settings);
    } else {
      const created = await base44.entities.AppSettings.create(settings);
      setSettingsId(created.id);
      return created;
    }
  }

  // --- Profile Save ---
  async function handleSaveProfile() {
    setSavingProfile(true);
    try {
      await commitSettingsPayload();
      toast.success('Profile updated.');
    } catch (error) {
      toast.error('Failed to save profile.');
    } finally {
      setSavingProfile(false);
    }
  }

  // --- Matching Save ---
  async function handleSaveMatching() {
    const totalWeight = (settings?.skills_weight || 0) +
                        (settings?.semantic_weight || 0) +
                        (settings?.seniority_weight || 0) +
                        (settings?.domain_weight || 0);
    if (totalWeight !== 100) {
      toast.error(`Total weight must equal 100%. Current: ${totalWeight}%`);
      return;
    }
    setSavingMatching(true);
    try {
      await commitSettingsPayload();
      toast.success('Matching engine saved.');
    } catch (error) {
      toast.error('Failed to save matching.');
    } finally {
      setSavingMatching(false);
    }
  }

  // --- Notifications Save ---
  async function handleSaveNotifications() {
    setSavingNotifications(true);
    try {
      await commitSettingsPayload();
      toast.success('Notifications saved.');
    } catch (error) {
      toast.error('Failed to save notifications.');
    } finally {
      setSavingNotifications(false);
    }
  }

  // --- AI Provider: derived state for whether the Custom fields should show ---
  const selectedProviderInfo = providers.find((p) => p.id === selectedProvider);
  const needsBaseUrl = selectedProviderInfo?.needs_base_url;

  // --- AI Provider: Save & Activate ---
  async function handleSaveKey() {
    if (!apiKey.trim()) return toast.error('Please enter an API key.');
    if (!selectedProvider) return toast.error('Please select a provider first.');
    if (needsBaseUrl && (!customBaseUrl.trim() || !customModel.trim())) {
      return toast.error('Custom providers need a Base URL and a model name.');
    }

    setSavingKey(true);
    try {
      const body = {
        api_key: apiKey.trim(),
        provider: selectedProvider,
      };
      if (needsBaseUrl) {
        body.base_url = customBaseUrl.trim();
        body.model = customModel.trim();
      }

      const res = await fetch('/api/settings/api-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || 'Failed to save key');
      }

      toast.success(data.message || 'Key saved!');
      setApiKey('');
      setCustomBaseUrl('');
      setCustomModel('');
      fetchKeyStatus();
    } catch (error) {
      toast.error(error.message);
    } finally {
      setSavingKey(false);
    }
  }

  async function handleRemoveKey() {
    try {
      const res = await fetch('/api/settings/api-key', { method: 'DELETE' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to remove key');
      toast.success('Key removed.');
      fetchKeyStatus();
    } catch (error) {
      toast.error(error.message);
    }
  }

  // --- Source Management ---
  async function handleAddSource() {
    if (!newSourceUrl.trim()) {
      toast.error('Please enter a URL.');
      return;
    }
    setAddingSource(true);
    try {
      let url = newSourceUrl.trim();
      if (!url.startsWith('http')) url = 'https://' + url;
      const created = await base44.entities.ScrapeSource.create({
        name: newSourceName.trim() || url,
        url,
        active: true,
      });
      setSources((prev) => [created, ...prev]);
      setNewSourceName('');
      setNewSourceUrl('');
      toast.success('Source added.');
    } catch (error) {
      toast.error('Failed to add source.');
    } finally {
      setAddingSource(false);
    }
  }

  async function handleToggleSource(source) {
    try {
      const updated = await base44.entities.ScrapeSource.update(source.id, { active: !source.active });
      setSources((prev) => prev.map((s) => (s.id === source.id ? updated : s)));
    } catch (error) {
      toast.error('Failed to update source.');
    }
  }

  async function handleDeleteSource(source) {
    try {
      await base44.entities.ScrapeSource.delete(source.id);
      setSources((prev) => prev.filter((s) => s.id !== source.id));
      toast.success('Source removed.');
    } catch (error) {
      toast.error('Failed to remove source.');
    }
  }

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-6 h-6 text-slate-300 animate-spin" />
      </div>
    );
  }

  const totalWeight = (settings?.skills_weight || 0) + (settings?.semantic_weight || 0) + (settings?.seniority_weight || 0) + (settings?.domain_weight || 0);

  return (
    <div className="p-6 lg:p-8 max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Settings</h1>
        <p className="text-sm text-slate-500 mt-1">Control your matching, sources, and AI provider</p>
      </div>

      {/* Profile Card */}
      <Card className="p-5 border-slate-200 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-slate-900">Profile</h3>
          <Button size="sm" onClick={handleSaveProfile} disabled={savingProfile}>
            {savingProfile ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Save className="w-3.5 h-3.5 mr-1.5" />}
            Save Profile
          </Button>
        </div>
        <div>
          <Label htmlFor="user_name" className="text-xs text-slate-500">Your name</Label>
          <Input id="user_name" value={settings?.user_name || ''} onChange={(e) => update('user_name', e.target.value)} className="mt-1" />
        </div>
      </Card>

      {/* AI Provider Card */}
      <Card className="p-5 border-slate-200 shadow-sm">
        <div className="flex items-center gap-2 mb-4">
          <Key className="w-4 h-4 text-indigo-600" />
          <h3 className="text-sm font-semibold text-slate-900">AI Provider API Key</h3>
        </div>


        {!loadingKeyStatus && (
        <div className="mb-4">
          {keyStatus.active ? (
            <div className="flex items-center justify-between gap-2 text-sm text-emerald-600 bg-emerald-50 px-3 py-1.5 rounded-lg">
              <span className="flex items-center gap-2 min-w-0">
                <CheckCircle className="w-4 h-4 shrink-0" />
                <span className="truncate">
                  Active: {keyStatus.provider?.toUpperCase()} ({keyStatus.model}) — ****{keyStatus.key_suffix}
                </span>
              </span>
              <button
                onClick={handleRemoveKey}
                className="flex items-center gap-1 text-xs font-medium text-red-600 hover:text-red-700 hover:bg-red-50 px-2 py-1 rounded-md transition-colors shrink-0"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Remove
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-sm text-amber-600 bg-amber-50 px-3 py-1.5 rounded-lg">
              <AlertCircle className="w-4 h-4" />
              No active API key
            </div>
          )}
        </div>
        )}

        <p className="text-xs text-slate-500 mb-4">
          Choose your provider, paste the matching key, and save. Don't see your provider listed? Pick "Other / Custom".
        </p>

        {/* Provider dropdown */}
        <div className="mb-4">
          <Label className="text-sm font-medium text-slate-700">Provider</Label>
          <div className="relative mt-1">
            <select
              value={selectedProvider}
              onChange={(e) => setSelectedProvider(e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 appearance-none"
            >
              <option value="">-- Choose provider --</option>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </select>
            <ChevronDown className="w-4 h-4 absolute right-3 top-3 text-slate-400 pointer-events-none" />
          </div>
        </div>

        {/* Custom provider fields */}
        {needsBaseUrl && (
          <>
            <div className="mb-4">
              <Label className="text-sm font-medium text-slate-700">Base URL</Label>
              <Input
                placeholder="https://api.example-provider.com/v1"
                value={customBaseUrl}
                onChange={(e) => setCustomBaseUrl(e.target.value)}
                className="mt-1"
              />
            </div>
            <div className="mb-4">
              <Label className="text-sm font-medium text-slate-700">Model name</Label>
              <Input
                placeholder="e.g. their-model-name-here"
                value={customModel}
                onChange={(e) => setCustomModel(e.target.value)}
                className="mt-1"
              />
            </div>
          </>
        )}

        <div className="mb-4">
          <Label className="text-sm font-medium text-slate-700">API Key</Label>
          <Input
            type="password"
            placeholder="Paste your API key"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="mt-1"
          />
        </div>

        <div className="flex justify-end">
          <Button onClick={handleSaveKey} disabled={savingKey} size="sm" className="bg-indigo-600 hover:bg-indigo-700">
            {savingKey ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : null}
            Save & Activate
          </Button>
        </div>
      </Card>

      {/* Matching Engine Card */}
      <Card className="p-5 border-slate-200 shadow-sm">
        <div className="flex items-center justify-between mb-2">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Matching Engine</h3>
            <p className="text-xs text-slate-500">Jobs scoring above your threshold appear in your matches</p>
          </div>
          <Button size="sm" onClick={handleSaveMatching} disabled={savingMatching} className="bg-indigo-600 hover:bg-indigo-700">
            {savingMatching ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Save className="w-3.5 h-3.5 mr-1.5" />}
            Save Matrix
          </Button>
        </div>

        <div className="mb-4 mt-3">
          <div className="flex items-center justify-between mb-2">
            <Label className="text-sm text-slate-700">Match threshold</Label>
            <span className="text-sm font-bold text-indigo-600">{settings?.match_threshold ?? 70}%</span>
          </div>
          <Slider value={[settings?.match_threshold ?? 70]} onValueChange={([v]) => update('match_threshold', v)} min={0} max={100} step={5} />
        </div>

        <Separator className="my-4" />

        <div className="flex items-center justify-between mb-4">
          <p className="text-xs font-medium text-slate-600">Scoring weights (must total exactly 100)</p>
          <Badge variant={totalWeight === 100 ? "default" : "destructive"} className="text-xs">Total: {totalWeight}/100</Badge>
        </div>

        {[
          { key: 'skills_weight', label: 'Skills overlap', desc: 'How much skill matching matters' },
          { key: 'semantic_weight', label: 'Semantic similarity', desc: 'Overall meaning match' },
          { key: 'seniority_weight', label: 'Seniority fit', desc: 'Experience level alignment' },
          { key: 'domain_weight', label: 'Domain fit', desc: 'Industry/background match' },
        ].map((w) => (
          <div key={w.key} className="mb-4">
            <div className="flex items-center justify-between mb-1.5">
              <div>
                <Label className="text-sm text-slate-700">{w.label}</Label>
                <p className="text-xs text-slate-400">{w.desc}</p>
              </div>
              <span className="text-sm font-bold text-slate-700">{settings?.[w.key] ?? 0}%</span>
            </div>
            <Slider value={[settings?.[w.key] ?? 0]} onValueChange={([v]) => update(w.key, v)} min={0} max={100} step={5} />
          </div>
        ))}
      </Card>

      {/* Scrape Sources Card */}
      <Card className="p-5 border-slate-200 shadow-sm">
        <div className="flex items-center gap-2 mb-1">
          <Globe className="w-4 h-4 text-slate-400" />
          <h3 className="text-sm font-semibold text-slate-900">Scrape Sources</h3>
        </div>
        <p className="text-xs text-slate-500 mb-4">Website URLs to scan for job postings</p>

        <div className="flex flex-col sm:flex-row gap-2 mb-4">
          <Input placeholder="Source name (optional)" value={newSourceName} onChange={(e) => setNewSourceName(e.target.value)} className="sm:w-48" />
          <Input placeholder="https://company.com/careers" value={newSourceUrl} onChange={(e) => setNewSourceUrl(e.target.value)} className="flex-1" />
          <Button onClick={handleAddSource} disabled={addingSource} size="sm">
            {addingSource ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4 mr-1" />}
            Add
          </Button>
        </div>

        {sources.length === 0 ? (
          <div className="text-center py-6">
            <LinkIcon className="w-8 h-8 text-slate-200 mx-auto mb-2" />
            <p className="text-sm text-slate-400">No sources yet. Add a career page URL above.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {sources.map((source) => (
              <div key={source.id} className="flex items-center gap-3 p-3 rounded-lg border border-slate-200 bg-slate-50/50">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-700 truncate">{source.name}</p>
                  <p className="text-xs text-slate-400 truncate">{source.url}</p>
                </div>
                <Switch checked={source.active} onCheckedChange={() => handleToggleSource(source)} />
                <Button variant="ghost" size="icon" className="h-8 w-8 text-slate-400 hover:text-red-500" onClick={() => handleDeleteSource(source)}>
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Notifications Card */}
      <Card className="p-5 border-slate-200 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Notifications</h3>
            <p className="text-xs text-slate-500">Get alerted when new matching jobs are found</p>
          </div>
          <Button size="sm" onClick={handleSaveNotifications} disabled={savingNotifications}>
            {savingNotifications ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Save className="w-3.5 h-3.5 mr-1.5" />}
            Save Notifications
          </Button>
        </div>

        <SettingRow label="Telegram notifications" description="Message me on Telegram when new matches appear">
          <Switch checked={settings?.telegram_enabled || false} onCheckedChange={(v) => update('telegram_enabled', v)} />
        </SettingRow>

        {settings?.telegram_enabled && (
          <div className="space-y-3 py-2">
            <div>
              <Label className="text-xs text-slate-500">Bot token</Label>
              <Input value={settings?.telegram_bot_token || ''} onChange={(e) => update('telegram_bot_token', e.target.value)} placeholder="From @BotFather" className="mt-1" />
            </div>
            <div>
              <Label className="text-xs text-slate-500">Chat ID</Label>
              <Input value={settings?.telegram_chat_id || ''} onChange={(e) => update('telegram_chat_id', e.target.value)} placeholder="Your Telegram chat ID" className="mt-1" />
            </div>
          </div>
        )}

        <Separator className="my-2" />
        <SettingRow label="Interview alerts" description="Notify about interview invitations">
          <Switch checked={settings?.interview_alerts || false} onCheckedChange={(v) => update('interview_alerts', v)} />
        </SettingRow>
      </Card>
    </div>
  );
}