type LocalizedCopy = { zh: string; es: string; en: string };

export function localizedNextStepCopy(
  copy: LocalizedCopy,
  language?: string,
): string {
  const normalized = language?.toLowerCase() ?? "en";
  if (normalized.startsWith("zh")) return copy.zh;
  if (normalized.startsWith("es")) return copy.es;
  return copy.en;
}

export const TEACH_FIRST_PROFILE_LABEL: LocalizedCopy = {
  zh: "先讲解，再检查理解",
  es: "Primero explica y después comprueba la comprensión",
  en: "Teach first, then check understanding",
};

export const NEXT_LABELS: Record<string, LocalizedCopy> = {
  probe: {
    zh: "先用一道探查题看看你是否已经掌握",
    es: "Empieza con una pregunta de diagnóstico para comprobar si ya lo dominas",
    en: "Start with a probe and test out if you already know it",
  },
  teach: {
    zh: "先讲解这个知识点，再检查你是否理解",
    es: "Aprende este concepto antes de comprobar si lo has entendido",
    en: "Learn this knowledge point before checking understanding",
  },
  practice: {
    zh: "继续练习，直到稳定越过掌握门槛",
    es: "Practica hasta superar con soltura el nivel de dominio",
    en: "Practice until you reliably clear the mastery gate",
  },
  assess: {
    zh: "用自己的话讲清楚这个概念",
    es: "Explica este concepto con claridad y con tus propias palabras",
    en: "Explain this clearly in your own words",
  },
  review: {
    zh: "复习这个记忆信标",
    es: "Repasa este punto clave",
    en: "Revisit this memory beacon",
  },
  answer_pending: {
    zh: "完成导师正在等待的回答",
    es: "Completa la respuesta que espera tu tutor",
    en: "Complete the answer your tutor is waiting for",
  },
  complete: {
    zh: "整片疆域已经点亮",
    es: "Has completado todo el recorrido",
    en: "The whole territory is illuminated",
  },
};

export const NEXT_CTA_LABELS: Record<string, LocalizedCopy> = {
  teach: {
    zh: "开始学习这个知识点",
    es: "Aprender este concepto",
    en: "Learn this knowledge point",
  },
  review: {
    zh: "开始本次复习",
    es: "Empezar el repaso",
    en: "Start this review",
  },
  answer_pending: {
    zh: "回到原会话作答",
    es: "Responder en la conversación original",
    en: "Answer in the original session",
  },
  complete: {
    zh: "继续自由探索",
    es: "Seguir explorando",
    en: "Keep exploring",
  },
};
