import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MasteryQuestionCard } from "@/components/chat/home/MasteryQuestionCard";
import { initI18n } from "@/i18n/init";
import { buildMasteryAnswerTurn, type MasteryQuestion } from "@/lib/mastery-question";

initI18n("en");

const question = (overrides: Partial<MasteryQuestion> = {}): MasteryQuestion => ({
  questionId: "q-calc",
  prompt: "Compute the expected cost of the contract.",
  questionType: "short",
  objectiveName: "Expected costs",
  difficulty: "medium",
  attempt: 1,
  options: [],
  allowFreeText: true,
  ...overrides,
});

const photo = (name = "working.jpg") =>
  new File(["synthetic handwritten working"], name, { type: "image/jpeg" });

describe("MasteryQuestionCard answer photos", () => {
  const createObjectURL = URL.createObjectURL;
  const revokeObjectURL = URL.revokeObjectURL;
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:preview");
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => {
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
  });

  it("submits a photo-only answer with the image data", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(() => true);
    render(
      <MasteryQuestionCard question={question()} grade={null} answered={false} submittedAnswer="" onSubmit={onSubmit} />,
    );
    const submit = screen.getByRole("button", { name: "Submit" });
    expect(submit).toBeDisabled();
    expect(screen.getByText("Write your answer or attach a photo of your solution.")).toBeInTheDocument();

    const input = screen.getByLabelText("Attach an image as your answer") as HTMLInputElement;
    expect(input).toHaveAttribute("accept", "image/*");
    // The phone picker must still offer the gallery, not only the camera.
    expect(input).not.toHaveAttribute("capture");
    fireEvent.change(input, { target: { files: [photo()] } });

    expect(await screen.findByRole("img", { name: "working.jpg" })).toBeInTheDocument();
    expect(submit).toBeEnabled();
    await user.click(submit);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const payload = (onSubmit.mock.calls[0] as unknown[])[0] as {
      text: string;
      photos: Array<{ id: string; base64: string; mime: string; name: string }>;
    };
    expect(payload.text).toBe("");
    expect(payload.photos).toHaveLength(1);
    expect(payload.photos[0]).toMatchObject({ mime: "image/jpeg", name: "working.jpg" });
    expect(atob(payload.photos[0].base64)).toBe("synthetic handwritten working");
    expect(payload.photos[0].id).toMatch(/^[0-9a-f]{12}$/);
  });

  it("sends a typed final result together with the photo and lets a photo be removed", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(() => true);
    render(
      <MasteryQuestionCard question={question()} grade={null} answered={false} submittedAnswer="" onSubmit={onSubmit} />,
    );
    const input = screen.getByLabelText("Attach an image as your answer");
    fireEvent.change(input, { target: { files: [photo("a.jpg"), photo("b.jpg")] } });
    await screen.findByRole("img", { name: "b.jpg" });
    await user.click(screen.getAllByRole("button", { name: "Remove image" })[0]);
    await waitFor(() => expect(screen.queryByRole("img", { name: "a.jpg" })).toBeNull());

    await user.type(screen.getByRole("textbox"), "58.00");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    const payload = (onSubmit.mock.calls[0] as unknown[])[0] as { text: string; photos: Array<{ name: string }> };
    expect(payload.text).toBe("58.00");
    expect(payload.photos.map((item) => item.name)).toEqual(["b.jpg"]);
  });

  it("offers no photo input on choice cards", () => {
    render(
      <MasteryQuestionCard
        question={question({ options: [{ label: "A", body: "58" }] })}
        grade={null}
        answered={false}
        submittedAnswer=""
        onSubmit={() => true}
      />,
    );
    expect(screen.queryByLabelText("Attach an image as your answer")).toBeNull();
  });
});

describe("buildMasteryAnswerTurn", () => {
  const photos = [{ id: "p1", base64: "AAAA", mime: "image/jpeg", name: "working.jpg" }];

  it("names the photo attachments as the card answer", () => {
    expect(buildMasteryAnswerTurn({ questionId: "q", text: " ", photos }, "Photo of my solution")).toEqual({
      content: "Photo of my solution",
      attachments: [
        { type: "image", id: "p1", base64: "AAAA", filename: "working.jpg", mime_type: "image/jpeg" },
      ],
      masteryAnswer: { question_id: "q", text: "", attachment_ids: ["p1"] },
    });
  });

  it("keeps text and group answers unchanged and refuses an empty answer", () => {
    expect(buildMasteryAnswerTurn({ questionId: "q", text: "C" }, "label")).toEqual({
      content: "C",
      attachments: undefined,
      masteryAnswer: { question_id: "q", text: "C" },
    });
    expect(
      buildMasteryAnswerTurn(
        { questionId: "g", text: "1. A", answers: [{ questionId: "a", text: "A" }], photos },
        "label",
      )?.masteryAnswer,
    ).toEqual({ question_id: "g", text: "1. A", answers: { a: "A" } });
    expect(buildMasteryAnswerTurn({ questionId: "q", text: "" }, "label")).toBeNull();
  });
});

describe("MasteryQuestionCard answer photo limits", () => {
  const createObjectURL = URL.createObjectURL;
  afterEach(() => {
    URL.createObjectURL = createObjectURL;
  });
  it("refuses photos beyond the grader's byte budget", async () => {
    URL.createObjectURL = vi.fn(() => "blob:preview");
    render(
      <MasteryQuestionCard question={question()} grade={null} answered={false} submittedAnswer="" onSubmit={() => true} />,
    );
    const big = new File([new Uint8Array(11 * 1024 * 1024)], "big.jpg", { type: "image/jpeg" });
    fireEvent.change(screen.getByLabelText("Attach an image as your answer"), { target: { files: [big] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("File too large: big.jpg");
    expect(screen.queryByRole("img", { name: "big.jpg" })).toBeNull();
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  });
});
