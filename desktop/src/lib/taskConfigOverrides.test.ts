import {describe, expect, it} from "vitest";
import {taskConfigOverrides, TaskConfig} from "./modelCatalog";

const saved: TaskConfig = {strategy:"local-only", budget:{api_calls:0,api_tokens:0,global_api_calls:30}, verification_commands:[], roles:{planner:{route:"local",model:"old",model_profile_id:"local-old",context_window:32768,output_limit:1024,tool_mode:"auto",input_price:null,output_price:null}}};

describe("Task edits over latest Settings", () => {
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
