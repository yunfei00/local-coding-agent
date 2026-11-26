import {describe,it,expect} from "vitest";
import {buildLocalModelConfig} from "./openCodeModelConfig";
const profile={model:"gemma4:31b",context:32768,maxOutput:4096};
const gateway={port:12345,token:"a".repeat(64)};
describe("P2 local provider configuration",()=>{
  it("allows only the named provider through loopback",()=>{
    const config=buildLocalModelConfig(profile,gateway);
    expect(config.model).toBe("lca-ollama/gemma4:31b");
    expect(config.providers["lca-ollama"].settings.baseURL).toBe("http://127.0.0.1:12345/v1");
    expect(config.policies[0].effect).toBe("deny");
    expect(Object.keys(config.providers)).toEqual(["lca-ollama"]);
  });
  it("rejects invalid model, limits and gateway",()=>{
    expect(()=>buildLocalModelConfig({...profile,model:"__proto__"},gateway)).toThrow();
    expect(()=>buildLocalModelConfig({...profile,maxOutput:32768},gateway)).toThrow();
    expect(()=>buildLocalModelConfig(profile,{...gateway,port:65536})).toThrow();
    expect(()=>buildLocalModelConfig(profile,{...gateway,token:"secret"})).toThrow();
  });
});
