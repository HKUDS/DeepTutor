import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { UserMessage } from "@/features/chat/messages/ChatMessageList";
import UserMathText, {
  splitUserMath,
} from "@/features/chat/messages/UserMathText";
import { setUserMessageMath } from "@/hooks/useUserMessageMath";
import { initI18n } from "@/i18n/init";

initI18n("en");

afterEach(() => {
  cleanup();
  setUserMessageMath(false);
  window.localStorage.clear();
});

describe("splitUserMath", () => {
  it("splits explicit inline formulas and keeps the prose between them", () => {
    expect(splitUserMath("设 $x=1$，求 $y$")).toEqual([
      { kind: "text", value: "设 " },
      { kind: "math", value: "x=1", display: false },
      { kind: "text", value: "，求 " },
      { kind: "math", value: "y", display: false },
    ]);
  });

  it("keeps prices literal", () => {
    expect(splitUserMath("门票 $5 和 $10")).toEqual([
      { kind: "text", value: "门票 $5 和 $10" },
    ]);
    expect(splitUserMath("价格 $5-$10 元")).toEqual([
      { kind: "text", value: "价格 $5-$10 元" },
    ]);
  });

  it("keeps inline code and fenced code literal", () => {
    expect(splitUserMath("`$x$`")).toEqual([{ kind: "text", value: "`$x$`" }]);
    expect(splitUserMath("```\n$x$\n```")).toEqual([
      { kind: "text", value: "```\n$x$\n```" },
    ]);
  });

  it("splits display math", () => {
    expect(splitUserMath("前文\n$$x^2$$\n后文")).toEqual([
      { kind: "text", value: "前文\n" },
      { kind: "math", value: "x^2", display: true },
      { kind: "text", value: "\n后文" },
    ]);
  });
});

describe("user message math", () => {
  it("renders explicit formulas beside the literal prose", async () => {
    const { container } = render(<UserMathText content={"设 $x=1$，求 $y$"} />);

    await waitFor(() => {
      expect(container.querySelectorAll(".katex")).toHaveLength(2);
    });
    expect(container).toHaveTextContent("设");
    expect(container).toHaveTextContent("，求");
    expect(container).not.toHaveTextContent("$x=1$");
  });

  it("switches a sent bubble between literal text and math", async () => {
    setUserMessageMath(false);
    const { container } = render(
      <UserMessage
        index={0}
        msg={{ role: "user", content: "设 $x=1$" }}
      />,
    );

    expect(container.querySelector(".katex")).toBeNull();
    expect(screen.getByText("设 $x=1$")).toBeVisible();

    act(() => setUserMessageMath(true));

    await waitFor(() => {
      expect(container.querySelectorAll(".katex")).toHaveLength(1);
    });
    expect(container).not.toHaveTextContent("$x=1$");
  });
});
