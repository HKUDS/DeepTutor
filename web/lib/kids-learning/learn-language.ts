export type KidsLearningLanguage = "en" | "zh";

export function detectKidsReadingLanguage(
  text: string,
  fallback: KidsLearningLanguage = "en",
): KidsLearningLanguage {
  const cjk = (text.match(/[\u3400-\u9fff\uf900-\ufaff]/g) || []).length;
  const latin = (text.match(/[A-Za-z]+/g) || []).length;
  if (cjk + latin === 0) return fallback;
  return cjk >= latin ? "zh" : "en";
}

export interface KidsLearningCopy {
  books: string;
  readAloud: string;
  stop: string;
  learn: string;
  quiz: string;
  close: string;
  retry: string;
  question: string;
  submit: string;
  checking: string;
  tryAgain: string;
  correct: string;
  thinkAgain: string;
  quizLoading: string;
  quizEmpty: string;
  great: string;
  keepThinking: string;
  tryAgainHeading: string;
  correctCount: string;
  lookAndThink: string;
  quizIntro: string;
  learnLoading: string;
  learnError: string;
  pageOverview: string;
  keyConcepts: string;
  reflection: string;
  showHint: string;
  showAnswer: string;
  readOverview: string;
  stopOverview: string;
  readConcept: string;
  stopConcept: string;
  readReflection: string;
  stopReflection: string;
  readQuestion: string;
  stopQuestion: string;
  readChoice: string;
  stopChoice: string;
  readAnswer: string;
  stopAnswer: string;
  translateTitle: string;
  translateUnavailable: string;
  previousPage: string;
  nextPage: string;
  openingBook: string;
  openBookError: string;
}

const zhCopy: KidsLearningCopy = {
  books: "书架",
  readAloud: "朗读",
  stop: "停止",
  learn: "学习",
  quiz: "测一测",
  close: "关闭",
  retry: "重试",
  question: "题目",
  submit: "提交",
  checking: "检查中...",
  tryAgain: "再试一次",
  correct: "答对了",
  thinkAgain: "再想想",
  quizLoading: "正在准备 3 道题...",
  quizEmpty: "再读一会儿，就可以测一测啦！",
  great: "太棒了！",
  keepThinking: "继续想！",
  tryAgainHeading: "再试一次！",
  correctCount: "答对 {score} / {total} 题",
  lookAndThink: "看一看，想一想",
  quizIntro: "仔细看图和文字，选出你的想法。",
  learnLoading: "正在整理这一页...",
  learnError: "这一页暂时没整理好，可以再试一次。",
  pageOverview: "这一页讲了什么",
  keyConcepts: "关键概念",
  reflection: "想一想",
  showHint: "看提示",
  showAnswer: "看答案",
  readOverview: "朗读本页主旨",
  stopOverview: "停止朗读主旨",
  readConcept: "朗读概念",
  stopConcept: "停止朗读概念",
  readReflection: "朗读想一想",
  stopReflection: "停止朗读想一想",
  readQuestion: "朗读题目",
  stopQuestion: "停止朗读题目",
  readChoice: "朗读选项",
  stopChoice: "停止朗读选项",
  readAnswer: "朗读解析",
  stopAnswer: "停止朗读解析",
  translateTitle: "翻译",
  translateUnavailable: "翻译暂时不可用",
  previousPage: "上一页",
  nextPage: "下一页",
  openingBook: "正在打开书...",
  openBookError: "这本书暂时打不开。请回到书架再试一次。",
};

const enCopy: KidsLearningCopy = {
  books: "Books",
  readAloud: "Read Aloud",
  stop: "Stop",
  learn: "Learn",
  quiz: "Quiz",
  close: "Close",
  retry: "Try Again",
  question: "Question",
  submit: "Submit",
  checking: "Checking...",
  tryAgain: "Try Again",
  correct: "Yes",
  thinkAgain: "Think again",
  quizLoading: "Getting 3 questions...",
  quizEmpty: "Read a little more first!",
  great: "Great!",
  keepThinking: "Keep thinking!",
  tryAgainHeading: "Try again!",
  correctCount: "{score} / {total} correct!",
  lookAndThink: "Look and Think",
  quizIntro: "Look closely, then choose what you think.",
  learnLoading: "Putting this page together...",
  learnError: "This page is not ready yet. Please try again.",
  pageOverview: "What is this page about?",
  keyConcepts: "Key Ideas",
  reflection: "Think About It",
  showHint: "Show hint",
  showAnswer: "Show answer",
  readOverview: "Read overview",
  stopOverview: "Stop overview",
  readConcept: "Read concept",
  stopConcept: "Stop concept",
  readReflection: "Read reflection",
  stopReflection: "Stop reflection",
  readQuestion: "Read question",
  stopQuestion: "Stop question",
  readChoice: "Read choice",
  stopChoice: "Stop choice",
  readAnswer: "Read answer",
  stopAnswer: "Stop answer",
  translateTitle: "Translate",
  translateUnavailable: "Translation unavailable",
  previousPage: "Previous page",
  nextPage: "Next page",
  openingBook: "Opening book...",
  openBookError: "This book could not be opened. Please go back to Books and try again.",
};

export function kidsLearningCopy(language: KidsLearningLanguage): KidsLearningCopy {
  return language === "zh" ? zhCopy : enCopy;
}
