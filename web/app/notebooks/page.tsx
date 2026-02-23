"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  Plus,
  Search,
  BookOpen,
  Book,
  Clock,
  FileText,
  Trash2,
  Edit3,
  X,
  MoreVertical,
} from "lucide-react";
import { apiUrl } from "@/lib/api";

interface NotebookSummary {
  id: string;
  name: string;
  description: string;
  created_at: number;
  updated_at: number;
  record_count: number;
  color: string;
  icon: string;
}

const COLORS = [
  "#3B82F6", // blue
  "#8B5CF6", // purple
  "#EC4899", // pink
  "#EF4444", // red
  "#F97316", // orange
  "#EAB308", // yellow
  "#22C55E", // green
  "#14B8A6", // teal
  "#06B6D4", // cyan
  "#6366F1", // indigo
];

export default function NotebooksPage() {
  const router = useRouter();
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");

  // Modal states
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(
    null,
  );

  // Form states
  const [newNotebook, setNewNotebook] = useState({
    name: "",
    description: "",
    color: "#3B82F6",
  });
  const [editingNotebook, setEditingNotebook] = useState<{
    id: string;
    name: string;
    description: string;
    color: string;
  } | null>(null);

  // Context menu
  const [contextMenu, setContextMenu] = useState<{
    id: string;
    x: number;
    y: number;
  } | null>(null);
  const contextMenuRef = useRef<HTMLDivElement | null>(null);

  // Fetch notebooks
  useEffect(() => {
    fetchNotebooks();
  }, []);

  // Close context menu when clicking outside
  useEffect(() => {
    if (!contextMenu) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (contextMenuRef.current?.contains(target)) return;
      setContextMenu(null);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [contextMenu]);

  const fetchNotebooks = async () => {
    try {
      const res = await fetch(apiUrl("/api/v1/notebook/list"));
      const data = await res.json();
      setNotebooks(data.notebooks || []);
    } catch (err) {
      console.error("Failed to fetch notebooks:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateNotebook = async () => {
    if (!newNotebook.name.trim()) return;

    try {
      const res = await fetch(apiUrl("/api/v1/notebook/create"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newNotebook),
      });
      const data = await res.json();
      if (data.success) {
        fetchNotebooks();
        setShowCreateModal(false);
        setNewNotebook({ name: "", description: "", color: "#3B82F6" });
      }
    } catch (err) {
      console.error("Failed to create notebook:", err);
    }
  };

  const handleUpdateNotebook = async () => {
    if (!editingNotebook || !editingNotebook.name.trim()) return;

    try {
      const res = await fetch(
        apiUrl(`/api/v1/notebook/${editingNotebook.id}`),
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: editingNotebook.name,
            description: editingNotebook.description,
            color: editingNotebook.color,
          }),
        },
      );
      const data = await res.json();
      if (data.success) {
        fetchNotebooks();
        setShowEditModal(false);
        setEditingNotebook(null);
      }
    } catch (err) {
      console.error("Failed to update notebook:", err);
    }
  };

  const handleDeleteNotebook = async (notebookId: string) => {
    try {
      const res = await fetch(apiUrl(`/api/v1/notebook/${notebookId}`), {
        method: "DELETE",
      });
      const data = await res.json();
      if (data.success) {
        fetchNotebooks();
        setShowDeleteConfirm(null);
      }
    } catch (err) {
      console.error("Failed to delete notebook:", err);
    }
  };

  const handleContextMenu = (e: React.MouseEvent, notebookId: string) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ id: notebookId, x: e.clientX, y: e.clientY });
  };

  const filteredNotebooks = notebooks.filter(
    (nb) =>
      nb.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      nb.description.toLowerCase().includes(searchTerm.toLowerCase()),
  );

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 p-8">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-3xl font-bold text-slate-900 tracking-tight flex items-center gap-3 mb-2">
              <Book className="w-8 h-8 text-blue-600" />
              我的笔记本
            </h1>
            <p className="text-sm text-slate-500 mt-2">
              创建和管理你的研究笔记本
            </p>
          </div>
        </div>

        {/* Search Bar */}
        <div className="relative max-w-md">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
          <input
            type="text"
            placeholder="搜索笔记本..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-12 pr-4 py-3 bg-white border border-slate-200 rounded-xl text-slate-900 placeholder:text-slate-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none shadow-sm"
          />
        </div>
      </div>

      {/* Notebook Grid */}
      <div>
        {loading ? (
          <div className="flex items-center justify-center h-64">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
            {/* Create New Notebook Card */}
            <button
              onClick={() => setShowCreateModal(true)}
              className="group h-48 rounded-2xl border-2 border-dashed border-slate-300 bg-white/50 hover:border-blue-400 hover:bg-blue-50/50 transition-all flex flex-col items-center justify-center gap-3"
            >
              <div className="w-14 h-14 rounded-full bg-slate-100 group-hover:bg-blue-100 flex items-center justify-center transition-colors">
                <Plus className="w-7 h-7 text-slate-400 group-hover:text-blue-600" />
              </div>
              <span className="text-slate-500 group-hover:text-blue-600 font-medium">
                新建笔记本
              </span>
            </button>

            {/* Notebook Cards */}
            {filteredNotebooks.map((nb) => (
              <div
                key={nb.id}
                onClick={() => router.push(`/notebooks/${nb.id}`)}
                onContextMenu={(e) => handleContextMenu(e, nb.id)}
                className="group relative h-48 rounded-2xl bg-white border border-slate-200 hover:border-slate-300 hover:shadow-lg transition-all cursor-pointer overflow-hidden"
              >
                {/* Color Bar */}
                <div
                  className="absolute top-0 left-0 right-0 h-1.5"
                  style={{ backgroundColor: nb.color }}
                />

                {/* Content */}
                <div className="p-5 h-full flex flex-col">
                  {/* Icon & Title */}
                  <div className="flex items-start gap-3 mb-3">
                    <div
                      className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
                      style={{
                        backgroundColor: `${nb.color}15`,
                        color: nb.color,
                      }}
                    >
                      <BookOpen className="w-5 h-5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="font-semibold text-slate-900 truncate">
                        {nb.name}
                      </h3>
                      {nb.description && (
                        <p className="text-sm text-slate-500 truncate mt-0.5">
                          {nb.description}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Spacer */}
                  <div className="flex-1" />

                  {/* Footer */}
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span className="flex items-center gap-1">
                      <FileText className="w-3.5 h-3.5" />
                      {nb.record_count} 条记录
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="w-3.5 h-3.5" />
                      {new Date(nb.updated_at * 1000).toLocaleDateString()}
                    </span>
                  </div>
                </div>

                {/* Hover Actions */}
                <div className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity z-10">
                  <button
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      const rect = e.currentTarget.getBoundingClientRect();
                      setContextMenu({
                        id: nb.id,
                        x: rect.left,
                        y: rect.bottom + 4,
                      });
                    }}
                    className="p-1.5 rounded-lg bg-white/80 hover:bg-white border border-slate-200 shadow-sm"
                  >
                    <MoreVertical className="w-4 h-4 text-slate-500" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Empty State */}
        {!loading && filteredNotebooks.length === 0 && searchTerm && (
          <div className="text-center py-16">
            <Search className="w-12 h-12 text-slate-300 mx-auto mb-4" />
            <p className="text-slate-500">没有找到匹配的笔记本</p>
          </div>
        )}
      </div>

      {/* Context Menu */}
      {contextMenu && (
        <div
          ref={contextMenuRef}
          className="fixed z-50 bg-white rounded-xl shadow-lg border border-slate-200 py-2 min-w-[140px]"
          style={{ top: contextMenu.y, left: contextMenu.x }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => {
              const nb = notebooks.find((n) => n.id === contextMenu.id);
              if (nb) {
                setEditingNotebook({
                  id: nb.id,
                  name: nb.name,
                  description: nb.description,
                  color: nb.color,
                });
                setShowEditModal(true);
              }
              setContextMenu(null);
            }}
            className="w-full px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 flex items-center gap-2"
          >
            <Edit3 className="w-4 h-4" />
            编辑
          </button>
          <button
            onClick={() => {
              setShowDeleteConfirm(contextMenu.id);
              setContextMenu(null);
            }}
            className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 flex items-center gap-2"
          >
            <Trash2 className="w-4 h-4" />
            删除
          </button>
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-slate-900">新建笔记本</h2>
              <button
                onClick={() => setShowCreateModal(false)}
                className="p-2 hover:bg-slate-100 rounded-lg"
              >
                <X className="w-5 h-5 text-slate-500" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  名称
                </label>
                <input
                  type="text"
                  value={newNotebook.name}
                  onChange={(e) =>
                    setNewNotebook({ ...newNotebook, name: e.target.value })
                  }
                  placeholder="输入笔记本名称"
                  className="w-full px-4 py-3 border border-slate-200 rounded-xl text-slate-900 placeholder:text-slate-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  描述（可选）
                </label>
                <textarea
                  value={newNotebook.description}
                  onChange={(e) =>
                    setNewNotebook({
                      ...newNotebook,
                      description: e.target.value,
                    })
                  }
                  placeholder="简短描述这个笔记本的内容"
                  rows={3}
                  className="w-full px-4 py-3 border border-slate-200 rounded-xl text-slate-900 placeholder:text-slate-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none resize-none"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">
                  颜色
                </label>
                <div className="flex gap-2 flex-wrap">
                  {COLORS.map((color) => (
                    <button
                      key={color}
                      onClick={() => setNewNotebook({ ...newNotebook, color })}
                      className={`w-8 h-8 rounded-full transition-all ${
                        newNotebook.color === color
                          ? "ring-2 ring-offset-2 ring-slate-400 scale-110"
                          : "hover:scale-110"
                      }`}
                      style={{ backgroundColor: color }}
                    />
                  ))}
                </div>
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setShowCreateModal(false)}
                className="flex-1 px-4 py-3 border border-slate-200 rounded-xl text-slate-700 font-medium hover:bg-slate-50 transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleCreateNotebook}
                disabled={!newNotebook.name.trim()}
                className="flex-1 px-4 py-3 bg-blue-600 text-white rounded-xl font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                创建
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {showEditModal && editingNotebook && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-slate-900">编辑笔记本</h2>
              <button
                onClick={() => {
                  setShowEditModal(false);
                  setEditingNotebook(null);
                }}
                className="p-2 hover:bg-slate-100 rounded-lg"
              >
                <X className="w-5 h-5 text-slate-500" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  名称
                </label>
                <input
                  type="text"
                  value={editingNotebook.name}
                  onChange={(e) =>
                    setEditingNotebook({
                      ...editingNotebook,
                      name: e.target.value,
                    })
                  }
                  className="w-full px-4 py-3 border border-slate-200 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  描述
                </label>
                <textarea
                  value={editingNotebook.description}
                  onChange={(e) =>
                    setEditingNotebook({
                      ...editingNotebook,
                      description: e.target.value,
                    })
                  }
                  rows={3}
                  className="w-full px-4 py-3 border border-slate-200 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none resize-none"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">
                  颜色
                </label>
                <div className="flex gap-2 flex-wrap">
                  {COLORS.map((color) => (
                    <button
                      key={color}
                      onClick={() =>
                        setEditingNotebook({ ...editingNotebook, color })
                      }
                      className={`w-8 h-8 rounded-full transition-all ${
                        editingNotebook.color === color
                          ? "ring-2 ring-offset-2 ring-slate-400 scale-110"
                          : "hover:scale-110"
                      }`}
                      style={{ backgroundColor: color }}
                    />
                  ))}
                </div>
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => {
                  setShowEditModal(false);
                  setEditingNotebook(null);
                }}
                className="flex-1 px-4 py-3 border border-slate-200 rounded-xl text-slate-700 font-medium hover:bg-slate-50 transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleUpdateNotebook}
                disabled={!editingNotebook.name.trim()}
                className="flex-1 px-4 py-3 bg-blue-600 text-white rounded-xl font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm mx-4 p-6">
            <div className="text-center">
              <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-4">
                <Trash2 className="w-6 h-6 text-red-600" />
              </div>
              <h3 className="text-lg font-bold text-slate-900 mb-2">
                确认删除？
              </h3>
              <p className="text-slate-500 text-sm mb-6">
                删除后无法恢复，笔记本中的所有记录都将被删除。
              </p>
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => setShowDeleteConfirm(null)}
                className="flex-1 px-4 py-3 border border-slate-200 rounded-xl text-slate-700 font-medium hover:bg-slate-50 transition-colors"
              >
                取消
              </button>
              <button
                onClick={() => handleDeleteNotebook(showDeleteConfirm)}
                className="flex-1 px-4 py-3 bg-red-600 text-white rounded-xl font-medium hover:bg-red-700 transition-colors"
              >
                删除
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
