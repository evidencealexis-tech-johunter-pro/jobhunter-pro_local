import React, { useState, useEffect } from 'react';
import { base44 } from '@/api/base44Client';
import { toast } from 'sonner';
import { generateUpskillRoadmap } from '@/lib/jobUtils';
import { Loader2, GraduationCap, Target, TrendingUp, BookOpen, CheckCircle2 } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

export default function Upskill() {
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [skillGaps, setSkillGaps] = useState([]);
  const [resume, setResume] = useState(null);
  const [selectedSkill, setSelectedSkill] = useState(null);
  const [roadmap, setRoadmap] = useState(null);
  const [totalJobs, setTotalJobs] = useState(0);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    try {
      const [jobs, resumes] = await Promise.all([
        base44.entities.Job.filter({ dismissed: false }, '-match_score', 500),
        base44.entities.Resume.filter({ active: true }),
      ]);

      setTotalJobs(jobs.length);
      setResume(resumes[0] || null);

      const gapMap = {};
      for (const job of jobs) {
        for (const gap of (job.skill_gaps || [])) {
          const normalized = gap.trim();
          if (normalized) {
            const key = normalized.toLowerCase();
            gapMap[key] = (gapMap[key] || 0) + 1;
          }
        }
      }

      const gaps = Object.entries(gapMap)
        .map(([skill, count]) => ({ skill, count }))
        .sort((a, b) => b.count - a.count)
        .slice(0, 15);

      setSkillGaps(gaps);
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
    }
  }

  async function handleGenerateRoadmap(skill) {
    setSelectedSkill(skill);
    setGenerating(true);
    setRoadmap(null);
    try {
      const result = await generateUpskillRoadmap(skill, resume);
      setRoadmap(result);
    } catch (error) {
      toast.error('Failed to generate roadmap.');
    } finally {
      setGenerating(false);
    }
  }

  const maxCount = skillGaps.length > 0 ? skillGaps[0].count : 1;

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-6 h-6 text-slate-300 animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6 lg:p-8 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Upskill Roadmap</h1>
        <p className="text-sm text-slate-500 mt-1">
          {skillGaps.length > 0
            ? `${skillGaps.length} skills blocking you across ${totalJobs} jobs`
            : "No skill gaps detected yet — scan for jobs to see what you're missing"}
        </p>
      </div>

      {skillGaps.length === 0 ? (
        <Card className="p-12 text-center border-dashed border-slate-200">
          <Target className="w-10 h-10 text-slate-300 mx-auto mb-3" />
          <h3 className="text-base font-medium text-slate-700 mb-1">No skill gaps yet</h3>
          <p className="text-sm text-slate-500">
            Once you scan for jobs, missing skills will appear here with a learning roadmap.
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Skill gaps list */}
          <div>
            <h2 className="text-sm font-semibold text-slate-900 mb-3 flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-slate-400" />
              Top missing skills
            </h2>
            <div className="space-y-2">
              {skillGaps.map((gap) => (
                <Card
                  key={gap.skill}
                  className={`p-4 border-slate-200 cursor-pointer transition-all ${
                    selectedSkill === gap.skill ? 'border-indigo-400 ring-1 ring-indigo-200' : 'hover:border-slate-300'
                  }`}
                  onClick={() => handleGenerateRoadmap(gap.skill)}
                >
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <span className="text-sm font-medium text-slate-900 capitalize truncate">{gap.skill}</span>
                    <Badge variant="outline" className="text-xs shrink-0">
                      {gap.count} job{gap.count !== 1 ? 's' : ''}
                    </Badge>
                  </div>
                  <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-indigo-500 rounded-full"
                      style={{ width: `${(gap.count / maxCount) * 100}%` }}
                    />
                  </div>
                </Card>
              ))}
            </div>
            <p className="text-xs text-slate-400 mt-3">Click a skill to generate a learning roadmap</p>
          </div>

          {/* Roadmap */}
          <div>
            <h2 className="text-sm font-semibold text-slate-900 mb-3 flex items-center gap-2">
              <GraduationCap className="w-4 h-4 text-slate-400" />
              {selectedSkill ? `Roadmap: ${selectedSkill}` : 'Learning roadmap'}
            </h2>

            {generating ? (
              <Card className="p-12 text-center border-slate-200">
                <Loader2 className="w-8 h-8 text-indigo-600 animate-spin mx-auto mb-3" />
                <p className="text-sm text-slate-500">Building your roadmap...</p>
              </Card>
            ) : roadmap ? (
              <div className="space-y-3">
                {roadmap.overview && (
                  <Card className="p-4 border-indigo-200 bg-indigo-50/50">
                    <p className="text-sm text-slate-700 leading-relaxed">{roadmap.overview}</p>
                  </Card>
                )}
                {(roadmap.days || []).map((day, i) => (
                  <Card key={i} className="p-4 border-slate-200">
                    <div className="flex items-center gap-2 mb-2">
                      <div className="w-7 h-7 rounded-lg bg-slate-900 text-white flex items-center justify-center text-xs font-bold shrink-0">
                        {day.day}
                      </div>
                      <h3 className="text-sm font-semibold text-slate-900">{day.focus}</h3>
                    </div>
                    <ul className="space-y-1.5 mb-2">
                      {(day.tasks || []).map((task, j) => (
                        <li key={j} className="text-sm text-slate-600 flex gap-2 leading-relaxed">
                          <CheckCircle2 className="w-3.5 h-3.5 text-slate-300 mt-0.5 shrink-0" />
                          {task}
                        </li>
                      ))}
                    </ul>
                    {day.project && (
                      <div className="flex items-start gap-2 mt-2 pt-2 border-t border-slate-100">
                        <BookOpen className="w-3.5 h-3.5 text-indigo-500 mt-0.5 shrink-0" />
                        <p className="text-xs text-slate-600">
                          <span className="font-medium text-indigo-600">Project: </span>
                          {day.project}
                        </p>
                      </div>
                    )}
                  </Card>
                ))}
                <Button variant="outline" size="sm" className="w-full" onClick={() => handleGenerateRoadmap(selectedSkill)}>
                  Regenerate roadmap
                </Button>
              </div>
            ) : (
              <Card className="p-12 text-center border-dashed border-slate-200">
                <GraduationCap className="w-10 h-10 text-slate-300 mx-auto mb-3" />
                <h3 className="text-base font-medium text-slate-700 mb-1">Pick a skill to learn</h3>
                <p className="text-sm text-slate-500">
                  Select a missing skill to generate a day-by-day project-based learning plan.
                </p>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}