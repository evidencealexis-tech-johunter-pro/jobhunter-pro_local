import React, { useState, useEffect, useRef } from 'react';
import { base44 } from '@/api/base44Client';
import { toast } from 'sonner';
import { exportToCSV } from '@/lib/jobUtils';
import { Loader2, Search, AlertTriangle, Filter, Download, RefreshCw, Square, Trash2 } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import JobCard from '@/components/JobCard';
import { useRefresh } from '@/lib/RefreshContext';

const POLL_INTERVAL_MS = 1500;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function formatEta(seconds) {
  if (seconds == null) return '';
  if (seconds < 60) return `~${seconds}s remaining`;
  const mins = Math.round(seconds / 60);
  return `~${mins} min remaining`;
}

export default function JobDiscovery() {
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [scanProgress, setScanProgress] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [hasResume, setHasResume] = useState(false);
  const [sourceCount, setSourceCount] = useState(0);
  const [threshold, setThreshold] = useState(70);
  const [showAll, setShowAll] = useState(false);
  const [clearing, setClearing] = useState(false);

  const stoppedRef = useRef(false);
  const currentJobIdRef = useRef(null);

  const { refresh } = useRefresh();

  useEffect(() => {
    loadData();
    attachToAnyRunningScan();
  }, []);

  async function loadData() {
    try {
      const [resumes, sources, settingsList, allJobs] = await Promise.all([
        base44.entities.Resume.filter({ active: true }),
        base44.entities.ScrapeSource.filter({ active: true }),
        base44.entities.AppSettings.list(),
        base44.entities.Job.filter({ dismissed: false }, '-created_date', 500),
      ]);
      setHasResume(resumes.length > 0);
      setSourceCount(sources.length);
      setThreshold(settingsList[0]?.match_threshold ?? 70);
      setJobs(allJobs);
    } catch (error) {
      console.error('Failed to load job discovery data:', error);
      toast.error('Error loading job discovery data.');
    } finally {
      setLoading(false);
    }
  }

  async function attachToAnyRunningScan() {
    try {
      const res = await fetch('/api/apps/local/integration-endpoints/Core/ScrapeJobs/current');
      const data = await res.json();
      if (data.job_id) {
        setScanning(true);
        stoppedRef.current = false;
        currentJobIdRef.current = data.job_id;
        pollJob(data.job_id).then(async (result) => {
          setScanning(false);
          setScanProgress(null);
          currentJobIdRef.current = null;
          await loadData();
          if (result?.saved) {
            toast.success(`Found ${result.saved} new matching job${result.saved !== 1 ? 's' : ''}.`);
          }
        });
      }
    } catch (e) {
      console.error('Failed to check for a running scan:', e);
    }
  }

  async function pollJob(job_id) {
    while (true) {
      if (stoppedRef.current) {
        try {
          await fetch(`/api/apps/local/integration-endpoints/Core/ScrapeJobs/${job_id}/stop`, { method: 'POST' });
        } catch (e) {
          console.error('Failed to send stop signal:', e);
        }
        return null;
      }

      const statusRes = await fetch(`/api/apps/local/integration-endpoints/Core/ScrapeJobs/${job_id}/status`);
      if (!statusRes.ok) return null;
      const state = await statusRes.json();

      setScanProgress({
        phase: state.source_label ? `Scanning ${state.source_label}` : 'Scanning...',
        stage: state.stage || '',
        jobSaved: state.saved || 0,
        jobTotal: state.total || 0,
        eta: formatEta(state.eta_seconds),
      });

      if (state.status === 'completed') return { saved: state.saved || 0 };
      if (state.status === 'stopped') return { saved: state.saved || 0, stopped: true };
      if (state.status === 'error') return { saved: 0, error: true, message: state.message };
      if (state.status === 'interrupted') return { saved: state.saved || 0, interrupted: true };

      await sleep(POLL_INTERVAL_MS);
    }
  }

  // Starts one source's scan, then polls it to completion. This is the
  // piece that must run for EVERY source in the loop below - if it's
  // missing, a scan will only ever do one source and stop, which is the
  // exact bug this file fixes.
  async function runOneSourceScrape(source, settings) {
    const startRes = await fetch('/api/apps/local/integration-endpoints/Core/ScrapeJobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_url: source.url,
        source_name: source.name,
        match_threshold: settings.match_threshold ?? 70,
        skills_weight: settings.skills_weight ?? 40,
        semantic_weight: settings.semantic_weight ?? 25,
        seniority_weight: settings.seniority_weight ?? 15,
        domain_weight: settings.domain_weight ?? 20,
      }),
    });
    if (!startRes.ok) {
      const errData = await startRes.json().catch(() => ({}));
      throw new Error(errData.detail || `Failed to start scan for ${source.name}`);
    }
    const { job_id } = await startRes.json();
    currentJobIdRef.current = job_id;
    const result = await pollJob(job_id);
    return result || { saved: 0, error: true };
  }

  async function handleScan() {
    if (!hasResume) {
      toast.error('Please upload your resume first.');
      return;
    }
    if (sourceCount === 0) {
      toast.error('Please add scrape sources in Settings first.');
      return;
    }

    setScanning(true);
    stoppedRef.current = false;
    currentJobIdRef.current = null;

    try {
      const [sources, settingsList] = await Promise.all([
        base44.entities.ScrapeSource.filter({ active: true }),
        base44.entities.AppSettings.list(),
      ]);
      const settings = settingsList[0] || {};

      let totalSaved = 0;
      let anyError = false;

      // THIS loop is what auto-continues to the next source. Each
      // iteration awaits runOneSourceScrape fully before moving to i+1 -
      // no page reload, no manual action needed between sources.
      for (let i = 0; i < sources.length; i++) {
        if (stoppedRef.current) break;

        const source = sources[i];
        try {
          const result = await runOneSourceScrape(source, settings);
          totalSaved += result.saved || 0;
          if (result.error) {
            anyError = true;
            toast.error(`Failed to scan ${source.name}${result.message ? ': ' + result.message : ''}`);
          }
          if (result.stopped) break;
        } catch (err) {
          console.error(`Failed to scan ${source.name}:`, err);
          toast.error(`Failed to scan ${source.name}`);
          anyError = true;
        }
      }

      if (stoppedRef.current) {
        toast.info(`Scan stopped. ${totalSaved} job${totalSaved !== 1 ? 's' : ''} saved before stopping.`);
      } else {
        if (anyError) {
          toast.info('Some sources had issues - check the notification bell for details.');
        }
        toast.success(`Found ${totalSaved} new matching job${totalSaved !== 1 ? 's' : ''}.`);
      }

      await loadData();
      refresh();
    } catch (error) {
      console.error('Scan failed:', error);
      toast.error('Scan failed: ' + (error.message || 'Unknown error'));
    } finally {
      setScanning(false);
      setScanProgress(null);
      currentJobIdRef.current = null;
    }
  }

  function handleStopScan() {
    stoppedRef.current = true;
  }

  async function handleClearAllJobs() {
    if (!confirm('Are you sure you want to delete all jobs? This cannot be undone.')) return;
    setClearing(true);
    try {
      const res = await fetch('/api/apps/local/entities/Job/clear-all', { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to clear jobs');
      await loadData();
      refresh();
      toast.success('All jobs have been cleared.');
    } catch (error) {
      toast.error(error.message);
    } finally {
      setClearing(false);
    }
  }

  async function handleDismiss(job) {
    try {
      await base44.entities.Job.update(job.id, { dismissed: true });
      setJobs((prev) => prev.filter((j) => j.id !== job.id));
    } catch (error) {
      console.error('Failed to dismiss job:', error);
      toast.error('Failed to dismiss job.');
    }
  }

  async function handleStatusChange(job, status) {
    try {
      const updated = await base44.entities.Job.update(job.id, { status });
      setJobs((prev) => prev.map((j) => (j.id === job.id ? updated : j)));
    } catch (error) {
      console.error('Failed to update job status:', error);
      toast.error('Failed to update status.');
    }
  }

  function handleExport() {
    if (visibleJobs.length === 0) {
      toast.error('No jobs to export.');
      return;
    }
    exportToCSV(visibleJobs);
  }

  const visibleJobs = showAll ? jobs : jobs.filter((j) => (j.match_score ?? 0) >= threshold);

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-6 h-6 text-slate-300 animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6 lg:p-8 max-w-5xl mx-auto">
      <div className="flex items-center justify-between gap-4 mb-2">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Job Discovery</h1>
          <p className="text-sm text-slate-500 mt-1">
            {showAll
              ? `${jobs.length} job${jobs.length !== 1 ? 's' : ''} found`
              : `${visibleJobs.length} job${visibleJobs.length !== 1 ? 's' : ''} matching \u2265 ${threshold}%`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {scanning && (
            <Button
              size="sm"
              onClick={handleStopScan}
              className="h-9 px-2.5 text-xs bg-red-600 hover:bg-red-700 text-white border-none"
            >
              <Square className="w-3 h-3 mr-1" strokeWidth={3} />
              Stop
            </Button>
          )}

          {!scanning && visibleJobs.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleClearAllJobs}
              disabled={clearing}
              className="h-9 px-2.5 text-xs border-red-200 text-red-600 hover:bg-red-50"
            >
              {clearing ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Trash2 className="w-3 h-3 mr-1" />}
              Clear All Jobs
            </Button>
          )}

          <Button variant="outline" onClick={handleExport}>
            <Download className="w-4 h-4 mr-2" /> Export CSV
          </Button>
          <Button onClick={handleScan} disabled={scanning} className="bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm">
            {scanning ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Search className="w-4 h-4 mr-2" />}
            {scanning ? 'Scanning...' : 'Scan for Jobs'}
          </Button>
        </div>
      </div>

      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-slate-400" />
          <span className="text-sm text-slate-600">Show all jobs (ignore threshold)</span>
          <Switch checked={showAll} onCheckedChange={setShowAll} />
        </div>
        <span className="text-xs font-mono font-semibold bg-slate-100 text-slate-600 px-2.5 py-1 rounded-md">
          Threshold: {threshold}%
        </span>
      </div>

      {scanning && scanProgress && (
        <Card className="p-5 border-indigo-100 bg-indigo-50/40 mb-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Loader2 className="w-5 h-5 text-indigo-600 animate-spin" />
            <div>
              <p className="text-sm font-semibold text-slate-800">{scanProgress.phase}</p>
              <p className="text-xs text-slate-400 mt-0.5">
                {scanProgress.stage || 'This can take a moment while jobs are matched against your resume.'}
                {scanProgress.eta && ` \u2022 ${scanProgress.eta}`}
              </p>
            </div>
          </div>
          {scanProgress.jobTotal > 0 && (
            <span className="text-xs font-mono font-bold bg-indigo-100 text-indigo-700 px-2.5 py-1 rounded-md">
              {scanProgress.jobSaved} / {scanProgress.jobTotal} jobs
            </span>
          )}
        </Card>
      )}

      <div className="space-y-4">
        {visibleJobs.map((job) => (
          <JobCard key={job.id} job={job} onDismiss={handleDismiss} onStatusChange={handleStatusChange} />
        ))}

        {visibleJobs.length === 0 && !scanning && (
          <div className="text-center py-16 border-2 border-dashed border-slate-200 rounded-xl">
            <AlertTriangle className="w-8 h-8 text-slate-300 mx-auto mb-3" />
            <p className="text-sm font-medium text-slate-600">No jobs found yet.</p>
            <p className="text-xs text-slate-400 mt-1">
              Click "Scan for Jobs" to search your sources for matching openings.
            </p>
            <Button variant="outline" size="sm" onClick={handleScan} disabled={scanning} className="mt-4">
              <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Scan now
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}