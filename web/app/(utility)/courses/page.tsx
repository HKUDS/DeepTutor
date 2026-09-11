"use client";

import CoursesShelf from "@/components/courses/CoursesShelf";

/**
 * The Courses index — a top-level surface, sibling to Mastery Path and
 * Immersive Reading rather than a shelf inside the Learning Space.
 *
 * The shelf component is the whole page: adding a page-level heading above it
 * would put two titles on one screen saying the same thing.
 */
export default function CoursesPage() {
  return <CoursesShelf />;
}
