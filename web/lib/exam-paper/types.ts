export type QuestionsSpaceView = "question_bank" | "paper_reorder" | "exam_assemble";

/** One node of the doc_intel textbook tree returned by the textbook-tree API. */
export interface TextbookTreeNode {
  title: string;
  children?: TextbookTreeNode[];
}

/** One textbook document's aggregated structure tree. */
export interface TextbookSummary {
  doc_id: string;
  file_name: string;
  subject: string;
  doc_type: string;
  grade: string;
  tree: TextbookTreeNode;
}

/** A doc_intel question node under a struct path (questions/by-struct). */
export interface StructQuestion {
  node_id: string;
  q_id: string;
  text: string;
  question_type: string;
  difficulty: string;
  struct_path: string;
  has_answer: boolean;
  file_name: string;
}

export interface StructQuestionsResponse {
  kb_name: string;
  struct_path: string;
  questions: StructQuestion[];
  has_doc_intel: boolean;
  hint: string;
}

export interface ExamPaperAssemblePayload {
  kb_name: string;
  q_ids: string[];
  title?: string;
  include_answers: boolean;
}

export type PaperOrder = "source" | "easy_to_hard" | "manual";
export type UnassignedPolicy = "append" | "reject";
export type PaperExportFormat = "html" | "markdown";

export interface PaperSectionEditorValue {
  key: string;
  id: string;
  title: string;
  questionType: string;
  difficulty: string;
  knowledgePointIds: string;
  order: PaperOrder;
  questionIds: string;
}

export interface PaperReorderPayload {
  source_id: string;
  rules: {
    sections: Array<{
      id: string;
      title: string;
      filter: {
        question_type: string | null;
        difficulty: string | null;
        knowledge_point_ids: string[];
      };
      order: PaperOrder;
      question_ids: string[];
    }>;
    unassigned_policy: UnassignedPolicy;
  };
  include_answer_sheet: boolean;
}

export interface ReorderedQuestion {
  q_id: string;
  text: string;
  question_type: string;
  difficulty: string;
  has_answer: boolean;
  file_name: string;
}
