import {describe,it,expect,vi} from "vitest";
import {OpenCodeSupervisor} from "./openCodeSupervisor";
describe("diagnostic transport gate",()=>{
  it("rejects mutation, prompt and traversal before network access",async()=>{
    const supervisor=new OpenCodeSupervisor();
    const fetchSpy=vi.spyOn(globalThis,"fetch");
    try{
      for(const [route,method] of [["/api/session/s/prompt","POST"],["/api/session/s","PATCH"],["/api/session/..","GET"],["/api/session/%2e%2e","GET"],["/api/info","POST"]]){
        await expect(supervisor.request(route,method)).rejects.toThrow("Route not allowed");
      }
      await expect(supervisor.request("/api/session","POST",{title:"unsafe",permissions:[]})).rejects.toThrow("deny-all");
      await expect(supervisor.request("/api/session/s/interrupt","POST",{resume:true})).rejects.toThrow("Unexpected request body");
      expect(fetchSpy).not.toHaveBeenCalled();
    }finally{fetchSpy.mockRestore();}
  });
  it("allows active-session reconciliation only as a read operation",async()=>{
    const supervisor=new OpenCodeSupervisor();
    const fetchSpy=vi.spyOn(globalThis,"fetch");
    try{
      // A stopped supervisor must reject on availability, not on the route whitelist.
      await expect(supervisor.request("/api/session/active")).rejects.toThrow("Sidecar unavailable");
      await expect(supervisor.request("/api/session/active","POST")).rejects.toThrow("Route not allowed");
      expect(fetchSpy).not.toHaveBeenCalled();
    }finally{fetchSpy.mockRestore();}
  });
});
