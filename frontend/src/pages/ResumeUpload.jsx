import React, { useState, useEffect, useRef } from 'react';
import { base44 } from '@/api/base44Client';
import { toast } from 'sonner';
import { analyzeResume, scoreJob } from '@/lib/jobUtils';
import { 
  FileText, Upload, Loader2, CheckCircle2, Star, 
  Lightbulb, Award, Trash2, Briefcase, Building2, Clock, Copy, Check 
} from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

export default function ResumeUpload() {
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [resume, setResume] = useState(null);
  const [allJobs, setAllJobs] = useState([]);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef(null);

  // ✅ Moved to top before any early returns
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    loadResumeDataContext();
  }, []);

  async function loadResumeDataContext() {
    try {
      const resumes = await base44.entities.Resume.list('-created_date', 10);
      const active = resumes.find((r) => r.active) || resumes[0];
      if (active) setResume(active);

      const jobs = await base44.entities.Job.filter({ dismissed: false }, '-created_date', 500);
      setAllJobs(jobs);
    } catch (error) {
      console.error('Failed to initialize resume dashboard context:', error);
      toast.error('Error loading resume profile metrics.');
    } finally {
      setLoading(false);
    }
  }

  function handleDrag(e) {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  }

  async function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      await processResumeFile(e.dataTransfer.files[0]);
    }
  }

  async function handleFileSelect(e) {
    if (e.target.files && e.target.files[0]) {
      await processResumeFile(e.target.files[0]);
    }
  }

  async function processResumeFile(file) {
    if (file.type !== "application/pdf" && !file.name.endsWith('.pdf')) {
      toast.error("JobHunter Pro currently requires standard PDF document formats.");
      return;
    }

    // Duplicate prevention
    try {
      const existingResumes = await base44.entities.Resume.list('-created_date', 50);
      const duplicate = existingResumes.find((r) => r.file_name === file.name);
      if (duplicate) {
        toast.error(`"${file.name}" has already been uploaded. Clear the existing resume first if you want to re-analyze it.`);
        return;
      }
    } catch (error) {
      console.error('Failed to check for duplicate resume:', error);
    }

    setAnalyzing(true);
    const tid = toast.loading('Uploading resume and extracting text...');

    try {
      const { file_url } = await base44.integrations.Core.UploadFile({ file });
      toast.loading('Analyzing skills, experience, and career profile...', { id: tid });

      const analysis = await analyzeResume(file_url);

      // Deactivate existing resumes
      const resumes = await base44.entities.Resume.list('-created_date', 50);
      for (const r of resumes) {
        if (r.active && r.id) {
          await base44.entities.Resume.update(r.id, { active: false });
        }
      }

      // Save with correct field mapping
      const newResume = await base44.entities.Resume.create({
        file_url,
        file_name: file.name,
        name: file.name,
        quality_score: analysis.quality_score ?? 0,
        seniority: analysis.seniority || '--',
        level: analysis.seniority || '--',
        summary: analysis.summary || 'No summary available.',
        professional_summary: analysis.summary || 'No summary available.',
        strengths: analysis.strengths || [],
        improvements: analysis.improvements || [],
        enhancements: analysis.improvements || [],
        skills: analysis.skills || [],
        detected_skills: analysis.skills || [],
        core_skills: analysis.core_skills || [],
        familiar_skills: analysis.familiar_skills || [],
        job_titles: analysis.job_titles || [],
        industries: analysis.industries || [],
        years_experience: analysis.years_experience || 0,
        raw_text: analysis.raw_text || '',
        active: true,
      });

      setResume(newResume);
      toast.success('Resume analyzed and profile saved!', { id: tid });

      // Re-score existing jobs
      if (allJobs.length > 0) {
        toast.info(`Re-scoring ${allJobs.length} existing jobs...`);
        for (const job of allJobs) {
          try {
            const score = await scoreJob(job, newResume, {});
            await base44.entities.Job.update(job.id, {
              match_score: score.match_score,
              skill_gaps: score.skill_gaps || [],
              match_reasons: score.match_reasons || [],
              skills_required: score.required_skills || [],
              seniority: score.job_seniority || '',
              domain: score.job_domain || '',
            });
          } catch (err) {
            console.error('Failed processing scoring for:', job.title, err);
          }
        }
      }
    } catch (error) {
      console.error('Operational failure:', error);
      toast.error(error.message || 'Failed to analyze profile.', { id: tid });
    } finally {
      setAnalyzing(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  async function handleDeleteResume() {
    if (!resume) return;
    try {
      await base44.entities.Resume.delete(resume.id);
      setResume(null);
      toast.success("Resume record cleared.");
    } catch (error) {
      console.error("Failed to delete record:", error);
      toast.error("Error purging record.");
    }
  }

  if (loading) return (
    <div className="p-8 flex items-center justify-center min-h-[60vh]">
      <Loader2 className="w-6 h-6 text-slate-300 animate-spin" />
    </div>
  );

  if (analyzing && !resume) {
    return (
      <div className="p-6 lg:p-8 max-w-2xl mx-auto text-center py-20">
        <Loader2 className="w-8 h-8 text-indigo-600 animate-spin mx-auto mb-4" />
        <h2 className="text-lg font-semibold text-slate-900">Analyzing your resume...</h2>
        <p className="text-sm text-slate-500 mt-2">Extracting skills, experience, and career profile</p>
      </div>
    );
  }

  const score = resume?.quality_score ?? 0;
  const coreSkills = resume?.core_skills || [];
  const familiarSkills = resume?.familiar_skills || [];
  const displaySummary = resume?.summary || resume?.professional_summary || 'No summary available.';
  const displaySeniority = resume?.seniority || resume?.level || '--';
  const strengths = resume?.strengths || [];
  const improvements = resume?.improvements || resume?.enhancements || [];
  const jobTitles = resume?.job_titles || [];
  const industries = resume?.industries || [];
  const yearsExp = resume?.years_experience || 0;

  return (
    <div className="p-6 lg:p-8 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">My Resume</h1>
          <p className="text-sm text-slate-500">{resume ? resume.file_name : "Upload a resume"}</p>
        </div>
        <div className="flex items-center gap-2">
          {resume && (
            <Button variant="outline" size="sm" className="text-red-500 hover:text-red-600" onClick={handleDeleteResume}>
              <Trash2 className="w-4 h-4 mr-1.5" /> Clear
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}>
            <Upload className="w-4 h-4 mr-1.5" /> {resume ? 'Upload New' : 'Choose File'}
          </Button>
        </div>
        <input ref={fileInputRef} type="file" accept=".pdf" className="hidden" onChange={handleFileSelect} />
      </div>

      {/* Empty state */}
      {!resume && (
        <div
          onDragEnter={handleDrag}
          onDragOver={handleDrag}
          onDragLeave={handleDrag}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className="flex flex-col items-center justify-center border-2 border-dashed rounded-xl p-16 cursor-pointer border-slate-300 hover:border-indigo-400 bg-white hover:bg-indigo-50/10 transition-colors"
        >
          <Upload className="w-7 h-7 text-indigo-600 mb-4" />
          <p className="font-medium text-slate-800">Drop resume here or click to browse</p>
          <p className="text-sm text-slate-400 mt-1">PDF format only</p>
        </div>
      )}

      {/* Resume content */}
      {resume && (
        <div className="space-y-6">
          {/* Row 1: Quality Score + Summary */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <Card className="p-6 flex flex-col items-center justify-center text-center">
              <span className="text-xs font-semibold uppercase text-slate-400 mb-4">Quality Score</span>
              <div className="relative w-32 h-32 flex items-center justify-center mb-2">
                <svg className="w-full h-full transform -rotate-90" viewBox="0 0 36 36">
                  <path
                    className="text-slate-100"
                    strokeWidth="3"
                    stroke="currentColor"
                    fill="none"
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  />
                  <path
                    className="text-indigo-600"
                    strokeDasharray={`${score}, 100`}
                    strokeWidth="3"
                    strokeLinecap="round"
                    stroke="currentColor"
                    fill="none"
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  />
                </svg>
                <div className="absolute text-3xl font-bold text-slate-800">{score}</div>
              </div>
              <p className="text-xs text-slate-400 mt-1">out of 100</p>
            </Card>

            <Card className="p-6 md:col-span-2">
              <h3 className="text-sm font-semibold text-slate-900 uppercase mb-3">Professional Summary</h3>
              <p className="text-sm text-slate-600 leading-relaxed">{displaySummary}</p>
              <div className="flex gap-8 border-t border-slate-100 pt-4 mt-4">
                <div>
                  <p className="text-2xl font-bold text-slate-800 capitalize">{displaySeniority}</p>
                  <p className="text-xs text-slate-400 font-medium">Seniority Level</p>
                </div>
                {yearsExp > 0 && (
                  <div>
                    <p className="text-2xl font-bold text-slate-800">{yearsExp}+</p>
                    <p className="text-xs text-slate-400 font-medium">Years Experience</p>
                  </div>
                )}
              </div>
            </Card>
          </div>

          {/* Row 2: Core Skills + Familiar Skills */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card className="p-6">
              <h3 className="text-sm font-semibold text-slate-900 uppercase mb-4">
                Core Skills ({coreSkills.length})
              </h3>
              {coreSkills.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {coreSkills.map((skill, i) => (
                    <Badge key={i} className="bg-indigo-600 text-white border-indigo-600 hover:bg-indigo-700">
                      <Star className="w-3 h-3 mr-1" />
                      {skill}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-400 italic">No core skills identified.</p>
              )}
              <p className="text-xs text-slate-400 mt-4">Daily-use skills with demonstrated deep expertise</p>
            </Card>

            <Card className="p-6">
              <h3 className="text-sm font-semibold text-slate-900 uppercase mb-4">
                Familiar Skills ({familiarSkills.length})
              </h3>
              {familiarSkills.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {familiarSkills.map((skill, i) => (
                    <Badge key={i} variant="outline" className="text-slate-600 border-slate-300">
                      {skill}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-400 italic">No familiar skills identified.</p>
              )}
              <p className="text-xs text-slate-400 mt-4">Tools/tech with working knowledge but not primary expertise</p>
            </Card>
          </div>

          {/* Row 3: Strengths + Improvements */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card className="p-6">
              <h3 className="text-sm font-semibold text-slate-900 uppercase mb-4">
                Profile Strengths ({strengths.length})
              </h3>
              {strengths.length > 0 ? (
                <ul className="space-y-2">
                  {strengths.map((s, i) => (
                    <li key={i} className="text-sm text-slate-600 flex gap-2">
                      <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0 mt-0.5" />
                      {s}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-slate-400 italic">No strengths recorded yet.</p>
              )}
            </Card>

            <Card className="p-6">
              <h3 className="text-sm font-semibold text-slate-900 uppercase mb-4">
                Recommended Enhancements ({improvements.length})
              </h3>
              {improvements.length > 0 ? (
                <ul className="space-y-2">
                  {improvements.map((imp, i) => (
                    <li key={i} className="text-sm text-slate-600 flex gap-2">
                      <Lightbulb className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
                      {imp}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-slate-400 italic">No recommendations yet.</p>
              )}
            </Card>
          </div>

          {/* Row 4: Past Roles + Industries */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {jobTitles.length > 0 && (
              <Card className="p-6">
                <h3 className="text-sm font-semibold text-slate-900 uppercase mb-4">
                  Past Roles ({jobTitles.length})
                </h3>
                <div className="flex flex-wrap gap-2">
                  {jobTitles.map((title, i) => (
                    <Badge key={i} variant="outline" className="text-slate-600 border-slate-300">
                      <Briefcase className="w-3 h-3 mr-1" />
                      {title}
                    </Badge>
                  ))}
                </div>
              </Card>
            )}

            {industries.length > 0 && (
              <Card className="p-6">
                <h3 className="text-sm font-semibold text-slate-900 uppercase mb-4">
                  Industries ({industries.length})
                </h3>
                <div className="flex flex-wrap gap-2">
                  {industries.map((ind, i) => (
                    <Badge key={i} variant="secondary" className="bg-slate-100 text-slate-700">
                      <Building2 className="w-3 h-3 mr-1" />
                      {ind}
                    </Badge>
                  ))}
                </div>
              </Card>
            )}

            {jobTitles.length === 0 && industries.length > 0 && <div />}
            {industries.length === 0 && jobTitles.length > 0 && <div />}
          </div>

          {/* Row 5: Raw Text (collapsible with copy button) */}
          {resume?.raw_text && (
            <Card className="p-6">
              <details>
                <summary className="text-sm font-semibold text-slate-900 uppercase cursor-pointer hover:text-indigo-600 transition-colors flex items-center justify-between">
                  <span>Full Extracted Text</span>
                  <button
                    onClick={async (e) => {
                      e.preventDefault();
                      try {
                        await navigator.clipboard.writeText(resume.raw_text);
                        setCopied(true);
                        toast.success('Text copied to clipboard');
                        setTimeout(() => setCopied(false), 2000);
                      } catch {
                        toast.error('Failed to copy');
                      }
                    }}
                    className="flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-indigo-600 bg-slate-100 hover:bg-indigo-50 px-2.5 py-1 rounded-md transition-colors"
                  >
                    {copied ? (
                      <>
                        <Check className="w-3.5 h-3.5" />
                        Copied
                      </>
                    ) : (
                      <>
                        <Copy className="w-3.5 h-3.5" />
                        Copy
                      </>
                    )}
                  </button>
                </summary>
                <pre className="text-xs text-slate-500 whitespace-pre-wrap max-h-96 overflow-y-auto mt-3 p-4 bg-slate-50 rounded-lg border border-slate-100">
                  {resume.raw_text}
                </pre>
              </details>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}