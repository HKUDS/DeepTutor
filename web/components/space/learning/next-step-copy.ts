type LocalizedCopy = { zh: string; en: string };

export const TEACH_FIRST_PROFILE_LABEL: LocalizedCopy = {
  zh: "先讲解，再检查理解",
  en: "Teach first, then check understanding",
};

export const NEXT_LABELS: Record<string, LocalizedCopy> = {
  probe: {
    zh: "先用一道探查题看看你是否已经掌握",
    en: "Start with a probe and test out if you already know it",
  },
  teach: {
    zh: "先讲解这个知识点，再检查你是否理解",
    en: "Learn this knowledge point before checking understanding",
  },
  practice: {
    zh: "继续练习，直到稳定越过掌握门槛",
    en: "Practice until you reliably clear the mastery gate",
  },
  assess: {
    zh: "用自己的话讲清楚这个概念",
    en: "Explain this clearly in your own words",
  },
  review: { zh: "复习这个记忆信标", en: "Revisit this memory beacon" },
  answer_pending: {
    zh: "完成导师正在等待的回答",
    en: "Complete the answer your tutor is waiting for",
  },
  complete: {
    zh: "整片疆域已经点亮",
    en: "The whole territory is illuminated",
  },
};

export const NEXT_CTA_LABELS: Record<string, LocalizedCopy> = {
  teach: { zh: "开始学习这个知识点", en: "Learn this knowledge point" },
  review: { zh: "开始本次复习", en: "Start this review" },
  answer_pending: {
    zh: "回到原会话作答",
    en: "Answer in the original session",
  },
  complete: { zh: "继续自由探索", en: "Keep exploring" },
};
