import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { base44 } from '@/api/base44Client';
import { toast } from 'sonner';
import { generateInterviewPrep } from '@/lib/jobUtils';
import { Loader2, ArrowLeft, FileText, Briefcase, CheckCircle2, XCircle, Copy } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

export default function InterviewPrep() {
  const { jobId } = useParams();          // get job id from URL
  const [job, setJob] = useState(null);
  const [resume, setResume] = useState(null);
  const [contextDocs, setContextDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [prepData, setPrepData] = useState(null);

  useEffect(() => {
    loadData();
  }, [jobId]);

  async function loadData() {
    try {
      const [jobs, resumes, contexts] = await Promise.all([
        base44.entities.Job.filter({ dismissed: false }, '-created_date', 500),
        base44.entities.Resume.filter({ active: true }),
        base44.entities.ContextDocument.list('-created_date', 50),
      ]);

      const foundJob = jobs.find((j) => j.id === jobId);
      if (!foundJob) {
        toast.error('Job not found');
        setLoading(false);
        return;
      }
      setJob(foundJob);
      setResume(resumes[0] || null);
      setContextDocs(contexts);
    } catch (error) {
      console.error('Failed to load interview prep data:', error);
      toast.error('Error loading data.');
    } finally {
      setLoading(false);
    }
  }

  async function handleGeneratePrep() {
    if (!resume) {
      toast.error('Please upload an active resume first.');
      return;
    }
    setGenerating(true);
    try {
      const result = await generateInterviewPrep(job, resume, contextDocs);
      setPrepData(result);
      toast.success('Interview prep generated!');
    } catch (error) {
      console.error('Failed to generate interview prep:', error);
      toast.error(error.message || 'Generation failed');
    } finally {
      setGenerating(false);
    }
  }

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-6 h-6 text-slate-300 animate-spin" />
      </div>
    );
  }

  if (!job) {
    return (
      <div className="p-8 text-center">
        <p className="text-slate-500">Job not found.</p>
        <Button asChild variant="outline" className="mt-4">
          <Link to="/jobs"><ArrowLeft className="w-4 h-4 mr-2" /> Back to Jobs</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="p-6 lg:p-8 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <Link to="/jobs" className="text-sm text-slate-500 hover:text-indigo-600 inline-flex items-center gap-1 mb-2">
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Jobs
          </Link>
          <h1 className="text-2xl font-bold text-slate-900">Interview Prep</h1>
          <p className="text-sm text-slate-600 mt-1">
            {job.title} at {job.company || 'Unknown Company'}
          </p>
        </div>
        <Button onClick={handleGeneratePrep} disabled={generating} className="bg-indigo-600 hover:bg-indigo-700">
          {generating ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <FileText className="w-4 h-4 mr-2" />}
          {generating ? 'Generating...' : 'Generate Prep'}
        </Button>
      </div>

      {/* Job summary card */}
      <Card className="p-5 mb-6 border-slate-200">
        <h2 className="text-sm font-semibold text-slate-900 uppercase mb-2 flex items-center gap-2">
          <Briefcase className="w-4 h-4 text-indigo-600" /> Job Details
        </h2>
        <p className="text-sm text-slate-600 whitespace-pre-wrap">{job.description || 'No description available.'}</p>
        {job.skills_required?.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {job.skills_required.map((skill, i) => (
              <Badge key={i} variant="outline" className="text-xs">{skill}</Badge>
            ))}
          </div>
        )}
      </Card>

      {/* Generated content */}
      {prepData ? (
        <div className="space-y-6">
          {/* Questions */}
          <Card className="p-6">
            <h2 className="text-lg font-semibold text-slate-900 mb-4">Interview Questions</h2>
            <div className="space-y-4">
              {prepData.questions?.length > 0 ? (
                prepData.questions.map((q, idx) => (
                  <div key={idx} className="border border-slate-200 rounded-lg p-4">
                    <div className="flex items-start gap-2 mb-2">
                      <Badge className="bg-indigo-50 text-indigo-700 border-indigo-200 text-xs uppercase">
                        {q.type || 'General'}
                      </Badge>
                      <h3 className="text-sm font-medium text-slate-800">{q.question}</h3>
                    </div>
                    <p className="text-sm text-slate-600 bg-slate-50 p-3 rounded-lg whitespace-pre-wrap">
                      {q.suggested_answer || 'No suggested answer provided.'}
                    </p>
                  </div>
                ))
              ) : (
                <p className="text-sm text-slate-500">No questions generated yet.</p>
              )}
            </div>
          </Card>

          {/* Cover letter */}
          <Card className="p-6">
            <h2 className="text-lg font-semibold text-slate-900 mb-2">Suggested Cover Letter</h2>
            <p className="text-sm text-slate-600 whitespace-pre-wrap leading-relaxed">
              {prepData.cover_letter || 'No cover letter generated.'}
            </p>
          </Card>
        </div>
      ) : (
        <Card className="p-8 text-center border-dashed border-slate-200">
          <FileText className="w-8 h-8 text-slate-300 mx-auto mb-2" />
          <p className="text-sm text-slate-500">Click "Generate Prep" to create tailored interview questions and a cover letter.</p>
        </Card>
      )}
    </div>
  );
}