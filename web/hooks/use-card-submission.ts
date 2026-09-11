import { useCallback, useState } from "react";

export interface UserReplyPayload {
  text?: string;
  answers?: Array<{ questionId: string; text: string }>;
}

/** What a host does with a card's answers, and whether they landed. */
export type SubmitUserReply = (
  payload: UserReplyPayload,
) => void | boolean | Promise<void | boolean>;

/**
 * Send a card's answers, and know whether they reached a turn waiting for them.
 *
 * A question card outlives the turn that asked it — a backend restart drops
 * the waiter while the card stays on screen, fully interactive — so "sending"
 * is a claim that can turn out false. When it does the card has to reopen:
 * a submission that cannot succeed must not look like one still in flight.
 *
 * Both question cards implement that same three-state dance, so it lives here
 * rather than twice.
 */
export function useCardSubmission(onSubmit: SubmitUserReply) {
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState(false);

  const submit = useCallback(
    async (payload: UserReplyPayload) => {
      setSending(true);
      setFailed(false);
      let accepted: void | boolean;
      try {
        accepted = await onSubmit(payload);
      } catch {
        accepted = false;
      }
      // ``undefined`` is a host that does not report a verdict; only an
      // explicit ``false`` reopens the card. The picked answers survive in the
      // caller's state, so retrying is one click.
      if (accepted === false) {
        setSending(false);
        setFailed(true);
      }
    },
    [onSubmit],
  );

  return { sending, failed, submit };
}
