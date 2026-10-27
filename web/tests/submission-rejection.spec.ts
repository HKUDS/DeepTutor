import { describe, expect, it } from "vitest";

import { localizedRejectionReason } from "@/lib/submission-rejection";

const t = (key: string) => `t:${key}`;

describe("localizedRejectionReason", () => {
  it("names the mastery path conflict instead of blaming the network", () => {
    expect(
      localizedRejectionReason(
        "mastery_path_busy: path 'topic-1' is already active in session 's-9'",
        t,
      ),
    ).toBe(
      "t:Another session is still working on this topic. Close it or let it finish, then send again.",
    );
  });

  it("names a conversation that moved topics", () => {
    expect(
      localizedRejectionReason(
        "mastery_session_topic_mismatch: session 's-1' is on path 'a', not 'b'",
        t,
      ),
    ).toBe(
      "t:This conversation belongs to a different topic. Open it from that topic and send again.",
    );
  });

  it("passes an unrecognised reason through verbatim", () => {
    expect(localizedRejectionReason("Something new broke.", t)).toBe(
      "Something new broke.",
    );
  });

  it("reports nothing when the request was never refused", () => {
    expect(localizedRejectionReason("", t)).toBe("");
    expect(localizedRejectionReason("   ", t)).toBe("");
  });
});
