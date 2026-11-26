import {describe,it,expect} from "vitest";
import {sharedLocalProfiles} from "./sharedLocalProfiles";
describe("shared local profiles",()=>{
 it("excludes remote, paid and disabled connections and never exports credentials",()=>{
  const connections=[{connection_id:"a",provider_type:"ollama",enabled:true,base_url:"http://localhost:11434",credential_reference:"secret"},{connection_id:"b",provider_type:"openai_compatible",enabled:true,base_url:"http://localhost:11434"},{connection_id:"c",provider_type:"ollama",enabled:true,base_url:"http://remote:11434"}];
  const profiles=connections.map(c=>({connection_id:c.connection_id,model_profile_id:c.connection_id,model_id:"gemma4:31b",context_window:32768,max_output_tokens:2048}));
  expect(sharedLocalProfiles({connections,profiles})).toEqual([{id:"a",label:"gemma4:31b",model:"gemma4:31b",port:11434,context:32768,maxOutput:2048}]);
 });
});
