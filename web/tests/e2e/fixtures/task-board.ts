import type { TaskBoard } from "../../../lib/task-board-api";

export const emptyTaskBoard: TaskBoard = {
  cards: [],
  session_links: [],
  colors: { todo: "#2563eb", doing: "#a16207", done: "#15803d" },
  revision: 0,
};
