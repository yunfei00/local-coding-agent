import {describe,it,expect} from "vitest";
import {sharedLocalProfiles} from "./sharedLocalProfiles";
describe("shared local profiles",()=>{
 it("excludes remote, paid and disabled connections and never exports credentials",()=>{
  const connections=[{connection_id:"a",provider_type:"ollama",enabled:true,base_url:"http://localhost:11434",credential_reference:"secret"},{connection_id:"b",provider_type:"openai_compatible",enabled:true,base_url:"http://localhost:11434"},{connection_id:"c",provider_type:"ollama",enabled:true,base_url:"http://remote:11434"}];
  const profiles=connections.map(c=>({connection_id:c.connection_id,model_profile_id:c.connection_id,model_id:"gemma4:31b",context_window:32768,max_output_tokens:2048}));
  expect(sharedLocalProfiles({connections,profiles})).toEqual([{id:"a",label:"gemma4:31b",model:"gemma4:31b",port:11434,baseUrl:"http://localhost:11434",context:32768,maxOutput:2048}]);
 });
 it("preserves the configured LAN Ollama endpoint and model limits",()=>{
  const connections=[{connection_id:"lan",provider_type:"ollama",enabled:true,base_url:"http://192.168.1.20:11435",credential_reference:"secret"}];
  const profiles=[{connection_id:"lan",model_profile_id:"lan-model",model_id:"gemma4:31b",context_window:32768,max_output_tokens:8192}];
  expect(sharedLocalProfiles({connections,profiles})).toEqual([{id:"lan-model",label:"gemma4:31b",model:"gemma4:31b",port:11435,baseUrl:"http://192.168.1.20:11435",context:32768,maxOutput:8192}]);
 });
});
