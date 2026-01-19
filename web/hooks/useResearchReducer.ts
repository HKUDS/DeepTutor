import { useReducer } from "react";
import {
  ResearchState,
  ResearchEvent,
  TaskState,
  ThoughtEntry,
  ResearchLogEntry,
  TopicBlock,
  ReportOutline,
} from "../types/research";

export const initialResearchState: ResearchState = {
  global: {
    stage: "idle",
    startTime: 0,
    totalBlocks: 0,
    completedBlocks: 0,
  },
  planning: {
    originalTopic: "",
    optimizedTopic: "",
    subTopics: [],
    progress: "",
  },
  tasks: {},
  activeTaskIds: [],
  executionMode: "series",
  reporting: {
    outline: null,
    progress: "",
  },
  logs: [],
};

// Helper to create a log entry
const createLog = (
  message: string,
  type: ResearchLogEntry["type"] = "info",
): ResearchLogEntry => ({
  id: Math.random().toString(36).substring(7),
  timestamp: Date.now(),
  type,
  message,
});

// Helper to ensure a task exists in state
const ensureTask = (
  state: ResearchState,
  blockId: string,
  topic: string = "",
): TaskState => {
  if (state.tasks[blockId]) {
    return state.tasks[blockId];
  }
  return {
    id: blockId,
    topic: topic,
    status: "pending",
    iteration: 0,
    maxIterations: 0, // Will be updated from events
    currentAction: "Initialized",
    toolsUsed: [],
    thoughts: [],
    lastUpdate: Date.now(),
  };
};

// Helper to add a thought to a task
const addThought = (task: TaskState, thought: ThoughtEntry): TaskState => ({
  ...task,
  thoughts: [...task.thoughts, thought],
  lastUpdate: Date.now(),
});

export const researchReducer = (
  state: ResearchState,
  event: ResearchEvent,
): ResearchState => {
  // Common log handling
  const newLog = event.type === "log" ? createLog(event.content) : null;
  const logs = newLog ? [...state.logs, newLog] : state.logs;

  switch (event.type) {
    // --- Planning Phase ---
    case "planning_started":
      return {
        ...state,
        global: {
          ...state.global,
          stage: "planning",
          startTime: Date.now(),
        },
        planning: {
          ...state.planning,
          originalTopic: event.user_topic || "",
          progress: "Initializing planning...",
        },
        logs: [...logs, createLog("Planning started")],
      };

    case "rephrase_completed":
      return {
        ...state,
        planning: {
          ...state.planning,
          optimizedTopic: event.optimized_topic,
          progress: "Topic rephrased",
        },
        logs: [...logs, createLog(`Topic optimized: ${event.optimized_topic}`)],
      };

    case "decompose_started":
      return {
        ...state,
        planning: {
          ...state.planning,
          progress: `Decomposing into sub-topics (Mode: ${event.mode})...`,
        },
      };

    case "decompose_completed":
      return {
        ...state,
        planning: {
          ...state.planning,
          progress: `Decomposition completed (${event.generated_subtopics} subtopics)`,
        },
        logs: [
          ...logs,
          createLog(`Generated ${event.generated_subtopics} subtopics`),
        ],
      };

    case "queue_seeded":
      // Backend sends seeded blocks one by one or we might just wait for planning_completed
      // But we can capture the total blocks here if available
      return {
        ...state,
        global: {
          ...state.global,
          totalBlocks: event.total_blocks || state.global.totalBlocks,
        },
        planning: {
          ...state.planning,
          progress: `Added topic: ${event.sub_topic}`,
        },
      };

    case "planning_completed":
      return {
        ...state,
        global: {
          ...state.global,
          totalBlocks: event.total_blocks,
        },
        logs: [...logs, createLog("Planning phase completed", "success")],
      };

    // --- Researching Phase ---
    case "researching_started":
      // Initialize tasks based on blocks we might have received or just prepare
      return {
        ...state,
        global: {
          ...state.global,
          stage: "researching",
          totalBlocks: event.total_blocks || state.global.totalBlocks,
        },
        executionMode: event.execution_mode || "series",
        logs: [
          ...logs,
          createLog(
            `Research started in ${event.execution_mode || "series"} mode`,
          ),
        ],
      };

    case "block_started": {
      const blockId = event.block_id;
      const subTopic = event.sub_topic;
      const task = ensureTask(state, blockId, subTopic);

      return {
        ...state,
        tasks: {
          ...state.tasks,
          [blockId]: {
            ...task,
            status: "running",
            topic: subTopic || task.topic,
            lastUpdate: Date.now(),
          },
        },
        // In series mode, update global current block tracking if provided
        global: {
          ...state.global,
          ...(event.current_block
            ? { completedBlocks: event.current_block - 1 }
            : {}),
        },
        logs: [...logs, createLog(`Started research on: ${subTopic}`)],
      };
    }

    case "parallel_status_update": {
      // Bulk update for parallel mode
      const activeTasks = event.active_tasks || [];
      const updatedTasks = { ...state.tasks };
      const activeIds: string[] = [];

      activeTasks.forEach((t: any) => {
        const blockId = t.block_id;
        activeIds.push(blockId);

        const existingTask =
          updatedTasks[blockId] || ensureTask(state, blockId, t.sub_topic);

        // Don't overwrite status if task is already completed or failed
        const shouldUpdateStatus =
          existingTask.status !== "completed" &&
          existingTask.status !== "failed";

        updatedTasks[blockId] = {
          ...existingTask,
          status: shouldUpdateStatus ? "running" : existingTask.status,
          iteration: t.iteration,
          maxIterations: t.max_iterations,
          currentAction: shouldUpdateStatus
            ? t.current_query
              ? `Query: ${t.current_query}`
              : t.status
            : existingTask.currentAction,
          currentTool: t.current_tool,
          currentQuery: t.current_query,
          lastUpdate: Date.now(),
        };
      });

      // Also filter out completed/failed tasks from activeIds
      const filteredActiveIds = activeIds.filter((id) => {
        const task = updatedTasks[id];
        return task && task.status !== "completed" && task.status !== "failed";
      });

      return {
        ...state,
        tasks: updatedTasks,
        activeTaskIds: filteredActiveIds,
        global: {
          ...state.global,
          completedBlocks:
            event.completed_count || state.global.completedBlocks,
        },
      };
    }

    case "block_completed": {
      const blockId = event.block_id;
      return {
        ...state,
        tasks: {
          ...state.tasks,
          [blockId]: {
            ...(state.tasks[blockId] || ensureTask(state, blockId)),
            status: "completed",
            currentAction: "Research completed",
            lastUpdate: Date.now(),
            toolsUsed:
              event.tools_used || state.tasks[blockId]?.toolsUsed || [],
          },
        },
        // Remove completed task from activeTaskIds
        activeTaskIds: state.activeTaskIds.filter((id) => id !== blockId),
        global: {
          ...state.global,
          completedBlocks: (state.global.completedBlocks || 0) + 1,
        },
        logs: [...logs, createLog(`Completed: ${event.sub_topic}`, "success")],
      };
    }

    case "block_failed": {
      const blockId = event.block_id;
      return {
        ...state,
        tasks: {
          ...state.tasks,
          [blockId]: {
            ...(state.tasks[blockId] || ensureTask(state, blockId)),
            status: "failed",
            currentAction: `Failed: ${event.error}`,
            lastUpdate: Date.now(),
            thoughts: [
              ...(state.tasks[blockId]?.thoughts || []),
              { type: "error", content: event.error, timestamp: Date.now() },
            ],
          },
        },
        // Remove failed task from activeTaskIds
        activeTaskIds: state.activeTaskIds.filter((id) => id !== blockId),
        logs: [
          ...logs,
          createLog(`Failed: ${event.sub_topic} - ${event.error}`, "error"),
        ],
      };
    }

    // --- Agent Details (Thoughts) ---
    case "checking_sufficiency": {
      const blockId = event.block_id;
      if (!blockId || !state.tasks[blockId]) return state;

      const task = state.tasks[blockId];
      return {
        ...state,
        tasks: {
          ...state.tasks,
          [blockId]: addThought(task, {
            type: "sufficiency",
            content: `Iteration ${event.iteration}: Checking knowledge sufficiency...`,
            timestamp: Date.now(),
          }),
        },
      };
    }

    case "knowledge_sufficient": {
      const blockId = event.block_id;
      if (!blockId || !state.tasks[blockId]) return state;

      const task = state.tasks[blockId];
      return {
        ...state,
        tasks: {
          ...state.tasks,
          [blockId]: addThought(task, {
            type: "sufficiency",
            content: `Knowledge sufficient. Reason: ${event.reason}`,
            timestamp: Date.now(),
          }),
        },
      };
    }

    case "generating_query": {
      const blockId = event.block_id;
      if (!blockId || !state.tasks[blockId]) return state;

      return {
        ...state,
        tasks: {
          ...state.tasks,
          [blockId]: {
            ...state.tasks[blockId],
            currentAction: "Generating query plan...",
          },
        },
      };
    }

    case "tool_calling": {
      const blockId = event.block_id;
      if (!blockId || !state.tasks[blockId]) return state;

      const task = state.tasks[blockId];
      return {
        ...state,
        tasks: {
          ...state.tasks,
          [blockId]: {
            ...addThought(task, {
              type: "plan",
              content: `Rationale: ${event.rationale}`,
              timestamp: Date.now(),
            }),
            currentAction: `Using ${event.tool_type}: ${event.query}`,
            toolsUsed: Array.from(
              new Set([...task.toolsUsed, event.tool_type]),
            ),
          },
        },
      };
    }

    case "tool_completed": {
      const blockId = event.block_id;
      if (!blockId || !state.tasks[blockId]) return state;

      const task = state.tasks[blockId];
      return {
        ...state,
        tasks: {
          ...state.tasks,
          [blockId]: addThought(task, {
            type: "tool_call",
            content: `Used ${event.tool_type} with query "${event.query}"`,
            timestamp: Date.now(),
          }),
        },
      };
    }

    case "processing_notes": {
      const blockId = event.block_id;
      if (!blockId || !state.tasks[blockId]) return state;

      return {
        ...state,
        tasks: {
          ...state.tasks,
          [blockId]: {
            ...state.tasks[blockId],
            currentAction: "Processing notes and citations...",
          },
        },
      };
    }

    case "new_topic_added": {
      // A new topic was discovered during research
      const newTopic = event.new_topic;
      const newBlockId = `block_${Math.random().toString(36).substr(2, 9)}`; // Backend should provide ID theoretically but usually it adds to queue end
      // If backend provides ID in event, use it. But typically new_topic_added event might lack ID until queue_seeded.
      // Assuming queue_seeded will follow or handle this.
      // But for UI feedback:
      return {
        ...state,
        logs: [...logs, createLog(`New topic discovered: ${newTopic}`, "info")],
      };
    }

    case "researching_completed":
      return {
        ...state,
        global: {
          ...state.global,
          completedBlocks: state.global.totalBlocks,
        },
        logs: [...logs, createLog("Research phase completed", "success")],
      };

    // --- Reporting Phase ---
    case "reporting_started":
      return {
        ...state,
        global: {
          ...state.global,
          stage: "reporting",
        },
        reporting: {
          ...state.reporting,
          progress: "Starting report generation...",
        },
        logs: [...logs, createLog("Reporting started")],
      };

    case "deduplicate_completed":
      return {
        ...state,
        reporting: {
          ...state.reporting,
          progress: `Deduplication completed. Kept ${event.kept_blocks} blocks.`,
        },
      };

    case "outline_completed":
      // Determine the generated outline sections count
      const outlineData = event as any; // Full outline payload might be in event
      // But usually event just says outline_completed.
      // If the outline data is passed in payload:
      return {
        ...state,
        reporting: {
          ...state.reporting,
          progress: `Outline generated (${event.sections} sections).`,
          totalSections: event.sections ? event.sections + 2 : undefined, // +2 for intro and conclusion
          // If the event contained the outline structure, we would update it here
          // But usually the client fetches report or it's pushed separately.
          // Assuming for now just progress update.
        },
        logs: [...logs, createLog("Report outline generated")],
      };

    case "writing_section":
      return {
        ...state,
        reporting: {
          ...state.reporting,
          progress: `Writing: ${event.current_section}`,
          currentSection: event.current_section,
          sectionIndex: event.section_index,
          totalSections: event.total_sections,
        },
      };

    case "writing_completed":
      return {
        ...state,
        reporting: {
          ...state.reporting,
          progress: "Report writing completed.",
        },
        logs: [...logs, createLog("Report writing completed", "success")],
      };

    case "reporting_completed":
      return {
        ...state,
        global: {
          ...state.global,
          stage: "completed",
        },
        reporting: {
          ...state.reporting,
          wordCount: event.word_count,
          sectionCount: event.sections,
          citationCount: event.citations,
          generatedReport: event.report, // Store the generated report
          progress: "All done!",
        },
        logs: [
          ...logs,
          createLog(
            `Research finished! Report: ${event.word_count} words`,
            "success",
          ),
        ],
      };

    case "error":
      return {
        ...state,
        logs: [
          ...logs,
          createLog(event.content || "An error occurred", "error"),
        ],
      };

    default:
      return { ...state, logs };
  }
};

export const useResearchReducer = () => {
  return useReducer(researchReducer, initialResearchState);
};
