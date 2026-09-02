import type { StreamEvent } from "@/features/chat/model/protocol";

export interface PartnerDraftSnapshot {
  events: StreamEvent[];
  content: string;
}

interface FrameScheduler {
  schedule: (callback: () => void) => number;
  cancel: (handle: number) => void;
}

const browserScheduler: FrameScheduler = {
  schedule: (callback) => requestAnimationFrame(callback),
  cancel: (handle) => cancelAnimationFrame(handle),
};

export function createPartnerDraftPublisher(
  getDraft: () => PartnerDraftSnapshot | null,
  setDraft: (draft: PartnerDraftSnapshot | null) => void,
  scheduler: FrameScheduler = browserScheduler,
) {
  let frame = 0;
  let scheduled = false;
  const emit = () => {
    const draft = getDraft();
    setDraft(
      draft ? { events: [...draft.events], content: draft.content } : null,
    );
  };
  const cancelFrame = () => {
    if (!scheduled) return;
    scheduler.cancel(frame);
    frame = 0;
    scheduled = false;
  };

  return {
    publish() {
      if (scheduled) return;
      frame = scheduler.schedule(() => {
        scheduled = false;
        frame = 0;
        emit();
      });
      scheduled = true;
    },
    publishNow() {
      cancelFrame();
      emit();
    },
    cancel: cancelFrame,
  };
}
