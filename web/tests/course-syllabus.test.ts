import test from "node:test";
import assert from "node:assert/strict";

import {
  parseUnitTopic,
  getLectureMedia,
  unitsToText,
  textToUnits,
  parseLectureTitle,
} from "../components/courses/CourseSyllabus";
import type { SyllabusUnit } from "../lib/courses-api";

test("parseUnitTopic extracts parenthesized concepts with dot separator", () => {
  const result = parseUnitTopic(
    "Unit 1: Background & NLP Tasks (NLP Overview · Language Modeling · Sequence Tasks)",
  );
  assert.equal(result.unitTitle, "Unit 1: Background & NLP Tasks");
  assert.deepEqual(result.concepts, [
    "NLP Overview",
    "Language Modeling",
    "Sequence Tasks",
  ]);
});

test("parseUnitTopic extracts parenthesized concepts with comma separator", () => {
  const result = parseUnitTopic(
    "Unit 1: Background & NLP Tasks (NLP Tasks, Language Modeling, Seq2seq)",
  );
  assert.equal(result.unitTitle, "Unit 1: Background & NLP Tasks");
  assert.deepEqual(result.concepts, [
    "NLP Tasks",
    "Language Modeling",
    "Seq2seq",
  ]);
});

test("parseUnitTopic extracts colon-separated concepts after Unit prefix", () => {
  const result = parseUnitTopic(
    "Unit 1: Background & NLP Tasks: NLP Tasks, Language Modeling, Seq2seq",
  );
  assert.equal(result.unitTitle, "Unit 1: Background & NLP Tasks");
  assert.deepEqual(result.concepts, [
    "NLP Tasks",
    "Language Modeling",
    "Seq2seq",
  ]);
});

test("parseUnitTopic extracts colon-separated concepts without prefix", () => {
  const result = parseUnitTopic(
    "Background & NLP Tasks: NLP Tasks, Language Modeling, Seq2seq",
  );
  assert.equal(result.unitTitle, "Background & NLP Tasks");
  assert.deepEqual(result.concepts, [
    "NLP Tasks",
    "Language Modeling",
    "Seq2seq",
  ]);
});

test("parseUnitTopic handles units without sub-concepts cleanly", () => {
  const result = parseUnitTopic(
    "Unit 1: Pretraining Objectives & Data Curation",
  );
  assert.equal(result.unitTitle, "Unit 1: Pretraining Objectives & Data Curation");
  assert.deepEqual(result.concepts, []);
});

test("getLectureMedia resolves Lecture 1 video and slide links", () => {
  const unit: SyllabusUnit = {
    id: "lecture_1_transformers",
    position: 0,
    title: "Lecture 1 (25/09/2026): Transformers [Video có sẵn]",
    topics: [],
    covered: false,
  };
  const media = getLectureMedia(unit);
  assert.equal(media.videoUrl, "https://www.youtube.com/watch?v=114i2Kz-LZA");
  assert.equal(
    media.slideUrl,
    "https://cme295.stanford.edu/slides/fall26-cme295-lecture1.pdf",
  );
  assert.equal(
    media.mirrorSlideUrl,
    "https://raw.githubusercontent.com/afshinea/stanford-cme-295-transformers-large-language-models/main/en/cheatsheet-transformers-large-language-models.pdf",
  );
  assert.equal(
    media.readingWorkspaceUrl,
    "/learning/reading/rw_3f8b01ffbee24ecf9ad3f21e1d2f11ae",
  );
  assert.equal(media.isVideoUpcoming, false);
});

test("getLectureMedia resolves Lecture 2 slide and upcoming video badge", () => {
  const unit: SyllabusUnit = {
    id: "lecture_2_llms",
    position: 1,
    title: "Lecture 2 (02/10/2026): Large Language Models [Slide có sẵn]",
    topics: [],
    covered: false,
  };
  const media = getLectureMedia(unit);
  assert.equal(media.videoUrl, undefined);
  assert.equal(
    media.slideUrl,
    "https://cme295.stanford.edu/slides/fall26-cme295-lecture2.pdf",
  );
  assert.equal(media.isVideoUpcoming, true);
  assert.equal(media.isSlideUpcoming, false);
});

test("getLectureMedia resolves upcoming slide status for Lecture 3 without broken 404 links", () => {
  const unit: SyllabusUnit = {
    id: "lecture_3_training",
    position: 2,
    title: "Lecture 3 (09/10/2026): Training & Scaling Laws",
    topics: [],
    covered: false,
  };
  const media = getLectureMedia(unit);
  assert.equal(media.slideUrl, undefined);
  assert.equal(media.isVideoUpcoming, true);
  assert.equal(media.isSlideUpcoming, true);
});

test("getLectureMedia falls back by title matching when unit.id is generic", () => {
  const unit: SyllabusUnit = {
    id: "random_id_123",
    position: 0,
    title: "Lecture 1: Transformers & Attention",
    topics: [],
    covered: false,
  };
  const media = getLectureMedia(unit);
  assert.equal(media.videoUrl, "https://www.youtube.com/watch?v=114i2Kz-LZA");
  assert.equal(
    media.slideUrl,
    "https://cme295.stanford.edu/slides/fall26-cme295-lecture1.pdf",
  );
});

test("unitsToText and textToUnits preserve IDs and topics", () => {
  const existing: SyllabusUnit[] = [
    {
      id: "u1",
      position: 0,
      title: "Lecture 1",
      topics: ["Unit 1 (NLP · BERT)", "Unit 2 (GPT · T5)"],
      covered: true,
    },
    {
      id: "u2",
      position: 1,
      title: "Lecture 2",
      topics: ["Unit 3"],
      covered: false,
    },
  ];

  const text = unitsToText(existing);
  const parsed = textToUnits(text, existing);

  assert.equal(parsed.length, 2);
  assert.equal(parsed[0].id, "u1");
  assert.equal(parsed[0].title, "Lecture 1");
  assert.deepEqual(parsed[0].topics, ["Unit 1 (NLP · BERT)", "Unit 2 (GPT · T5)"]);
  assert.equal(parsed[1].id, "u2");
  assert.equal(parsed[1].title, "Lecture 2");
  assert.deepEqual(parsed[1].topics, ["Unit 3"]);
});

test("parseLectureTitle parses badges and tags in English and other languages", () => {
  const l1En = parseLectureTitle("Lecture 1: Transformers [Video available]");
  assert.equal(l1En.cleanTitle, "Lecture 1: Transformers");
  assert.equal(l1En.badge?.variant, "video");

  const l2En = parseLectureTitle("Lecture 2: LLMs [Slide available]");
  assert.equal(l2En.cleanTitle, "Lecture 2: LLMs");
  assert.equal(l2En.badge?.variant, "slide");

  const l3En = parseLectureTitle("Lecture 3: Training [Upcoming]");
  assert.equal(l3En.cleanTitle, "Lecture 3: Training");
  assert.equal(l3En.badge?.variant, "upcoming");

  const examEn = parseLectureTitle("Midterm Exam [Midterm Exam]");
  assert.equal(examEn.cleanTitle, "Midterm Exam");
  assert.equal(examEn.badge?.variant, "exam");

  const l1Vi = parseLectureTitle("Lecture 1: Transformers [Video có sẵn]");
  assert.equal(l1Vi.cleanTitle, "Lecture 1: Transformers");
  assert.equal(l1Vi.badge?.variant, "video");

  const examVi = parseLectureTitle("Midterm Exam [Thi giữa kỳ]");
  assert.equal(examVi.cleanTitle, "Midterm Exam");
  assert.equal(examVi.badge?.variant, "exam");
});
