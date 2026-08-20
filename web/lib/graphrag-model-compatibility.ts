import type { GraphRagModelCompatibility } from "@/lib/knowledge-api";

export interface GraphRagCandidateGate {
  activeKey: string;
  candidateKey: string;
  testedKey: string | null;
  result: GraphRagModelCompatibility | null;
}

/** A successful probe is valid only for the exact, not-yet-active candidate. */
export function canApplyGraphRagModelCandidate({
  activeKey,
  candidateKey,
  testedKey,
  result,
}: GraphRagCandidateGate): boolean {
  return (
    candidateKey !== activeKey &&
    testedKey === candidateKey &&
    result?.compatible === true
  );
}
