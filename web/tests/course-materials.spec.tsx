import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CourseMaterials from "@/components/courses/CourseMaterials";
import { initI18n } from "@/i18n/init";
import type { StudyCourse } from "@/lib/courses-api";

initI18n("en");

describe("CourseMaterials", () => {
  it("does not show Stanford materials for an unrelated course", () => {
    render(
      <CourseMaterials
        course={{ id: "course_other", name: "DeBERTa fine-tuning" } as StudyCourse}
      />,
    );
    expect(
      screen.queryByRole("link", { name: /official syllabus website/i }),
    ).not.toBeInTheDocument();
  });

  it("renders syllabus media from course data and labels the GitHub PDF as a cheatsheet", () => {
    const course = {
      id: "course_stanford",
      name: "Stanford CME 295",
      syllabus: [
        {
          id: "lecture_1_transformers",
          position: 0,
          title: "Lecture 1: Transformers",
          topics: [],
          covered: false,
          video_url: "https://www.youtube.com/watch?v=abc12345678",
          slide_url: "https://example.org/lecture-one.pdf",
          video_status: "available",
          slide_status: "available",
        },
        {
          id: "lecture_2_llms",
          position: 1,
          title: "Lecture 2: LLMs",
          topics: [],
          covered: false,
          slide_url: "https://example.org/lecture-two.pdf",
          video_status: "upcoming",
          slide_status: "available",
        },
      ],
    } as unknown as StudyCourse;
    render(<CourseMaterials course={course} />);

    // 1. Official Syllabus Website link
    const syllabusLink = screen.getByRole("link", {
      name: /official syllabus website/i,
    });
    expect(syllabusLink).toHaveAttribute(
      "href",
      "https://cme295.stanford.edu/syllabus/",
    );

    // 2. Slide and cheatsheet links come from the syllabus and reference data.
    const slideLinks = screen.getAllByRole("link", { name: /Download or view/i });
    expect(slideLinks[0]).toHaveAttribute("href", "https://example.org/lecture-one.pdf");
    expect(slideLinks[1]).toHaveAttribute("href", "https://example.org/lecture-two.pdf");
    const cheatsheetLinks = screen.getAllByRole("link", { name: /Cheatsheet/i });
    expect(cheatsheetLinks.length).toBeGreaterThanOrEqual(2);
    expect(cheatsheetLinks[0]).toHaveAttribute(
      "href",
      "https://raw.githubusercontent.com/afshinea/stanford-cme-295-transformers-large-language-models/main/en/cheatsheet-transformers-large-language-models.pdf",
    );
    expect(screen.queryByRole("link", { name: /GitHub mirror/i })).not.toBeInTheDocument();
    expect(screen.getByText(/DeepTutor authored the expanded Units and Concepts/i)).toBeInTheDocument();

    // 3. Video & Lectures: YouTube ID & Timed Transcript
    expect(screen.getByText(/YouTube: abc12345678/i)).toBeInTheDocument();
    const youtubeLink = screen.getByRole("link", {
      name: /YouTube \(opens in new tab\)/i,
    });
    expect(youtubeLink).toHaveAttribute(
      "href",
      "https://www.youtube.com/watch?v=abc12345678",
    );
    const transcriptLink = screen.getByRole("link", {
      name: /timed media transcript/i,
    });
    expect(transcriptLink).toHaveAttribute(
      "href",
      "/learning/watching?video=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabc12345678&title=Lecture%201%3A%20Transformers",
    );

    // 4. VIP Cheatsheet & Code
    const cheatsheetPdfLink = screen.getByRole("link", {
      name: /VIP Cheatsheet PDF/i,
    });
    expect(cheatsheetPdfLink).toHaveAttribute(
      "href",
      "https://raw.githubusercontent.com/afshinea/stanford-cme-295-transformers-large-language-models/main/en/cheatsheet-transformers-large-language-models.pdf",
    );

    const githubLink = screen.getByRole("link", {
      name: /Open cheatsheet repository on GitHub/i,
    });
    expect(githubLink).toHaveAttribute(
      "href",
      "https://github.com/afshinea/stanford-cme-295-transformers-large-language-models",
    );

    // 5. Super Study Guide textbook
    const textbookLink = screen.getByRole("link", {
      name: /Super Study Guide website/i,
    });
    expect(textbookLink).toHaveAttribute("href", "https://superstudy.guide");
  });
});
