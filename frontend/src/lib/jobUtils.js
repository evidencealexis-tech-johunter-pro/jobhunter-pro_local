import { base44 } from '@/api/base44Client';

// ============================================================
//  SINGLE-CALL RESUME ANALYZER (strict, fast, accurate)
//  One Gemini call does everything — with strict skill filtering
// ============================================================

export async function analyzeResume(fileUrl) {
  const analysis = await base44.integrations.Core.InvokeLLM({
    prompt: `You are an expert recruiter. Analyze this resume with PRECISION and SKEPTICISM.

CRITICAL RULES:
1. ONLY extract skills the candidate has DEMONSTRABLY used in a job, project, or certification. Do NOT list skills that appear only in a generic "Skills" section without evidence of actual use.
2. IGNORE: operating systems (Windows, MacOS, Linux), Microsoft Office, Google Workspace, spoken languages (English, Spanish), soft skills without evidence (communication, teamwork, leadership).
3. Categorize skills into two tiers:
   - core_skills: Tools/technologies/methodologies used daily or deep expertise (max 8)
   - familiar_skills: Working knowledge but not primary (max 10)
4. If the resume mentions a skill in passing (e.g., "attended a React workshop" but no React job), DO NOT include it.
5. Quality score 0-100: be harsh — deduct for generic language, no metrics, buzzwords. Most real resumes score 50-70.

Return ONLY valid JSON with this exact structure. No markdown, no extra text.`,
    file_urls: [fileUrl],
    response_json_schema: {
      type: "object",
      properties: {
        is_resume: { type: "boolean" },
        raw_text: { type: "string" },
        core_skills: { type: "array", items: { type: "string" } },
        familiar_skills: { type: "array", items: { type: "string" } },
        years_experience: { type: "number" },
        seniority: { type: "string", enum: ["Entry Level", "Junior", "Mid-level", "Senior", "Principal", "Director"] },
        job_titles: { type: "array", items: { type: "string" } },
        industries: { type: "array", items: { type: "string" } },
        summary: { type: "string" },
        strengths: { type: "array", items: { type: "string" } },
        improvements: { type: "array", items: { type: "string" } },
        quality_score: { type: "number" }
      }
    }
  });

  if (analysis.is_resume === false) {
    throw new Error('This file does not appear to be a resume. Please upload a valid resume document.');
  }

  // Merge core + familiar into a flat skills array (core first = higher priority)
  return {
    ...analysis,
    skills: [
      ...(analysis.core_skills || []),
      ...(analysis.familiar_skills || [])
    ],
    core_skills: analysis.core_skills || [],
    familiar_skills: analysis.familiar_skills || [],
  };
}

// ============================================================
//  JOB SCORING (unchanged)
// ============================================================

export async function scoreJob(job, resume, weights) {
  const result = await base44.integrations.Core.InvokeLLM({
    prompt: `You are an expert job matching system. Compare this candidate against this job posting and score each dimension from 0-100.

CANDIDATE PROFILE:
- Core skills (daily use, deep expertise): ${(resume.core_skills || resume.skills || []).join(', ') || 'None detected'}
- Familiar skills (working knowledge): ${(resume.familiar_skills || []).join(', ') || 'None detected'}
- Years of experience: ${resume.years_experience ?? 'unknown'}
- Seniority level: ${resume.seniority || 'unknown'}
- Industries: ${(resume.industries || []).join(', ') || 'None detected'}
- Professional summary: ${resume.summary || 'N/A'}

JOB DETAILS:
- Title: ${job.title}
- Company: ${job.company || 'Unknown'}
- Description: ${job.description || 'No description available'}
- Location: ${job.location || 'Not specified'}

Score each dimension 0-100:
1. skills_score: Core skills count 3x more than familiar. If 4/5 core skills match, score 75+ even if familiar don't.
2. semantic_score: Overall career trajectory alignment.
3. seniority_score: Level match.
4. domain_score: Industry match.

Also return: skill_gaps, match_reasons, required_skills, job_seniority, job_domain, legitimacy_score, red_flags.`,
    response_json_schema: {
      type: "object",
      properties: {
        skills_score: { type: "number" },
        semantic_score: { type: "number" },
        seniority_score: { type: "number" },
        domain_score: { type: "number" },
        skill_gaps: { type: "array", items: { type: "string" } },
        match_reasons: { type: "array", items: { type: "string" } },
        required_skills: { type: "array", items: { type: "string" } },
        job_seniority: { type: "string" },
        job_domain: { type: "string" },
        legitimacy_score: { type: "number" },
        red_flags: { type: "array", items: { type: "string" } }
      }
    }
  });

  const sw = weights?.skills_weight ?? 40;
  const semw = weights?.semantic_weight ?? 25;
  const snrw = weights?.seniority_weight ?? 15;
  const dw = weights?.domain_weight ?? 20;
  const totalWeight = sw + semw + snrw + dw || 1;

  const matchScore = Math.round(
    ((result.skills_score || 0) * sw +
     (result.semantic_score || 0) * semw +
     (result.seniority_score || 0) * snrw +
     (result.domain_score || 0) * dw) / totalWeight
  );

  return { ...result, match_score: matchScore };
}

// ============================================================
//  UTILITIES (unchanged)
// ============================================================

export function generateFingerprint(job) {
  const str = `${job.title || ''}|${job.company || ''}|${job.url || ''}`.toLowerCase().replace(/\s+/g, ' ').trim();
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash;
  }
  return Math.abs(hash).toString(36);
}

export function exportToCSV(jobs) {
  const headers = ['Title', 'Company', 'Match Score', 'Why It Matches', 'Skills Missing', 'Location', 'Seniority', 'Status', 'Link'];
  const rows = jobs.map(j => [
    j.title || '',
    j.company || '',
    j.match_score ?? '',
    (j.match_reasons || []).join('; '),
    (j.skill_gaps || []).join('; '),
    j.location || '',
    j.seniority || '',
    j.status || '',
    j.url || ''
  ]);

  const csv = [headers, ...rows].map(row =>
    row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(',')
  ).join('\n');

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `jobhunter-matches-${new Date().toISOString().split('T')[0]}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function scoreColor(score) {
  if (score >= 85) return 'text-emerald-600 bg-emerald-50 border-emerald-200';
  if (score >= 70) return 'text-indigo-600 bg-indigo-50 border-indigo-200';
  if (score >= 50) return 'text-amber-600 bg-amber-50 border-amber-200';
  return 'text-slate-500 bg-slate-50 border-slate-200';
}

export function legitimacyColor(score) {
  if (score >= 75) return { label: 'Legitimate', className: 'text-emerald-600 bg-emerald-50 border-emerald-200', dot: 'bg-emerald-500' };
  if (score >= 50) return { label: 'Caution', className: 'text-amber-600 bg-amber-50 border-amber-200', dot: 'bg-amber-500' };
  return { label: 'Likely Ghost', className: 'text-red-600 bg-red-50 border-red-200', dot: 'bg-red-500' };
}

export async function analyzeContextDoc(fileUrl) {
  const result = await base44.integrations.Core.InvokeLLM({
    prompt: `Analyze this professional document for a job seeker's context library.

Extract: title, doc_type (Performance Review/Project/Code Sample/Design Doc/Other), summary, raw_text.`,
    file_urls: [fileUrl],
    response_json_schema: {
      type: "object",
      properties: {
        title: { type: "string" },
        doc_type: { type: "string" },
        summary: { type: "string" },
        raw_text: { type: "string" }
      }
    }
  });
  return result;
}

export async function generateInterviewPrep(job, resume, contextDocs) {
  const contextSummary = (contextDocs || [])
    .map((d, i) => `[Document ${i + 1}: ${d.title} (${d.doc_type})]\n${d.summary || ''}`)
    .join('\n\n');

  const result = await base44.integrations.Core.InvokeLLM({
    prompt: `You are an expert interview coach. Prepare for this job:

JOB: ${job.title} at ${job.company || 'Unknown'}
Description: ${job.description || 'N/A'}
Required skills: ${(job.skills_required || []).join(', ') || 'N/A'}

CANDIDATE: Skills: ${(resume?.skills || []).join(', ')}, Years: ${resume?.years_experience ?? 'N/A'}, Seniority: ${resume?.seniority || 'N/A'}
Additional context: ${contextSummary || 'None'}

Generate 10 interview questions with suggested answers, plus a 300-400 word cover letter.`,
    response_json_schema: {
      type: "object",
      properties: {
        questions: {
          type: "array",
          items: {
            type: "object",
            properties: {
              question: { type: "string" },
              type: { type: "string" },
              suggested_answer: { type: "string" }
            }
          }
        },
        cover_letter: { type: "string" }
      }
    }
  });
  return result;
}

export async function generateUpskillRoadmap(skill, resume) {
  const result = await base44.integrations.Core.InvokeLLM({
    prompt: `Create a 5-7 day learning roadmap to learn "${skill}" for someone with skills: ${(resume?.skills || []).join(', ')}. Return overview and days array.`,
    response_json_schema: {
      type: "object",
      properties: {
        overview: { type: "string" },
        days: {
          type: "array",
          items: {
            type: "object",
            properties: {
              day: { type: "number" },
              focus: { type: "string" },
              tasks: { type: "array", items: { type: "string" } },
              project: { type: "string" }
            }
          }
        }
      }
    }
  });
  return result;
}