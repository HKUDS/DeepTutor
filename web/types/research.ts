export interface TopicBlock {
  block_id: string;
  sub_topic: string;
  overview: string;
  status: "pending" | "researching" | "completed" | "failed";
  tool_traces: ToolTrace[];
  iteration_count: number;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, any>;
}

export interface ToolTrace {
  tool_id?: string; // Optional as it might not be populated in all contexts
  citation_id?: string;
  tool_type: string;
  query: string;
  raw_answer: string;
  summary: string;
  timestamp?: string;
  raw_answer_truncated?: boolean;
  raw_answer_original_size?: number;
}

export interface ThoughtEntry {
  type: "sufficiency" | "plan" | "tool_call" | "note" | "error";
  content: string;
  metadata?: Record<string, any>;
  timestamp: number;
}

export interface TaskState {
  id: string;
  topic: string;
  status: "pending" | "running" | "completed" | "failed";
  iteration: number;
  maxIterations: number;
  currentAction: string; // e.g. "Searching web for..."
  toolsUsed: string[];
  thoughts: ThoughtEntry[]; // Record chain of thought (Sufficiency -> Query -> Tool)
  lastUpdate: number;
  // Specific fields for parallel mode display
  currentTool?: string;
  currentQuery?: string;
}

export interface OutlineSubsection {
  title: string;
  instruction: string;
}

export interface OutlineSection {
  title: string;
  instruction: string;
  block_id?: string;
  subsections?: OutlineSubsection[];
}

export interface ReportOutline {
  title: string;
  introduction: string;
  introduction_instruction?: string;
  sections: OutlineSection[];
  conclusion: string;
  conclusion_instruction?: string;
}

export interface LogEntry {
  id: string;
  timestamp: number;
  type: "info" | "success" | "warning" | "error";
  message: string;
  details?: any;
}

export interface ResearchState {
  global: {
    stage: "idle" | "planning" | "researching" | "reporting" | "completed";
    startTime: number;
    totalBlocks: number;
    completedBlocks: number;
    topic?: string; // Main topic
  };
  // Planning stage data
  planning: {
    originalTopic: string;
    optimizedTopic: string;
    subTopics: TopicBlock[];
    progress: string; // Current planning step description
  };
  // Research stage data (Core)
  tasks: Record<string, TaskState>; // block_id -> detailed state
  activeTaskIds: string[]; // IDs of tasks currently running in parallel
  executionMode: "series" | "parallel";

  // Reporting stage data
  reporting: {
    outline: ReportOutline | null;
    progress: string; // Current reporting step description
    generatedReport?: string;
    wordCount?: number;
    sectionCount?: number;
    citationCount?: number;
    // Current writing progress
    currentSection?: string;
    sectionIndex?: number;
    totalSections?: number;
  };
  logs: LogEntry[]; // Global log stream
}

// WebSocket Event Types
export type ResearchEventType =
  // Planning
  | "planning_started"
  | "rephrase_completed"
  | "decompose_started"
  | "decompose_completed"
  | "queue_seeded"
  | "planning_completed"

  // Researching - Pipeline
  | "researching_started"
  | "parallel_status_update"
  | "block_started"
  | "block_completed"
  | "block_failed"
  | "researching_completed"

  // Researching - Agent
  | "iteration_started"
  | "checking_sufficiency"
  | "knowledge_sufficient"
  | "generating_query"
  | "tool_calling"
  | "tool_completed"
  | "processing_notes"
  | "iteration_completed"
  | "new_topic_added"

  // Reporting
  | "reporting_started"
  | "deduplicate_completed"
  | "outline_completed"
  | "writing_section"
  | "writing_completed"
  | "reporting_completed"

  // System
  | "log"
  | "error"
  | "status"
  | "reset";

export interface ResearchEvent {
  type: ResearchEventType;
  stage?: string;
  status?: string;
  timestamp?: string;
  research_id?: string;
  [key: string]: any; // Payload
}
