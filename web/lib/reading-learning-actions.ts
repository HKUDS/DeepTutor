export const READER_LEARNING_ACTION_EVENT = "dt:reader-learning-action";

export type ReaderLearningAction = "learn" | "quiz";

export interface ReaderLearningContext {
  locator: number;
  unit: string;
  ageBand: string;
}

export function buildReaderLearningPrompt(
  action: ReaderLearningAction,
  context: ReaderLearningContext,
  locale: string = "zh",
): string {
  const Chinese = locale.toLowerCase().startsWith("zh");
  const where = Chinese
    ? `第 ${context.locator} ${context.unit}`
    : `${context.unit} ${context.locator}`;
  const age = Chinese
    ? `${context.ageBand} 岁`
    : `ages ${context.ageBand}`;

  if (action === "learn") {
    return Chinese
      ? `请只依据当前阅读材料的${where}，为${age}的孩子讲解。输出四部分：1. 这一页主要讲了什么（最多两句话）；2. 最多三个关键概念，每个用一句话解释；3. 一个来自生活或书里的具体例子；4. 最后提出一个引导孩子继续思考的问题。不要使用材料外的信息。`
      : `Using only ${where} of the currently open reading material, explain it for ${age}. Return four parts: 1. the main idea in at most two sentences; 2. at most three key concepts, one sentence each; 3. one concrete example; 4. one final question that invites further thinking. Do not use information outside the material.`;
  }

  return Chinese
    ? `请只依据当前阅读材料的${where}，为${age}的孩子出一组共三题的练习。先只提出第 1 题，等我回答后再告诉我对错和讲解，然后继续下一题；不要一次列出三题，不要使用材料外的信息，也不要保存成绩。`
    : `Using only ${where} of the currently open reading material, create a three-question practice set for ${age}. Ask only question 1 first. After my answer, tell me whether it is right and explain it, then continue to the next question. Do not list all questions at once, use outside information, or save a score.`;
}

export function dispatchReaderLearningAction(
  action: ReaderLearningAction,
  prompt: string,
): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent(READER_LEARNING_ACTION_EVENT, {
      detail: { action, prompt },
    }),
  );
}
