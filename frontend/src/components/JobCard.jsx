import React from 'react';
import { Link } from 'react-router-dom';
import { ExternalLink, X, MapPin, TrendingUp, AlertCircle, AlertTriangle, GraduationCap } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { scoreColor, legitimacyColor } from '@/lib/jobUtils';

const statusOptions = [
  { value: 'new', label: 'New' },
  { value: 'interested', label: 'Interested' },
  { value: 'applied', label: 'Applied' },
  { value: 'responded', label: 'Responded' },
  { value: 'interviewed', label: 'Interviewed' },
  { value: 'rejected', label: 'Rejected' },
];

export default function JobCard({ job, onDismiss, onStatusChange }) {
  const score = job.match_score ?? 0;
  const legitimacy = job.legitimacy_score != null ? legitimacyColor(job.legitimacy_score) : null;

  return (
    <Card className="p-5 hover:shadow-md transition-shadow border-slate-200">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <h3 className="font-semibold text-slate-900 text-base leading-snug truncate">{job.title}</h3>
            {job.repost_count > 0 && (
              <Badge variant="outline" className="text-xs text-amber-600 border-amber-200 bg-amber-50 shrink-0">
                Reposted {job.repost_count}x
              </Badge>
            )}
          </div>
          <p className="text-sm text-slate-500">
            {job.company || 'Unknown company'}
            {job.location && <span className="mx-1.5 text-slate-300">•</span>}
            {job.location && (
              <span className="inline-flex items-center gap-1">
                <MapPin className="w-3 h-3" />
                {job.location}
              </span>
            )}
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {legitimacy && (
            <Badge variant="outline" className={`text-xs ${legitimacy.className}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${legitimacy.dot} mr-1`} />
              {legitimacy.label}
            </Badge>
          )}
          <div className={`px-2.5 py-1 rounded-md text-sm font-bold border ${scoreColor(score)}`}>
            {score}%
          </div>
          {onDismiss && (
            <Button variant="ghost" size="icon" className="h-8 w-8 text-slate-400 hover:text-red-500" onClick={() => onDismiss(job)}>
              <X className="w-4 h-4" />
            </Button>
          )}
        </div>
      </div>

      {job.match_reasons && job.match_reasons.length > 0 && (
        <div className="mb-3">
          <div className="flex items-center gap-1.5 text-xs font-medium text-emerald-600 mb-1.5">
            <TrendingUp className="w-3.5 h-3.5" />
            Why it matched
          </div>
          <ul className="space-y-1">
            {job.match_reasons.slice(0, 3).map((reason, i) => (
              <li key={i} className="text-sm text-slate-600 leading-relaxed pl-4 relative">
                <span className="absolute left-0 top-2 w-1 h-1 rounded-full bg-emerald-400" />
                {reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {job.red_flags && job.red_flags.length > 0 && (
        <div className="mb-3">
          <div className="flex items-center gap-1.5 text-xs font-medium text-red-600 mb-1.5">
            <AlertTriangle className="w-3.5 h-3.5" />
            Red flags
          </div>
          <ul className="space-y-1">
            {job.red_flags.slice(0, 3).map((flag, i) => (
              <li key={i} className="text-sm text-slate-600 leading-relaxed pl-4 relative">
                <span className="absolute left-0 top-2 w-1 h-1 rounded-full bg-red-400" />
                {flag}
              </li>
            ))}
          </ul>
        </div>
      )}

      {job.skill_gaps && job.skill_gaps.length > 0 && (
        <div className="mb-3">
          <div className="flex items-center gap-1.5 text-xs font-medium text-amber-600 mb-1.5">
            <AlertCircle className="w-3.5 h-3.5" />
            Skills to learn
          </div>
          <div className="flex flex-wrap gap-1.5">
            {job.skill_gaps.slice(0, 6).map((gap, i) => (
              <Badge key={i} variant="outline" className="text-xs text-amber-700 border-amber-200 bg-amber-50">
                {gap}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {job.skills_required && job.skills_required.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {job.skills_required.slice(0, 5).map((skill, i) => (
            <Badge key={i} variant="secondary" className="text-xs font-normal">
              {skill}
            </Badge>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between gap-2 pt-2 border-t border-slate-100">
        <Select value={job.status || 'new'} onValueChange={(val) => onStatusChange?.(job, val)}>
          <SelectTrigger className="w-[140px] h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {statusOptions.map((opt) => (
              <SelectItem key={opt.value} value={opt.value} className="text-xs">
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" asChild className="h-8 text-xs">
            <Link to={`/interview/${job.id}`}>
              <GraduationCap className="w-3.5 h-3.5 mr-1" />
              Prep
            </Link>
          </Button>
          <Button variant="outline" size="sm" asChild className="h-8 text-xs">
            <a href={job.url} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="w-3.5 h-3.5 mr-1" />
              View Job
            </a>
          </Button>
        </div>
      </div>
    </Card>
  );
}