import type {
  BookReference,
  LLMSelection,
  MasteryCardAnswer,
  MasteryCardSkip,
  MemoryReferences,
  NotebookReference,
  OutgoingAttachment,
  ReadingReference,
  ReadingViewport,
  TimedMediaViewport,
} from "@/contracts/generated/turn-protocol";

export interface StartTurnInput {
  content: string;
  capability?: string | null;
  sessionId?: string | null;
  tools?: string[] | null;
  knowledgeBases?: string[];
  language?: string | null;
  capabilityConfig?: Record<string, unknown>;
  allowedCapabilityConfigKeys?: readonly string[];
  attachments?: OutgoingAttachment[];
  notebookReferences?: NotebookReference[];
  historyReferences?: string[];
  partnerGroupReferences?: Array<Record<string, unknown>>;
  questionNotebookReferences?: number[];
  bookReferences?: BookReference[];
  readingReferences?: ReadingReference[];
  memoryReferences?: MemoryReferences;
  skills?: string[];
  persona?: string | null;
  llmSelection?: LLMSelection | null;
  workspaceMode?: string | null;
  masteryPathId?: string | null;
  masterySessionMode?: string | null;
  masteryPathLeaseManaged?: boolean;
  masteryAnswer?: MasteryCardAnswer | null;
  masterySkip?: MasteryCardSkip | null;
  readingMaterialId?: string | null;
  readingMaterialRevision?: number | null;
  readingWorkspaceId?: string | null;
  readingViewport?: ReadingViewport | null;
  timedMediaId?: string | null;
  timedMediaViewport?: TimedMediaViewport | null;
  parentMessageId?: number | null;
  courseId?: string | null;
  persistUserMessage?: boolean;
  regenerate?: boolean;
  regeneratedFromMessageId?: number | null;
  supersededTurnId?: string | null;
  followupQuestionContext?: Record<string, unknown> | null;
  selectionTutorContext?: Record<string, unknown> | null;
  subagentConsultBudget?: number | null;
  autoRoute?: boolean | null;
}

export interface LegacySendMessageArguments {
  content: string;
  attachments?: OutgoingAttachment[];
  config?: Record<string, unknown>;
  notebookReferences?: NotebookReference[];
  historyReferences?: string[];
  questionNotebookReferences?: number[];
  persona?: string;
  memoryReferences?: MemoryReferences;
}
