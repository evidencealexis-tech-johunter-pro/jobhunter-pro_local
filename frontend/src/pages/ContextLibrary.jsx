import React, { useState, useEffect, useRef } from 'react';
import { base44 } from '@/api/base44Client';
import { toast } from 'sonner';
import { analyzeContextDoc } from '@/lib/jobUtils';
import { Loader2, Upload, Trash2, FileText, FolderOpen, FileCode, Star, FileCheck } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

const typeIcons = {
  'Performance Review': Star,
  'Project': FileCheck,
  'Code Sample': FileCode,
  'Design Doc': FileText,
  'Other': FileText,
};

export default function ContextLibrary() {
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [docs, setDocs] = useState([]);
  const fileInputRef = useRef(null);

  useEffect(() => {
    loadDocs();
  }, []);

  async function loadDocs() {
    try {
      const list = await base44.entities.ContextDocument.list('-created_date', 50);
      setDocs(list);
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
    }
  }

  async function handleFileSelect(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    // --- Duplicate prevention: block re-uploading a file with the same name ---
    try {
      const existingDocs = await base44.entities.ContextDocument.list('-created_date', 50);
      const duplicate = existingDocs.find((d) => d.file_name === file.name);
      if (duplicate) {
        toast.error(`"${file.name}" is already in your context library. Remove the existing one first if you want to re-add it.`);
        if (fileInputRef.current) fileInputRef.current.value = '';
        return;
      }
    } catch (error) {
      console.error('Failed to check for duplicate document:', error);
      // Don't block the upload just because the duplicate check itself failed
    }

    setUploading(true);
    const tid = toast.loading('Uploading document...');
    try {
      const { file_url } = await base44.integrations.Core.UploadFile({ file });
      toast.success('Analyzing document...', { id: tid });
      const analysis = await analyzeContextDoc(file_url);
      await base44.entities.ContextDocument.create({
        title: analysis.title || file.name,
        doc_type: analysis.doc_type || 'Other',
        file_url,
        file_name: file.name,
        raw_text: analysis.raw_text || '',
        summary: analysis.summary || '',
      });
      toast.success('Document added to your context library.', { id: tid });
      await loadDocs();
    } catch (error) {
      toast.error('Failed to add document.', { id: tid });
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  async function handleDelete(doc) {
    try {
      await base44.entities.ContextDocument.delete(doc.id);
      setDocs((prev) => prev.filter((d) => d.id !== doc.id));
      toast.success('Document removed.');
    } catch (error) {
      toast.error('Failed to remove document.');
    }
  }

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-6 h-6 text-slate-300 animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6 lg:p-8 max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Context Library</h1>
        <p className="text-sm text-slate-500 mt-1">
          Add past reviews, project docs, and code samples to give the AI richer material for interview prep and cover letters
        </p>
      </div>

      {/* Upload area */}
      <Card
        className="p-8 mb-6 border-2 border-dashed border-slate-300 hover:border-indigo-400 hover:bg-indigo-50/30 transition-colors cursor-pointer text-center"
        onClick={() => !uploading && fileInputRef.current?.click()}
      >
        {uploading ? (
          <>
            <Loader2 className="w-8 h-8 text-indigo-600 animate-spin mx-auto mb-3" />
            <p className="text-sm font-medium text-slate-700">Analyzing document...</p>
            <p className="text-xs text-slate-500 mt-0.5">Extracting title, type, and summary</p>
          </>
        ) : (
          <>
            <div className="w-12 h-12 rounded-xl bg-indigo-50 flex items-center justify-center mx-auto mb-3">
              <Upload className="w-6 h-6 text-indigo-600" />
            </div>
            <h3 className="text-base font-semibold text-slate-900 mb-1">Add a document</h3>
            <p className="text-sm text-slate-500">PDF works best — performance reviews, project READMEs, code samples, design docs</p>
          </>
        )}
        <input ref={fileInputRef} type="file" accept=".pdf,.doc,.docx,.txt,.md" className="hidden" onChange={handleFileSelect} />
      </Card>

      {/* Documents */}
      {docs.length === 0 ? (
        <Card className="p-10 text-center border-dashed border-slate-200">
          <FolderOpen className="w-10 h-10 text-slate-300 mx-auto mb-3" />
          <p className="text-sm text-slate-400">Your context library is empty. Add documents above.</p>
        </Card>
      ) : (
        <div className="space-y-3">
          {docs.map((doc) => {
            const Icon = typeIcons[doc.doc_type] || FileText;
            return (
              <Card key={doc.id} className="p-4 border-slate-200">
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center shrink-0">
                    <Icon className="w-5 h-5 text-slate-500" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <h3 className="text-sm font-semibold text-slate-900 truncate">{doc.title}</h3>
                      <Badge variant="outline" className="text-xs shrink-0">{doc.doc_type}</Badge>
                    </div>
                    {doc.summary && <p className="text-xs text-slate-500 leading-relaxed">{doc.summary}</p>}
                    {doc.file_name && <p className="text-xs text-slate-400 mt-1">{doc.file_name}</p>}
                  </div>
                  <Button variant="ghost" size="icon" className="h-8 w-8 text-slate-400 hover:text-red-500 shrink-0" onClick={() => handleDelete(doc)}>
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}