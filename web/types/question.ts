// Question generation types for the Dashboard UI

export interface QuestionFocus {
  id: string;
  focus: string;
  scenario_hint?: string;
}

export interface QuestionValidation {
  decision?:
    | "approve"
    | "request_modification"
    | "request_regeneration"
    | "extended";
  issues?: string[];
  suggestions?: string[];
  reasoning?: string;
  // Extension analysis fields (for extended questions)
  kb_connection?: string;
  extended_aspect?: string;
  // Relevance analysis fields (for custom mode)
  relevance?: "high" | "partial";
  kb_coverage?: string;
  extension_points?: string;
}

// Question Plan (for custom mode)
export interface QuestionPlan {
  knowledge_point: string;
  difficulty: string;
  question_type: string;
  num_questions: number;
  focuses: QuestionFocus[];
}

export interface GeneratedQuestion {
  question_type?: string;
  type?: string;
  question: string;
  options?: Record<string, string>;
  correct_answer: string;
  explanation: string;
  knowledge_point?: string;
}

export interface QuestionResult {
  success: boolean;
  question_id: string;
  question: GeneratedQuestion;
  validation: QuestionValidation;
  rounds: number;
  focus?: QuestionFocus;
  // Extended question indicator
  extended?: boolean;
}

export interface QuestionFailure {
  question_id: string;
  error: string;
  reason?: string;
}

export interface QuestionTask {
  id: string;
  focus: string;
  scenarioHint?: string;
  status:
    | "pending"
    | "generating"
    | "analyzing"
    | "validating"
    | "done"
    | "error";
  round?: number;
  maxRounds?: number;
  result?: QuestionResult;
  error?: string;
  extended?: boolean; // Whether this is an extended question
  lastUpdate: number;
}

export interface QuestionProgress {
  stage:
    | "idle"
    | "planning"
    | "researching"
    | "generating"
    | "complete"
    // Mimic mode stages
    | "uploading"
    | "parsing"
    | "extracting";
  status?: string;
  message?: string; // Progress message for display
  // Planning
  queries?: string[];
  // Generating
  current?: number;
  total?: number;
  round?: number;
  maxRounds?: number;
  // Focuses
  focuses?: QuestionFocus[];
  // Mimic mode - reference questions info
  referenceQuestions?: Array<{
    number: string;
    preview: string;
  }>;
}

export interface QuestionState {
  // Global state
  global: {
    stage:
      | "idle"
      | "planning"
      | "researching"
      | "generating"
      | "complete"
      // Mimic mode stages
      | "uploading"
      | "parsing"
      | "extracting";
    startTime: number;
    totalQuestions: number;
    completedQuestions: number;
    failedQuestions: number;
    extendedQuestions: number; // Count of extended questions
    topic?: string;
    // Mimic mode specific
    mode?: "custom" | "mimic";
    referenceQuestions?: Array<{
      number: string;
      preview: string;
    }>;
  };
  // Planning stage
  planning: {
    topic: string;
    difficulty: string;
    questionType: string;
    queries: string[];
    progress: string;
  };
  // Question tasks
  tasks: Record<string, QuestionTask>;
  activeTaskIds: string[];
  // Results
  results: QuestionResult[];
  failures: QuestionFailure[];
  // Shared context summary (truncated for display)
  sharedContextPreview?: string;
  // Sub-focuses assigned to each question
  subFocuses: QuestionFocus[];
  // Logs
  logs: QuestionLogEntry[];
}

export interface QuestionLogEntry {
  id: string;
  timestamp: number;
  type: "info" | "success" | "warning" | "error" | "system";
  content: string;
}

// WebSocket Event Types
export type QuestionEventType =
  // Progress events
  | "progress"
  | "question_update"
  | "question_result"
  | "question_error"
  | "batch_summary"
  // Custom mode events
  | "knowledge_saved"
  | "plan_ready"
  // Mimic mode events
  | "summary" // Mimic mode final summary
  // Status events
  | "status"
  | "agent_status"
  | "token_stats"
  // Result events
  | "result"
  | "complete"
  | "error"
  | "log";

export interface QuestionEvent {
  type: QuestionEventType;
  // Progress fields
  stage?: string;
  status?: string;
  message?: string; // Progress message for display
  // Question-specific
  question_id?: string;
  question?: GeneratedQuestion;
  validation?: QuestionValidation;
  rounds?: number;
  focus?: QuestionFocus;
  // Batch fields
  requested?: number;
  completed?: number;
  failed?: number;
  total?: number;
  current?: number;
  sub_focuses?: QuestionFocus[];
  focuses?: QuestionFocus[];
  queries?: string[];
  // Custom mode fields
  plan?: QuestionPlan;
  // Mimic mode fields
  reference_question?: string;
  reference_number?: string;
  reference_preview?: string;
  reference_questions?: Array<{
    number: string;
    preview: string;
  }>;
  total_questions?: number;
  successful?: number;
  total_reference?: number;
  output_file?: string;
  // Generic
  content?: string;
  index?: number;
  success?: boolean;
  error?: string;
  [key: string]: any;
}

// Token stats
export interface QuestionTokenStats {
  model: string;
  calls: number;
  tokens: number;
  input_tokens: number;
  output_tokens: number;
  cost: number;
}

// Agent status
export interface QuestionAgentStatus {
  [key: string]: "pending" | "running" | "done" | "error";
}

// Config for question generation
export interface QuestionConfig {
  topic: string;
  difficulty: "easy" | "medium" | "hard";
  type: "choice" | "written";
  count: number;
  selectedKb: string;
}

// Mimic mode config
export interface MimicConfig {
  uploadedFile: File | null;
  paperPath: string;
  selectedKb: string;
  maxQuestions?: number;
}
