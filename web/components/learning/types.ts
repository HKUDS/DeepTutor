export interface WorkspaceProps {
  /** Chat-session-backed learning path id (``book_id`` in the learning API). */
  pathId: string;
}

export interface FeynmanWorkspaceProps extends WorkspaceProps {}
