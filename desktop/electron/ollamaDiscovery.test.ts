import {describe,it,expect,vi} from "vitest";
import {discoverOllamaModels} from "./ollamaDiscovery";
describe("Ollama discovery",()=>{
 it("returns unique valid names from loopback only",async()=>{
  const fetcher=vi.fn(async()=>new Response(JSON.stringify({models:[{name:"gemma4:31b"},{name:"gemma4:31b"},{name:"bad name"},{name:"gpt-oss:20b"}]})));
  expect(await discoverOllamaModels(11434,fetcher)).toEqual(["gemma4:31b","gpt-oss:20b"]);
  expect(fetcher).toHaveBeenCalledWith("http://127.0.0.1:11434/api/tags",expect.objectContaining({redirect:"error"}));
 });
 it("rejects invalid port before network access",async()=>{
  const fetcher=vi.fn();await expect(discoverOllamaModels(0,fetcher)).rejects.toThrow("port");expect(fetcher).not.toHaveBeenCalled();
 });
});
