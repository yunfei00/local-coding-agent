import {describe, expect, it} from "vitest";
import {taskConfigOverrides, TaskConfig, longTaskBudget, defaultModelOutput, codingOutputProfile} from "./modelCatalog";

const saved: TaskConfig = {strategy:"local-only", budget:{api_calls:0,api_tokens:0,global_api_calls:30}, verification_commands:[], roles:{planner:{route:"local",model:"old",model_profile_id:"local-old",context_window:32768,output_limit:1024,tool_mode:"auto",input_price:null,output_price:null}}};

describe("Task edits over latest Settings", () => {
  it('uses a coding output default for new API profiles while keeping the local default', () => {
    expect(defaultModelOutput('openai_compatible')).toBe(8192);
    expect(defaultModelOutput('ollama')).toBe(1024);
  });
  it('raises only the selected profile output and preserves larger limits and identity', () => {
    const original={model_profile_id:'selected',connection_id:'api',model_id:'model',display_name:'Model',
      max_output_tokens:1024,context_window:65536,pricing:{input_price:1},supports_vision:true};
    expect(codingOutputProfile(original)).toEqual({...original,max_output_tokens:8192});
    expect(original.max_output_tokens).toBe(1024);
    expect(codingOutputProfile({...original,max_output_tokens:16384}).max_output_tokens).toBe(16384);
  });
  it("explicitly extends small budgets while retaining prices, retries and bindings", () => {
    const original: TaskConfig = {...saved,budget:{...saved.budget,api_cost:2,local_repairs:3,request_seconds:60}};
    const next = longTaskBudget(original);
    expect(next.budget).toMatchObject({api_calls:200,api_tokens:10000000,global_api_calls:2000,
      global_api_tokens:100000000,task_seconds:7200,api_cost:2,local_repairs:3,request_seconds:60});
    expect(next.roles).toBe(original.roles);
    expect(original.budget.api_calls).toBe(0);
    expect(longTaskBudget({...next,budget:{...next.budget,api_tokens:20000000}}).budget.api_tokens).toBe(20000000);
    expect(taskConfigOverrides(original,next)).toEqual({budget:{api_calls:200,api_tokens:10000000,
      global_api_calls:2000,global_api_tokens:100000000,task_seconds:7200}});
  });
  it("adds or clears a deliberate GUI contract without replaying saved model settings", () => {
    const gui={command:"npm start",window_title:"App",steps:[]};
    expect(taskConfigOverrides(saved,{...saved,gui_verification:gui})).toEqual({gui_verification:gui});
    expect(taskConfigOverrides({...saved,gui_verification:gui},{...saved,gui_verification:null})).toEqual({gui_verification:null});
  });
  it("does not send cached defaults as explicit overrides", () => {
    expect(taskConfigOverrides(saved, structuredClone(saved))).toEqual({});
  });
  it("strategy edits cannot replay stale zero budgets or Planner bindings", () => {
    expect(taskConfigOverrides(saved, {...saved,strategy:"api-only"})).toEqual({strategy:"api-only"});
  });
  it("retains deliberate zero budgets and only changed nested fields", () => {
    const nonzero = {...saved,budget:{...saved.budget,api_calls:3}};
    expect(taskConfigOverrides(nonzero, {...nonzero,budget:{...nonzero.budget,api_calls:0}})).toEqual({budget:{api_calls:0}});
    expect(taskConfigOverrides(saved, {...saved,roles:{planner:{...saved.roles.planner,model_profile_id:"online"}},verification_commands:["uv run python -m unittest"]})).toEqual({roles:{planner:{model_profile_id:"online"}},verification_commands:["uv run python -m unittest"]});
  });
  it("keeps per-task overrides on subsequent tasks after refreshing Settings", () => {
    const latest = {...saved,strategy:"local-first",budget:{...saved.budget,api_calls:6}};
    const effective = {...latest,strategy:"api-only",budget:{...latest.budget,api_calls:0}};
    expect(taskConfigOverrides(latest,effective)).toEqual({strategy:"api-only",budget:{api_calls:0}});
  });
});
