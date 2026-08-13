import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { base44 } from '@/api/base44Client';
import { Briefcase, Target, Search, FileText, ArrowRight, TrendingUp, Clock, CheckCircle2, Building2 } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useRefresh } from '@/lib/RefreshContext';

function StatCard({ icon: Icon, label, value, accent, loading }) {
  return (
    <Card className="p-5 border-slate-200">
      <div className="flex items-center gap-4">
        <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${accent}`}>
          <Icon className="w-5 h-5" />
        </div>
        <div>
          <p className="text-2xl font-bold text-slate-900 leading-none">
            {loading ? <span className="inline-block w-8 h-6 bg-slate-100 rounded animate-pulse" /> : value}
          </p>
          <p className="text-sm text-slate-500 mt-1">{label}</p>
        </div>
      </div>
    </Card>
  );
}

export default function Dashboard() {
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({ matching: 0, total: 0, sources: 0, applied: 0, interviews: 0, hasResume: false, resumeScore: null });
  const [userName, setUserName] = useState('');
  const [recentJobs, setRecentJobs] = useState([]);
  const { tick } = useRefresh();   // <-- listen for refresh trigger

  useEffect(() => {
    loadDashboard();
  }, [tick]);   // re‑fetch on each scan completion

  async function loadDashboard() {
    try {
      const [resumes, jobs, sources, settingsList] = await Promise.all([
        base44.entities.Resume.list('-created_date', 50),
        base44.entities.Job.filter({ dismissed: false }, '-match_score', 50),
        base44.entities.ScrapeSource.filter({ active: true }),
        base44.entities.AppSettings.list(),
      ]);

      const activeResume = resumes.find((r) => r.active);
      const settings = settingsList[0];
      const threshold = settings?.match_threshold ?? 70;

      const matching = jobs.filter((j) => (j.match_score ?? 0) >= threshold);
      const applied = jobs.filter((j) => ['applied', 'responded', 'interviewed'].includes(j.status));
      const interviews = jobs.filter((j) => j.status === 'interviewed');

      setStats({
        matching: matching.length,
        total: jobs.length,
        sources: sources.length,
        applied: applied.length,
        interviews: interviews.length,
        hasResume: !!activeResume,
        resumeScore: activeResume?.quality_score ?? null,
      });
      setUserName(settings?.user_name || '');
      setRecentJobs(matching.slice(0, 4));
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
    }
  }

  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';

  return (
    <div className="p-6 lg:p-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <p className="text-sm text-indigo-600 font-medium mb-1">{greeting}{userName ? `, ${userName}` : ''}</p>
        <h1 className="text-2xl lg:text-3xl font-bold text-slate-900 tracking-tight">Your job search at a glance</h1>
      </div>

      {/* No resume state */}
      {!loading && !stats.hasResume && (
        <Card className="p-8 mb-6 border-indigo-200 bg-gradient-to-br from-indigo-50 to-white">
          <div className="flex flex-col sm:flex-row items-start gap-5">
            <div className="w-12 h-12 rounded-xl bg-indigo-600 flex items-center justify-center shrink-0">
              <FileText className="w-6 h-6 text-white" />
            </div>
            <div className="flex-1">
              <h2 className="text-lg font-semibold text-slate-900 mb-1">Upload your resume to get started</h2>
              <p className="text-sm text-slate-600 mb-4">
                JobHunter Pro will analyze your skills, experience, and seniority — then start finding jobs that actually fit you.
              </p>
              <Button asChild>
                <Link to="/resume">
                  Upload Resume
                  <ArrowRight className="w-4 h-4 ml-1.5" />
                </Link>
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard icon={Target} label="Matching jobs" value={stats.matching} accent="bg-indigo-50 text-indigo-600" loading={loading} />
        <StatCard icon={Briefcase} label="Total scraped" value={stats.total} accent="bg-slate-100 text-slate-600" loading={loading} />
        <StatCard icon={CheckCircle2} label="Applications sent" value={stats.applied} accent="bg-blue-50 text-blue-600" loading={loading} />
        <StatCard icon={TrendingUp} label="Interviews" value={stats.interviews} accent="bg-emerald-50 text-emerald-600" loading={loading} />
      </div>

      {/* Resume quality + sources */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-8">
        <Card className="p-5 border-slate-200">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-slate-400" />
              <h3 className="text-sm font-medium text-slate-700">Resume Status</h3>
            </div>
            <Button variant="ghost" size="sm" asChild className="text-xs h-7">
              <Link to="/resume">Manage</Link>
            </Button>
          </div>
          {stats.hasResume ? (
            <div className="flex items-center gap-4">
              <div className="relative w-14 h-14">
                <svg className="w-14 h-14 -rotate-90" viewBox="0 0 56 56">
                  <circle cx="28" cy="28" r="24" fill="none" stroke="currentColor" strokeWidth="4" className="text-slate-100" />
                  <circle
                    cx="28" cy="28" r="24" fill="none" stroke="currentColor" strokeWidth="4"
                    className="text-indigo-600 transition-all"
                    strokeDasharray={`${(stats.resumeScore || 0) * 1.508} 999`}
                    strokeLinecap="round"
                  />
                </svg>
                <span className="absolute inset-0 flex items-center justify-center text-sm font-bold text-slate-900">
                  {stats.resumeScore ?? '--'}
                </span>
              </div>
              <div>
                <p className="text-sm font-medium text-slate-900">Active resume</p>
                <p className="text-xs text-slate-500">Quality score out of 100</p>
              </div>
            </div>
          ) : (
            <p className="text-sm text-slate-400">No resume uploaded yet</p>
          )}
        </Card>

        <Card className="p-5 border-slate-200">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Building2 className="w-4 h-4 text-slate-400" />
              <h3 className="text-sm font-medium text-slate-700">Scrape Sources</h3>
            </div>
            <Button variant="ghost" size="sm" asChild className="text-xs h-7">
              <Link to="/settings">Manage</Link>
            </Button>
          </div>
          <p className="text-2xl font-bold text-slate-900">{stats.sources}</p>
          <p className="text-xs text-slate-500">Active sources being monitored</p>
        </Card>
      </div>

      {/* Recent matches */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-slate-400" />
            <h2 className="text-base font-semibold text-slate-900">Top matches</h2>
          </div>
          <Button variant="ghost" size="sm" asChild className="text-xs">
            <Link to="/jobs">
              View all
              <ArrowRight className="w-3.5 h-3.5 ml-1" />
            </Link>
          </Button>
        </div>

        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <Card key={i} className="p-4">
                <div className="h-4 bg-slate-100 rounded w-1/3 mb-2 animate-pulse" />
                <div className="h-3 bg-slate-100 rounded w-1/4 animate-pulse" />
              </Card>
            ))}
          </div>
        ) : recentJobs.length > 0 ? (
          <div className="space-y-3">
            {recentJobs.map((job) => (
              <Card key={job.id} className="p-4 border-slate-200 hover:shadow-sm transition-shadow">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <h4 className="text-sm font-medium text-slate-900 truncate">{job.title}</h4>
                    <p className="text-xs text-slate-500">{job.company || 'Unknown company'}</p>
                  </div>
                  <Badge className="bg-indigo-50 text-indigo-600 border border-indigo-200 shrink-0">
                    {job.match_score}%
                  </Badge>
                </div>
              </Card>
            ))}
          </div>
        ) : (
          <Card className="p-8 text-center border-dashed border-slate-200">
            <Search className="w-8 h-8 text-slate-300 mx-auto mb-2" />
            <p className="text-sm text-slate-400">No matching jobs yet. Scan for jobs to find matches.</p>
            <Button variant="outline" size="sm" asChild className="mt-3">
              <Link to="/jobs">Scan for Jobs</Link>
            </Button>
          </Card>
        )}
      </div>
    </div>
  );
}