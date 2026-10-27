import { useEffect, useState } from "react";
import {RecentExecutions} from "./RecentExecutions";
import {AgentContextEvidence, type WorkingMemory} from "./AgentContextEvidence";

type Step = { id: string; description: string; state: string; verification?: string; evidence?: Array<Record<string, unknown>>;
  recovery?: {category?:string; summary?:string; action?:string};
  executions?: Array<{call_id: string; tool: string; status: string; exit_code?: number | null; metadata?:{duration_ms?:number;error_code?:string;diagnosis?:{category:string;summary:string;action:string}}}> };
type Plan = { id: string; goal: string; steps: Step[]; execution?: {calls:number;continuations:number;reserved_tokens:number;elapsed:number;status:string;last_error?:string;working_memory?:WorkingMemory;repository_instructions?:Array<{path:string;sha256:string}>;limits:{model_calls:number;tokens:number;seconds:number;max_continuations:number}} };
export function PlanPanel({ threadId, onClose }: { threadId: string; onClose: () => void }) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [goal, setGoal] = useState("");
  const [stepsText, setStepsText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [checkpoint, setCheckpoint] = useState<Record<string, unknown> | null>(null);
  const request = async (operation: string, payload: Record<string, unknown> = {}) => {
    setBusy(true); setError("");
    try {
      const event = await window.localAgent.planRequest(threadId, operation, payload);
      if (operation === "plan.resume") {
        const checkpoint = event.payload?.checkpoint as { reason?: string } | null;
        const nextStep = event.payload?.next_step as { description?: string } | null;
        setCheckpoint(checkpoint ? (checkpoint as Record<string, unknown>) : null);
        setError(nextStep ? "Resume from: " + nextStep.description + ". Verify workspace before continuing; no tools replayed." : (checkpoint ? "Plan has no unfinished steps." : "No checkpoint yet."));
      } else {
        setPlans((event.payload?.plans as Plan[]) ?? []);
      }
    } catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  };
  const continuePlan = async (plan: Plan) => {
    const next = plan.steps.find(step => step.state !== "completed" && step.state !== "skipped");
    if (!next) { setError("All plan steps are complete."); return; }
    if (!window.confirm("Continue from step: " + next.description +
      "\nReview workspace changes before proceeding. Previously completed steps will not be requested again.")) return;
    setBusy(true); setError("");
    try {
      const recovered = await window.localAgent.planRequest(threadId, "plan.recover", {plan_id: plan.id});
      if (recovered.payload?.autonomous_task_id) {
        await window.localAgent.taskRequest(threadId,"task.resume",{task_id:plan.id,confirm_workspace:true});
        onClose(); return;
      }
      await window.localAgent.planRequest(threadId, "plan.resume.confirm", {plan_id: plan.id});
      await window.localAgent.startTurn(threadId,
        "Continue the existing persistent task plan from its first unfinished step: " +
        next.description + ". First inspect current workspace and checkpoint state. " +
        "Do not replay completed steps or repeat mutating commands. " +
        "Run the step verification and report actual evidence.");
      onClose();
    } catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  };
  useEffect(() => {
    setPlans([]); setCheckpoint(null); void request("plan.list");
    return window.localAgent.onAgentEvent((event: AgentEnvelope) => {
      if (event.thread_id === threadId && ["plan.completed", "plan.step.completed", "tool.completed", "turn.completed", "turn.cancelled", "turn.failed", "turn.continuing", "execution.updated"].includes(event.type)) void request("plan.list");
    });
  }, [threadId]);
  return <aside className="context-overlay" aria-label="Task plans">
    <div className="context-panel">
      <header className="context-panel-header"><div><span className="eyebrow">PERSISTENT TASK PLANS</span>
        <h2>Thread plan</h2><p>Steps and checkpoints survive restart. Completed steps require evidence.</p></div>
        <button type="button" className="panel-close" onClick={onClose}>Close</button></header>
      {error ? <div className="error-banner">{error}</div> : null}
      <section className="context-section"><h3>New plan</h3>
        <input value={goal} placeholder="Goal" onChange={e => setGoal(e.target.value)} />
        <textarea value={stepsText} placeholder="One step per line" onChange={e => setStepsText(e.target.value)} />
        <button type="button" disabled={busy || !goal.trim() || !stepsText.trim()}
          onClick={() => void request("plan.create", {goal, steps: stepsText.split("\n").map(description => ({description: description.trim()})).filter(s => s.description)}).then(() => {setGoal("");setStepsText("");})}>Create plan</button>
      </section>
      {plans.map(plan => <section className="context-section" key={plan.id}>
        <h3>{plan.goal}</h3>
        {plan.execution ? <p>累计模型调用 {plan.execution.calls}/{plan.execution.limits.model_calls} · 续跑 {plan.execution.continuations}/{plan.execution.limits.max_continuations} · Token 保守预留 {plan.execution.reserved_tokens}/{plan.execution.limits.tokens}</p> : null}
        {plan.execution ? <p>活动执行 {plan.execution.elapsed.toFixed(1)}/{plan.execution.limits.seconds} 秒 · {plan.execution.status} {plan.execution.last_error ?? ""}</p> : null}
        <AgentContextEvidence memory={plan.execution?.working_memory} instructions={plan.execution?.repository_instructions}/>
        <RecentExecutions calls={plan.steps.flatMap(s => s.executions ?? [])} />
        <div className="context-pin-input">
          <button type="button" disabled={busy} onClick={() => void request("plan.checkpoint", {plan_id: plan.id})}>Checkpoint</button>
          <button type="button" disabled={busy} onClick={() => void request("plan.resume", {plan_id: plan.id})}>Resume info</button>
          <button type="button" disabled={busy} onClick={() => void continuePlan(plan)}>Continue plan</button>
          {plan.execution ? <button disabled={busy} onClick={() => {if (window.confirm("明确增加累计执行预算：16 次模型调用、500000 Token 保守预留、300 秒和 1 次续跑。既有消耗不会清零；恢复后可能产生在线费用。")) void request("plan.execution.extend",{plan_id:plan.id});}}>增加执行预算</button> : null}
        </div>
        {checkpoint ? <pre style={{whiteSpace:"pre-wrap", overflowWrap:"anywhere"}}>{JSON.stringify(checkpoint, null, 2)}</pre> : null}
        {plan.steps.map((step, index) => <div className="context-file-row" key={step.id}>
          <span>{index + 1}. {step.description} — {step.state}</span>
          {step.state === "blocked" && step.recovery?.summary ? <p role="status">{step.recovery.category}: {step.recovery.summary} 下一步：{step.recovery.action}。使用 Continue plan 安全恢复。</p> : null}
          {step.state === "pending" ? <>
            <button type="button" disabled={busy} onClick={() => {
              const description = window.prompt("Edit step description", step.description);
              if (!description?.trim()) return;
              void request("plan.step.edit", {plan_id:plan.id,step_id:step.id,description,verification:step.verification ?? ""});
            }}>Edit</button>
            <button type="button" disabled={busy || index === 0 || plan.steps[index - 1].state !== "pending"} onClick={() => {
              const ids = plan.steps.map(item => item.id);
              [ids[index - 1], ids[index]] = [ids[index], ids[index - 1]];
              void request("plan.steps.reorder", {plan_id:plan.id,step_ids:ids});
            }}>↑</button>
            <button type="button" disabled={busy || index === plan.steps.length - 1 || plan.steps[index + 1].state !== "pending"} onClick={() => {
              const ids = plan.steps.map(item => item.id);
              [ids[index], ids[index + 1]] = [ids[index + 1], ids[index]];
              void request("plan.steps.reorder", {plan_id:plan.id,step_ids:ids});
            }}>↓</button>
          </> : null}
          <select value={step.state} disabled={busy} aria-label={"State for " + step.description}
            onChange={e => {
              const state = e.target.value;
              const callIds = step.executions?.filter(call => call.status === "succeeded").map(call => call.call_id) ?? [];
              if (state === "completed" && !callIds.length) { setError("This step has no successful runtime tool evidence yet."); return; }
              void request("plan.step.update", {plan_id: plan.id, step_id: step.id, state,
                tool_call_ids: callIds});
            }}>
            {["pending", "in_progress", "blocked", "skipped", "completed"].map(state => <option key={state} value={state}>{state}</option>)}
          </select>
        </div>)}
      </section>)}
    </div>
  </aside>;
}
