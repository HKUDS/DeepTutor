"use client";

/* eslint-disable react-hooks/exhaustive-deps */

import { useState, useEffect, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  FileText,
  Search,
  Upload,
  Loader2,
  Eye,
  Download,
  Database,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiUrl } from "@/lib/api";
import Modal from "@/components/ui/Modal";

interface KnowledgeBaseInfo {
  name: string;
  display_name?: string;
  is_default: boolean;
  statistics: {
    raw_documents: number;
    images: number;
    content_lists: number;
    rag_initialized: boolean;
  };
}

interface KbFile {
  name: string;
  display_name?: string;
  size: number;
  modified_at: string;
  status: "indexed" | "processing" | "failed" | "pending";
  error?: string;
}

export default function KnowledgeBaseDetailPage() {
  const params = useParams();
  const router = useRouter();
  const kbName = decodeURIComponent(params.name as string);

  const [kbInfo, setKbInfo] = useState<KnowledgeBaseInfo | null>(null);
  const [files, setFiles] = useState<KbFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [filesLoading, setFilesLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0); // Mock progress
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewContent, setPreviewContent] = useState("");
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewFilename, setPreviewFilename] = useState("");

  // File upload
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchKbDetails();
    fetchFiles();
  }, [kbName]);

  const fetchKbDetails = async () => {
    try {
      const res = await fetch(apiUrl(`/api/v1/knowledge/${kbName}`));
      if (!res.ok) throw new Error("Failed to fetch details");
      const data = await res.json();
      setKbInfo(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const fetchFiles = async () => {
    try {
      setFilesLoading(true);
      const res = await fetch(apiUrl(`/api/v1/knowledge/${kbName}/files`));
      if (!res.ok) throw new Error("Failed to fetch files");
      const data = await res.json();
      setFiles(data || []);
    } catch (err) {
      console.error(err);
    } finally {
      setFilesLoading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;

    setUploading(true);
    const formData = new FormData();
    Array.from(e.target.files).forEach((file) => {
      formData.append("files", file);
    });

    try {
      // Mock progress
      const interval = setInterval(() => {
        setUploadProgress((prev) => Math.min(prev + 10, 90));
      }, 200);

      const res = await fetch(apiUrl(`/api/v1/knowledge/${kbName}/upload`), {
        method: "POST",
        body: formData,
      });

      clearInterval(interval);
      setUploadProgress(100);

      if (!res.ok) throw new Error("Upload failed");

      // Success
      setTimeout(() => {
        setUploading(false);
        setUploadProgress(0);
        if (fileInputRef.current) fileInputRef.current.value = "";
        fetchFiles();
        fetchKbDetails(); // Update stats
      }, 500);
    } catch (err) {
      console.error(err);
      alert("上传失败");
      setUploading(false);
    }
  };

  const handleDownloadFile = async (filename: string) => {
    const encodedName = encodeURIComponent(filename);
    window.open(
      apiUrl(`/api/v1/knowledge/${kbName}/file/${encodedName}`),
      "_blank",
    );
  };

  const handlePreviewFile = async (filename: string) => {
    const isMarkdown =
      filename.toLowerCase().endsWith(".md") ||
      filename.toLowerCase().endsWith(".markdown");
    setPreviewFilename(filename);
    setPreviewContent("");
    setPreviewError(null);
    setPreviewOpen(true);

    if (!isMarkdown) {
      setPreviewError("仅支持 Markdown 文件预览");
      return;
    }

    setPreviewLoading(true);
    try {
      const encodedName = encodeURIComponent(filename);
      const res = await fetch(
        apiUrl(`/api/v1/knowledge/${kbName}/file/${encodedName}`),
      );
      if (!res.ok) throw new Error("Failed to load file");
      const text = await res.text();
      setPreviewContent(text);
    } catch (err) {
      console.error(err);
      setPreviewError("读取文件失败");
    } finally {
      setPreviewLoading(false);
    }
  };

  const filteredFiles = files.filter(
    (f) =>
      f.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (f.display_name || "").toLowerCase().includes(searchTerm.toLowerCase()),
  );

  const formatSize = (bytes: number) => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  };

  const formatDate = (isoString: string) => {
    return new Date(isoString).toLocaleString();
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-600" />
      </div>
    );
  }

  if (!kbInfo) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4">
        <h2 className="text-xl font-bold">未找到知识库</h2>
        <button
          onClick={() => router.push("/knowledge")}
          className="text-indigo-600 hover:underline"
        >
          返回列表
        </button>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-slate-50 overflow-hidden">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-8 py-5 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.push("/knowledge")}
            className="p-2 hover:bg-slate-100 rounded-lg text-slate-500 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
              {kbInfo.display_name || kbInfo.name}
              {kbInfo.is_default && (
                <span className="px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-600 text-xs font-bold border border-indigo-100">
                  默认
                </span>
              )}
            </h1>
            <div className="flex items-center gap-4 mt-1 text-sm text-slate-500">
              <span className="flex items-center gap-1.5">
                <FileText className="w-4 h-4" />
                {kbInfo.statistics.raw_documents} 文档
              </span>
              <span className="flex items-center gap-1.5">
                <Database className="w-4 h-4" />
                {kbInfo.statistics.rag_initialized ? "已索引" : "未索引"}
              </span>
            </div>
          </div>
        </div>

        <div className="flex gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder="搜索文件..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-9 pr-4 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 w-64"
            />
          </div>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors shadow-sm disabled:opacity-50 disabled:cursor-not-allowed font-medium text-sm"
          >
            {uploading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                上传中 {uploadProgress}%
              </>
            ) : (
              <>
                <Upload className="w-4 h-4" />
                上传文档
              </>
            )}
          </button>
          <input
            type="file"
            ref={fileInputRef}
            className="hidden"
            multiple
            onChange={handleFileUpload}
          />
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-8">
        <div className="max-w-6xl mx-auto">
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th className="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    文件名
                  </th>
                  <th className="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider w-32">
                    大小
                  </th>
                  <th className="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider w-48">
                    修改时间
                  </th>
                  <th className="px-6 py-4 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider w-32">
                    状态
                  </th>
                  <th className="px-6 py-4 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider w-24">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filesLoading ? (
                  <tr>
                    <td
                      colSpan={5}
                      className="px-6 py-12 text-center text-slate-500"
                    >
                      <Loader2 className="w-8 h-8 animate-spin mx-auto mb-2 text-indigo-500" />
                      加载文件列表中...
                    </td>
                  </tr>
                ) : filteredFiles.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-6 py-12 text-center">
                      <div className="w-16 h-16 bg-slate-50 rounded-full flex items-center justify-center mx-auto mb-3">
                        <FileText className="w-8 h-8 text-slate-300" />
                      </div>
                      <p className="text-slate-500 font-medium">暂无文档</p>
                      <p className="text-sm text-slate-400 mt-1">
                        点击右上角上传按钮添加文档
                      </p>
                    </td>
                  </tr>
                ) : (
                  filteredFiles.map((file) => (
                    <tr
                      key={file.name}
                      className="hover:bg-slate-50 transition-colors group"
                    >
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded bg-indigo-50 text-indigo-600 flex items-center justify-center shrink-0">
                            <FileText className="w-4 h-4" />
                          </div>
                          <div className="font-medium text-slate-900 group-hover:text-indigo-600 transition-colors truncate max-w-sm">
                            {file.display_name || file.name}
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4 text-sm text-slate-500 font-mono">
                        {formatSize(file.size)}
                      </td>
                      <td className="px-6 py-4 text-sm text-slate-500">
                        {formatDate(file.modified_at)}
                      </td>
                      <td className="px-6 py-4">
                        {file.status === "indexed" ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-100">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                            已索引
                          </span>
                        ) : file.status === "processing" ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-100">
                            <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                            处理中
                          </span>
                        ) : file.status === "failed" ? (
                          <span
                            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-red-50 text-red-700 border border-red-100 cursor-help"
                            title={file.error || "处理失败"}
                          >
                            <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                            失败
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-100">
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                            待处理
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => handlePreviewFile(file.name)}
                            className="p-2 text-slate-400 hover:text-indigo-600 hover:bg-slate-200 rounded-lg transition-colors"
                            title="查看"
                          >
                            <Eye className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleDownloadFile(file.name)}
                            className="p-2 text-slate-400 hover:text-indigo-600 hover:bg-slate-200 rounded-lg transition-colors"
                            title="下载"
                          >
                            <Download className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <Modal
        isOpen={previewOpen}
        onClose={() => setPreviewOpen(false)}
        title={previewFilename || "文件预览"}
        size="xl"
      >
        <div className="p-6 max-h-[70vh] overflow-y-auto">
          {previewLoading ? (
            <div className="flex items-center justify-center py-10 text-slate-500">
              <Loader2 className="w-6 h-6 animate-spin text-indigo-500 mr-2" />
              加载中...
            </div>
          ) : previewError ? (
            <div className="text-sm text-rose-600">{previewError}</div>
          ) : (
            <div className="prose prose-slate max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {previewContent || "暂无内容"}
              </ReactMarkdown>
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}
