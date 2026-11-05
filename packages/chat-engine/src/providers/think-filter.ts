/** Split inline thinking tags even when the provider splits a tag across deltas. */
export class ThinkFilter {
  private pending = "";
  private thinking = false;
  feed(text: string, final = false): Array<["content" | "thinking", string]> {
    this.pending += text;
    const out: Array<["content" | "thinking", string]> = [];
    while (this.pending) {
      const tag = this.thinking ? "</think>" : "<think>";
      const at = this.pending.indexOf(tag);
      if (at >= 0) {
        if (at)
          out.push([
            this.thinking ? "thinking" : "content",
            this.pending.slice(0, at),
          ]);
        this.pending = this.pending.slice(at + tag.length);
        this.thinking = !this.thinking;
        continue;
      }
      let held = 0;
      if (!final)
        for (let n = 1; n < tag.length; n++)
          if (this.pending.endsWith(tag.slice(0, n))) held = n;
      const ready = this.pending.slice(0, this.pending.length - held);
      if (ready) out.push([this.thinking ? "thinking" : "content", ready]);
      this.pending = held ? this.pending.slice(-held) : "";
      break;
    }
    return out;
  }
}
