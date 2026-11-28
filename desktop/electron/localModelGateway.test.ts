import {describe,it,expect} from "vitest";
import {createServer} from "node:http";
import {startCompatibleGateway,startLocalModelGateway} from "./localModelGateway";
describe("local model gateway",()=>{
  it("authenticates, restricts model and tools, and enforces request budget",async()=>{
    let forwarded=0;
    const upstream=createServer(async(req,res)=>{
      forwarded++;
      let raw="";for await(const chunk of req)raw+=String(chunk);
      const body=JSON.parse(raw);
      res.writeHead(200,{"content-type":"application/json"});
      res.end(JSON.stringify({model:body.model,max:body.max_tokens}));
    });
    await new Promise<void>(resolve=>upstream.listen(0,"127.0.0.1",resolve));
    const address=upstream.address();
    if(!address||typeof address==="string")throw new Error("Missing test address");
    const gateway=await startLocalModelGateway("gemma4:31b",address.port,{requests:3,inputBytes:4096,maxOutput:128,durationMs:30000});
    const url="http://127.0.0.1:"+gateway.port+"/v1/chat/completions";
    const call=(body:unknown,token=gateway.token)=>fetch(url,{method:"POST",headers:{authorization:"Bearer "+token,"content-type":"application/json"},body:JSON.stringify(body)});
    const body={model:"gemma4:31b",messages:[{role:"user",content:"hello"}]};
    try{
      expect((await call(body,"wrong")).status).toBe(401);
      expect((await call({...body,model:"other"})).status).toBe(400);
      expect((await call({...body,tools:[{type:"function",function:{name:"write"}}]})).status).toBe(403);
      const result=await call(body);
      expect(result.status).toBe(200);
      expect(await result.json()).toEqual({model:"gemma4:31b",max:128});
      expect((await call(body)).status).toBe(429);
      expect(forwarded).toBe(1);
    }finally{
      await gateway.close();
      await new Promise<void>(resolve=>{upstream.close(()=>resolve());upstream.closeAllConnections();});
    }
  });

  it("forwards upstream status while only the configured upstream receives its credential", async () => {
    const observed: Array<string | undefined> = [];
    const fixtureCredential = "fixture-provider-key-not-a-credential";
    const statuses = [401,403,500,429];
    const upstream = createServer((request,response) => {
      observed.push(request.headers.authorization);
      request.resume();
      response.writeHead(statuses[observed.length - 1], {"content-type":"application/json"});
      response.end(JSON.stringify({error:`fixture upstream echoed ${fixtureCredential}`}));
    });
    await new Promise<void>(resolve => upstream.listen(0,"127.0.0.1",resolve));
    const address = upstream.address();
    if (!address || typeof address === "string") throw new Error("Missing fixture port");
    const gateway = await startCompatibleGateway("selected",{baseUrl:`http://127.0.0.1:${address.port}/v1`,apiKey:fixtureCredential},
      {requests:6,inputBytes:4096,maxOutput:64,durationMs:10000,reserve:async () => {
        if (observed.length === statuses.length) throw new Error("Fixture limit");
      }});
    const call = () => fetch(`http://127.0.0.1:${gateway.port}/v1/chat/completions`,{method:"POST",
      headers:{authorization:"Bearer "+gateway.token},body:JSON.stringify({model:"selected",messages:[{role:"user",content:"test"}]})});
    try {
      for (const status of statuses) {
        const response = await call();
        expect(response.status).toBe(status === 429 ? 402 : status);
        expect(await response.text()).not.toContain(fixtureCredential);
      }
      const rejected = await call();
      expect(rejected.status).toBe(402);
      expect(await rejected.text()).toContain("HTTP 429");
      expect(observed).toEqual(statuses.map(() => "Bearer "+fixtureCredential));
      expect(gateway.usage().upstreamRequests).toBe(statuses.length);
      expect(JSON.stringify(gateway.usage())).not.toContain(fixtureCredential);
    } finally {
      await gateway.close();
      await new Promise<void>(resolve=>{upstream.close(()=>resolve());upstream.closeAllConnections();});
    }
  });
});
