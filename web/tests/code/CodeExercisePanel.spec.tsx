import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";
import CodeExercisePanel from "@/components/code/CodeExercisePanel";
import type { CodeRunResponse } from "@/lib/code-runner-api";

initI18n("en");

const mocks = vi.hoisted(() => ({
  fetchCodeCapabilities: vi.fn(),
  runCode: vi.fn(),
}));

vi.mock("@/lib/code-runner-api", () => ({
  fetchCodeCapabilities: mocks.fetchCodeCapabilities,
  runCode: mocks.runCode,
}));

vi.mock("@/components/code/CodeEditor", () => ({
  default: ({
    value,
    onChange,
    readOnly,
  }: {
    value: string;
    onChange: (value: string) => void;
    readOnly?: boolean;
  }) => (
    <textarea
      aria-label="Code editor"
      value={value}
      readOnly={readOnly}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
}));

const result: CodeRunResponse = {
  stdout: "6\n",
  stderr: "",
  exit_code: 0,
  timed_out: false,
  error: "",
  passed: 1,
  total: 1,
  duration_ms: 12,
  tests: [
    {
      name: "Sample 1",
      passed: true,
      stdout: "6\n",
      stderr: "",
      exit_code: 0,
      timed_out: false,
      expected_stdout: "6\n",
      duration_ms: 8,
    },
  ],
};

beforeEach(() => {
  mocks.fetchCodeCapabilities.mockResolvedValue({
    available: true,
    isolation: "system",
    languages: ["python"],
    max_timeout: 30,
    max_tests: 10,
  });
  mocks.runCode.mockResolvedValue(result);
});

describe("CodeExercisePanel", () => {
  it("runs the public tests and reports the result", async () => {
    const onChange = vi.fn();
    const onRunResult = vi.fn();

    render(
      <CodeExercisePanel
        questionId="q_1"
        turnId="turn-1"
        codeSpec={{
          language: "python",
          starter_code: "print(6)\n",
          stdin: "",
          tests: [{ name: "Sample 1", stdin: "", expected_stdout: "6\n" }],
        }}
        value=""
        onChange={onChange}
        onRunResult={onRunResult}
      />,
    );

    const runTests = await screen.findByRole("button", { name: /run tests/i });
    await waitFor(() => expect(runTests).not.toBeDisabled());
    expect(onChange).toHaveBeenCalledWith("print(6)\n");
    await userEvent.click(runTests);

    await waitFor(() =>
      expect(mocks.runCode).toHaveBeenCalledWith(
        expect.objectContaining({
          language: "python",
          code: "print(6)\n",
          tests: [{ name: "Sample 1", stdin: "", expected_stdout: "6\n" }],
        }),
      ),
    );
    expect(onRunResult).toHaveBeenCalledWith(result);
    expect(await screen.findByText("1/1 tests passed")).toBeInTheDocument();
  });

  it("hides the run actions when execution is unavailable", async () => {
    mocks.fetchCodeCapabilities.mockResolvedValue({
      available: false,
      isolation: "off",
      languages: [],
      max_timeout: 0,
      max_tests: 0,
    });

    render(
      <CodeExercisePanel
        questionId="q_1"
        value=""
        onChange={() => {}}
        codeSpec={{
          language: "python",
          starter_code: "",
          stdin: "",
          tests: [],
        }}
      />,
    );

    expect(
      await screen.findByText("Code execution is unavailable"),
    ).toBeInTheDocument();
  });
});
