type AnswerFragment = {text:string; reasoning:string};

// Older Ollama templates can emit an unlabelled prefix followed by a closing
// think marker. Keep the ambiguous prefix out of the answer until it is classified.
export class OpenCodeAnswer {
  private state: "start" | "reasoning" | "text";
  private pending = "";

  constructor(taggedThinking: boolean) {
    this.state = taggedThinking ? "start" : "text";
  }

  separatedReasoning() {
    if (this.state === "start" && !this.pending.trim()) this.state = "text";
  }

  push(delta: string, finish = false): AnswerFragment {
    this.pending += delta;
    const output = {text:"",reasoning:""};
    if (this.state === "start") {
      const start = this.pending.trimStart();
      if (start.startsWith("<think>")) {
        this.state = "reasoning";
        this.pending = start.slice(7);
      } else if (/(?:^|\r?\n)[\t ]*<\/think>(?=[\s]|$)/.test(this.pending)) {
        this.state = "reasoning";
      } else if (finish) {
        this.state = "text";
      } else {
        return output;
      }
    }
    if (this.state === "reasoning") {
      const end = this.pending.indexOf("</think>");
      if (end >= 0) {
        output.reasoning = this.pending.slice(0,end);
        this.pending = this.pending.slice(end+8);
        this.state = "text";
      } else {
        const boundary = finish ? this.pending.length : Math.max(0,this.pending.length-7);
        output.reasoning = this.pending.slice(0,boundary);
        this.pending = this.pending.slice(boundary);
        return output;
      }
    }
    output.text = this.pending;
    this.pending = "";
    return output;
  }
}
