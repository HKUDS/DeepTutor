import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useCardSubmission } from "@/hooks/use-card-submission";

describe("incremental card acknowledgement", () => {
  it("reopens after each new durable leaf set, not a replay of the same set", async () => {
    const onSubmit = vi.fn(() => true);
    const { result, rerender } = renderHook(({ acknowledgement }) =>
      useCardSubmission(onSubmit, undefined, acknowledgement),
    { initialProps: { acknowledgement: "[]" } });
    await act(async () => result.current.submit({ answers: [{ questionId: "a", text: "A" }] }));
    expect(result.current.sending).toBe(true);
    rerender({ acknowledgement: '["a"]' });
    expect(result.current.sending).toBe(false);
    expect(result.current.failed).toBe(false);
    await act(async () => result.current.submit({ answers: [{ questionId: "b", text: "B" }] }));
    expect(result.current.sending).toBe(true);
    rerender({ acknowledgement: '["a"]' });
    expect(result.current.sending).toBe(true);
    rerender({ acknowledgement: '["a","b"]' });
    expect(result.current.sending).toBe(false);
  });

  it("still reopens on rejection or failed delivery without an acknowledgement", async () => {
    const onSubmit = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    const { result, rerender } = renderHook(({ rejection }) =>
      useCardSubmission(onSubmit, rejection, '["a"]'),
    { initialProps: { rejection: undefined as string | undefined } });
    await act(async () => result.current.submit({ text: "B" }));
    expect(result.current.sending).toBe(false);
    expect(result.current.failed).toBe(true);
    await act(async () => result.current.submit({ text: "B" }));
    expect(result.current.sending).toBe(true);
    rerender({ rejection: "reject-next" });
    expect(result.current.sending).toBe(false);
    expect(result.current.failed).toBe(true);
  });
});
