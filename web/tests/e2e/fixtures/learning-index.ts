import type { LearningSources } from "../../../lib/learning-dashboard";

export const emptyLearningIndex: { sources: LearningSources; failed: string[] } = {
  sources: { books: [], mastery: [], reading: [], watching: [], practice: [] },
  failed: [],
};
