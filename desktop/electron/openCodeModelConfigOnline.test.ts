import {describe,it,expect} from "vitest";
import {validateOnlineModelProfile,activateOnlineProvider} from "./openCodeModelConfigOnline";
describe("online provider safety",()=>{
  const profile={model:"example-model",baseURL:"https://example.com/v1",credentialId:"stored-key"};
  it("validates metadata but refuses activation",()=>{
    expect(validateOnlineModelProfile(profile)).toEqual(profile);
    expect(()=>activateOnlineProvider()).toThrow("hard budget gate");
  });
  it("rejects insecure URLs and embedded credentials",()=>{
    for(const baseURL of ["http://example.com/v1","https://user:pass@example.com/v1","https://example.com/v1?key=secret"]){
      expect(()=>validateOnlineModelProfile({...profile,baseURL})).toThrow();
    }
  });
});
