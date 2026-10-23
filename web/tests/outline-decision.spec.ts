import { describe, expect, it } from "vitest";

import {
  parseOutlineDecision,
  pendingProseDecision,
} from "../lib/outline-decision";

const screenshot = `选这 4 个而不是泛泛的「函数式」是有理由的。

同时提交的两处调整：

1. 顺序：M6 现在排在 M0 之前（原来的预览也一并 commit 了）。
2. 硬前置：M0-KP3 的 prerequisite_ids 指向 M6-KP1。

一件需要你拍板的事：M6 现在有 10 个知识点，按你每周 15-20 小时的预算，这一个模块会吃掉不少时间。你有两种走法：

- 按现在这样全学，M6 单独占大约 2-3 周；
- 收敛：把「纯函数与不可变数据」并进「高阶函数与闭包」，把「生成器与惰性求值」降级成装饰器那节里的一个子话题，M6 回到 8 个点左右。

你倾向哪种？另外，M6 里目前没有任何知识点绑定知识库来源。`;

describe("prose outline decisions", () => {
  it("lifts the choice under a 拍板 cue and ignores the report above it", () => {
    const decision = parseOutlineDecision(screenshot);
    expect(decision?.prompt).toContain("一件需要你拍板的事");
    expect(decision?.options).toEqual([
      "按现在这样全学，M6 单独占大约 2-3 周；",
      "收敛：把「纯函数与不可变数据」并进「高阶函数与闭包」，把「生成器与惰性求值」降级成装饰器那节里的一个子话题，M6 回到 8 个点左右。",
    ]);
  });

  it("ignores a numbered report that never asks the learner to pick", () => {
    expect(
      parseOutlineDecision("同时提交的两处调整：\n\n1. 顺序改了。\n2. 前置改了。"),
    ).toBeNull();
  });

  it("stops once the learner has already answered", () => {
    expect(
      pendingProseDecision([
        { role: "assistant", content: screenshot },
        { role: "user", content: "按现在这样全学" },
      ]),
    ).toBeNull();
    expect(
      pendingProseDecision([{ role: "assistant", content: screenshot }])?.options,
    ).toHaveLength(2);
  });
});
