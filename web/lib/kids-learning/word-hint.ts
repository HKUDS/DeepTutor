export type KidsWordHintPhase = "picker" | "hint" | "choices" | "reveal" | "correct";

export interface KidsWordHintState {
  word: string;
  phase: KidsWordHintPhase;
  choices: string[];
  feedback?: string;
  correctChoice?: string;
  chinese?: string;
  explanation?: string;
  wrongAttempts: number;
}

export type KidsWordHintEvent =
  | { type: "show-choices"; choices: string[] }
  | {
      type: "check";
      correct: boolean;
      attempt: number;
      feedback: string;
      correctChoice?: string;
      chinese?: string;
      explanation?: string;
    }
  | { type: "reveal"; correctChoice: string; chinese: string; explanation: string }
  | { type: "reset"; word: string };

export function createInitialWordHintState(word: string): KidsWordHintState {
  return {
    word,
    phase: "hint",
    choices: [],
    wrongAttempts: 0,
  };
}

export function reduceWordHintState(
  state: KidsWordHintState,
  event: KidsWordHintEvent,
): KidsWordHintState {
  if (event.type === "reset") return createInitialWordHintState(event.word);
  if (event.type === "show-choices" && state.phase === "hint") {
    return {
      ...state,
      phase: "choices",
      choices: event.choices.slice(0, 3),
      feedback: undefined,
      correctChoice: undefined,
      chinese: undefined,
      explanation: undefined,
    };
  }

  if (event.type === "check" && state.phase === "choices") {
    if (event.correct) {
      return {
        ...state,
        phase: "correct",
        feedback: event.feedback,
        wrongAttempts: state.wrongAttempts,
      };
    }

    const attempts = Math.max(state.wrongAttempts, event.attempt);
    const shouldReveal = attempts >= 2;
    return {
      ...state,
      phase: shouldReveal ? "reveal" : "choices",
      feedback: event.feedback,
      correctChoice: shouldReveal ? event.correctChoice : undefined,
      chinese: shouldReveal ? event.chinese : undefined,
      explanation: shouldReveal ? event.explanation : undefined,
      wrongAttempts: attempts,
    };
  }

  if (event.type === "reveal" && state.phase !== "correct") {
    return {
      ...state,
      phase: "reveal",
      feedback: undefined,
      correctChoice: event.correctChoice,
      chinese: event.chinese,
      explanation: event.explanation,
      wrongAttempts: Math.max(2, state.wrongAttempts),
    };
  }

  return state;
}
