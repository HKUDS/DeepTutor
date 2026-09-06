import type { StartTurnCommand } from "@/contracts/generated/turn-protocol";
import { buildStartTurn } from "@/contracts/parse/turn-command";
import { ApiError } from "@/shared/api/errors";

import type {
  LegacySendMessageArguments,
  StartTurnInput,
} from "../model/start-turn";

const RUNTIME_ONLY_CONFIG_KEYS = new Set([
  "_course_id",
  "_persist_user_message",
  "_regenerate",
  "_regenerated_from_message_id",
  "_superseded_turn_id",
  "auto_route",
  "followup_question_context",
  "selection_tutor_context",
  "subagent_consult_budget",
]);

function invalid(message: string): never {
  throw new ApiError({
    code: "invalid_turn_input",
    message,
    retryable: false,
    scope: "turn",
  });
}

function capabilityConfig(input: StartTurnInput): Record<string, unknown> {
  const config = input.capabilityConfig ?? {};
  const allowed = input.allowedCapabilityConfigKeys
    ? new Set(input.allowedCapabilityConfigKeys)
    : null;
  for (const key of Object.keys(config)) {
    if (RUNTIME_ONLY_CONFIG_KEYS.has(key)) {
      invalid(`Runtime field ${key} must use its typed turn property`);
    }
    if (allowed && !allowed.has(key)) {
      invalid(
        `Unsupported ${input.capability ?? "chat"} configuration field: ${key}`,
      );
    }
  }
  return { ...config };
}

export function buildStartTurnInput(input: StartTurnInput): StartTurnCommand {
  if (!input.content.trim()) invalid("Turn content must not be empty");
  if (input.subagentConsultBudget != null && input.subagentConsultBudget < 0) {
    invalid("Subagent consult budget must be non-negative");
  }
  if (
    input.readingMaterialRevision != null &&
    input.readingMaterialRevision < 1
  ) {
    invalid("Reading material revision must be positive");
  }
  if (
    input.timedMediaViewport &&
    (!Number.isFinite(input.timedMediaViewport.time_seconds) ||
      input.timedMediaViewport.time_seconds < 0)
  ) {
    invalid("Timed media position must be non-negative");
  }

  return buildStartTurn({
    content: input.content,
    capability: input.capability === undefined ? "chat" : input.capability,
    session_id: input.sessionId ?? null,
    tools: input.tools ?? null,
    knowledge_bases: input.knowledgeBases ?? [],
    language: input.language ?? null,
    config: capabilityConfig(input),
    attachments: input.attachments ?? [],
    notebook_references: input.notebookReferences ?? [],
    history_references: input.historyReferences ?? [],
    partner_group_references: input.partnerGroupReferences ?? [],
    question_notebook_references: input.questionNotebookReferences ?? [],
    book_references: input.bookReferences ?? [],
    reading_references: input.readingReferences ?? [],
    memory_references: input.memoryReferences ?? [],
    skills: input.skills ?? [],
    persona: input.persona ?? null,
    llm_selection: input.llmSelection ?? null,
    workspace_mode: input.workspaceMode ?? null,
    mastery_path_id: input.masteryPathId ?? null,
    mastery_session_mode: input.masterySessionMode ?? null,
    mastery_path_lease_managed: input.masteryPathLeaseManaged ?? false,
    mastery_answer: input.masteryAnswer ?? null,
    mastery_skip: input.masterySkip ?? null,
    reading_material_id: input.readingMaterialId ?? null,
    reading_material_revision: input.readingMaterialRevision ?? null,
    reading_workspace_id: input.readingWorkspaceId ?? null,
    reading_viewport: input.readingViewport ?? null,
    timed_media_id: input.timedMediaId ?? null,
    timed_media_viewport: input.timedMediaViewport ?? null,
    ...(input.parentMessageId !== undefined
      ? { parent_message_id: input.parentMessageId }
      : {}),
    course_id: input.courseId ?? null,
    persist_user_message: input.persistUserMessage ?? true,
    regenerate: input.regenerate ?? false,
    regenerated_from_message_id: input.regeneratedFromMessageId ?? null,
    superseded_turn_id: input.supersededTurnId ?? null,
    followup_question_context: input.followupQuestionContext ?? null,
    selection_tutor_context: input.selectionTutorContext ?? null,
    subagent_consult_budget: input.subagentConsultBudget ?? null,
    auto_route: input.autoRoute ?? null,
  });
}

/** Temporary positional adapter for callers migrated in Task 14. */
export function legacySendMessageInput(
  legacy: LegacySendMessageArguments,
  defaults: Omit<
    StartTurnInput,
    keyof LegacySendMessageArguments | "capabilityConfig"
  >,
): StartTurnInput {
  return {
    ...defaults,
    content: legacy.content,
    attachments: legacy.attachments,
    capabilityConfig: legacy.config,
    notebookReferences: legacy.notebookReferences,
    historyReferences: legacy.historyReferences,
    questionNotebookReferences: legacy.questionNotebookReferences,
    persona: legacy.persona,
    memoryReferences: legacy.memoryReferences,
  };
}
