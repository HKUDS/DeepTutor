import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CourseMaterials from "@/components/courses/CourseMaterials";
import { initI18n } from "@/i18n/init";

initI18n("en");

describe("CourseMaterials", () => {
  it("renders official syllabus link, slides, videos, cheatsheet, and textbook", () => {
    render(<CourseMaterials />);

    // 1. Official Syllabus Website link
    const syllabusLink = screen.getByRole("link", {
      name: /official syllabus website/i,
    });
    expect(syllabusLink).toHaveAttribute(
      "href",
      "https://cme295.stanford.edu/syllabus/",
    );

    // 2. Lecture Slides (PDF) directory & fallback mirrors
    expect(screen.getByText("fall26-cme295-lecture1.pdf")).toBeInTheDocument();
    expect(screen.getByText("fall26-cme295-lecture2.pdf")).toBeInTheDocument();
    const mirrorLinks = screen.getAllByRole("link", {
      name: /GitHub mirror/i,
    });
    expect(mirrorLinks.length).toBeGreaterThanOrEqual(1);
    expect(mirrorLinks[0]).toHaveAttribute(
      "href",
      "https://raw.githubusercontent.com/afshinea/stanford-cme-295-transformers-large-language-models/main/en/cheatsheet-transformers-large-language-models.pdf",
    );
    const readOnDeepTutorLink = screen.getByRole("link", {
      name: /Read on DeepTutor/i,
    });
    expect(readOnDeepTutorLink).toHaveAttribute(
      "href",
      "/learning/reading/rw_3f8b01ffbee24ecf9ad3f21e1d2f11ae",
    );
    expect(
      screen.getByText(
        /If Stanford server times out, use GitHub mirror or DeepTutor reading workspace/i,
      ),
    ).toBeInTheDocument();

    // 3. Video & Lectures: YouTube ID & Timed Transcript
    expect(screen.getByText(/YouTube: 114i2Kz-LZA/i)).toBeInTheDocument();
    const youtubeLink = screen.getByRole("link", {
      name: /YouTube \(opens in new tab\)/i,
    });
    expect(youtubeLink).toHaveAttribute(
      "href",
      "https://www.youtube.com/watch?v=114i2Kz-LZA",
    );
    const transcriptLink = screen.getByRole("link", {
      name: /timed media transcript/i,
    });
    expect(transcriptLink).toHaveAttribute(
      "href",
      "/learning/watching?video=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D114i2Kz-LZA",
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
      name: /VIP cheatsheet and code repository on GitHub/i,
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
