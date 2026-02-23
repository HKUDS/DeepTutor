import React from "react";
import { TaskState } from "../../types/research";
import {
  CheckCircle2,
  Loader2,
  Clock,
  AlertCircle,
  Database,
  Globe,
  GraduationCap,
  Code,
  FileSearch,
  Activity,
} from "lucide-react";

interface TaskGridProps {
  tasks: Record<string, TaskState>;
  activeTaskIds: string[];
  selectedTaskId: string | null;
  onTaskSelect: (taskId: string) => void;
}

const getStatusLabel = (status: TaskState["status"]) => {
  switch (status) {
    case "completed":
      return "已完成";
    case "running":
      return "运行中";
    case "failed":
      return "失败";
    default:
      return "待开始";
  }
};

const getStatusIcon = (status: TaskState["status"]) => {
  switch (status) {
    case "completed":
      return (
        <CheckCircle2 className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
      );
    case "running":
      return (
        <Loader2 className="w-4 h-4 text-indigo-500 dark:text-indigo-400 animate-spin" />
      );
    case "failed":
      return <AlertCircle className="w-4 h-4 text-red-500 dark:text-red-400" />;
    default:
      return <Clock className="w-4 h-4 text-slate-400 dark:text-slate-500" />;
  }
};

const getToolIcon = (toolName: string) => {
  if (toolName.includes("rag"))
    return <Database className="w-3 h-3 text-blue-500 dark:text-blue-400" />;
  if (toolName.includes("web"))
    return <Globe className="w-3 h-3 text-green-500 dark:text-green-400" />;
  if (toolName.includes("paper"))
    return (
      <GraduationCap className="w-3 h-3 text-purple-500 dark:text-purple-400" />
    );
  if (toolName.includes("code"))
    return <Code className="w-3 h-3 text-orange-500 dark:text-orange-400" />;
  return <FileSearch className="w-3 h-3 text-slate-500 dark:text-slate-400" />;
};

export const TaskGrid: React.FC<TaskGridProps> = ({
  tasks,
  activeTaskIds,
  selectedTaskId,
  onTaskSelect,
}) => {
  // Sort tasks: Active first, then running, then pending, then completed/failed
  const sortedTasks = Object.values(tasks).sort((a, b) => {
    const score = (task: TaskState) => {
      if (activeTaskIds.includes(task.id)) return 4;
      if (task.status === "running") return 3;
      if (task.status === "pending") return 2;
      return 1;
    };
    return score(b) - score(a);
  });

  if (sortedTasks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-8 text-slate-400 dark:text-slate-500 border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-xl">
        <Activity className="w-8 h-8 mb-2 opacity-50" />
        <p className="text-sm">尚未初始化任务</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      {sortedTasks.map((task) => {
        const isActive = activeTaskIds.includes(task.id);
        const isSelected = selectedTaskId === task.id;

        return (
          <div
            key={task.id}
            onClick={() => onTaskSelect(task.id)}
            className={`
              relative p-4 rounded-xl border cursor-pointer transition-all duration-200
              hover:shadow-md flex flex-col gap-3
              ${
                isSelected
                  ? "bg-indigo-50/50 dark:bg-indigo-900/30 border-indigo-500 ring-1 ring-indigo-500"
                  : "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:border-indigo-300 dark:hover:border-indigo-600"
              }
              ${isActive ? "shadow-sm" : "opacity-90"}
            `}
          >
            {/* Active Indicator Pulse */}
            {isActive && (
              <div className="absolute top-4 right-4 flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
              </div>
            )}

            <div className="flex items-start gap-3">
              <div
                className={`p-2 rounded-lg shrink-0 ${
                  task.status === "completed"
                    ? "bg-emerald-50 dark:bg-emerald-900/40"
                    : task.status === "failed"
                      ? "bg-red-50 dark:bg-red-900/40"
                      : isActive
                        ? "bg-indigo-50 dark:bg-indigo-900/40"
                        : "bg-slate-100 dark:bg-slate-700"
                }`}
              >
                {getStatusIcon(task.status)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-2">
                  <h4
                    className="text-sm font-semibold text-slate-800 dark:text-slate-100 line-clamp-1 pr-4"
                    title={task.topic}
                  >
                    {task.topic}
                  </h4>
                </div>
                <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded-full font-medium uppercase tracking-wide shrink-0 ${
                      task.status === "completed"
                        ? "bg-emerald-100 dark:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300"
                        : task.status === "failed"
                          ? "bg-red-100 dark:bg-red-900/50 text-red-700 dark:text-red-300"
                          : task.status === "running"
                            ? "bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300"
                            : "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400"
                    }`}
                  >
                    {getStatusLabel(task.status)}
                  </span>
                  {task.maxIterations > 0 && (
                    <span className="text-[10px] text-slate-400 dark:text-slate-500 font-medium whitespace-nowrap shrink-0">
                      {task.iteration}/{task.maxIterations}
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Current Action / Summary */}
            <div className="bg-slate-50 dark:bg-slate-700 rounded-lg p-2.5 min-h-[48px] border border-slate-100 dark:border-slate-600">
              <p className="text-xs text-slate-600 dark:text-slate-300 line-clamp-2 leading-relaxed">
                <span className="font-medium text-slate-400 dark:text-slate-500 mr-1">
                  当前动作：
                </span>
                {task.currentAction || "等待开始..."}
              </p>
            </div>

            {/* Tools Used Footer */}
            {task.toolsUsed.length > 0 && (
              <div className="flex items-center gap-1.5 overflow-hidden">
                <span className="text-[10px] text-slate-400 dark:text-slate-500 uppercase font-medium mr-1">
                  工具：
                </span>
                {task.toolsUsed.slice(0, 5).map((tool, idx) => (
                  <div
                    key={idx}
                    className="p-1.5 bg-white dark:bg-slate-700 rounded-md border border-slate-200 dark:border-slate-600 shadow-sm"
                    title={tool}
                  >
                    {getToolIcon(tool)}
                  </div>
                ))}
                {task.toolsUsed.length > 5 && (
                  <span className="text-[10px] text-slate-400 dark:text-slate-500 ml-1 font-medium">
                    +{task.toolsUsed.length - 5}
                  </span>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};
