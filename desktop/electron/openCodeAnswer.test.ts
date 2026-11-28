import {describe,expect,it} from "vitest";
import {OpenCodeAnswer} from "./openCodeAnswer";

describe("OpenCode answer framing",()=>{
  it("separates split legacy Ollama tags in live and recovered text",()=>{
    const answer = new OpenCodeAnswer(true);
    const chunks = ["\n<thi","nk>English reasoning","</thi","nk>","中文回复"];
    const fragments = chunks.map(chunk=>answer.push(chunk)).concat(answer.push("",true));
    expect(fragments.map(fragment=>fragment.text).join("")).toBe("中文回复");
    expect(fragments.map(fragment=>fragment.reasoning).join("")).toBe("English reasoning");
    expect(new OpenCodeAnswer(true).push(chunks.join(""),true).text).toBe("中文回复");
  });

  it("keeps an unfinished reasoning block out of the answer and preserves literal markup",()=>{
    expect(new OpenCodeAnswer(true).push("<think>unfinished",true)).toEqual({text:"",reasoning:"unfinished"});
    const literal = "Show the literal <think> syntax";
    expect(new OpenCodeAnswer(true).push(literal,true).text).toBe(literal);
    expect(new OpenCodeAnswer(false).push("<think>literal",true).text).toBe("<think>literal");
  });

  it("does not expose Ollama's unlabelled reasoning prefix before the closing tag",()=>{
    const answer=new OpenCodeAnswer(true);
    expect(answer.push("English prefix without an opening marker")).toEqual({text:"",reasoning:""});
    expect(answer.push("\n</think>\n正式回复")).toEqual({text:"\n正式回复",reasoning:"English prefix without an opening marker\n"});
    const structured=new OpenCodeAnswer(true);
    structured.separatedReasoning();
    expect(structured.push("正文立即流式输出").text).toBe("正文立即流式输出");
  });
});
