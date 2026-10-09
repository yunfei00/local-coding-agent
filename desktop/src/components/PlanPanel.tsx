import { useEffect, useState } from "react";

type Step = { id: string; description: string; state: string; verification?: string; evidence?: Array<Record<string, unknown>> };
type Plan = { id: string; goal: string; steps: Step[] };
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
    if (next.state === "blocked") {
      setError("This step is blocked. Resolve the failure and change its state to in_progress before continuing.");
      return;
    }
    if (!window.confirm("Continue from step: " + next.description +
      "\nReview workspace changes before proceeding. Previously completed steps will not be requested again.")) return;
    setBusy(true); setError("");
    try {
      await window.localAgent.startTurn(threadId,
        "Continue the existing persistent task plan from its first unfinished step: " +
        next.description + ". First inspect current workspace and checkpoint state. " +
        "Do not replay completed steps or repeat mutating commands. " +
        "Run the step verification and report actual evidence.");
      onClose();
    } catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  };
  useEffect(() => { setPlans([]); void request("plan.list"); }, [threadId]);
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
        <div className="context-pin-input">
          <button type="button" disabled={busy} onClick={() => void request("plan.checkpoint", {plan_id: plan.id})}>Checkpoint</button>
          <button type="button" disabled={busy} onClick={() => void request("plan.resume", {plan_id: plan.id})}>Resume info</button>
          <button type="button" disabled={busy} onClick={() => void continuePlan(plan)}>Continue plan</button>
        </div>
        {checkpoint ? <pre style={{whiteSpace:"pre-wrap", overflowWrap:"anywhere"}}>{JSON.stringify(checkpoint, null, 2)}</pre> : null}
        {plan.steps.map((step, index) => <div className="context-file-row" key={step.id}>
          <span>{index + 1}. {step.description} — {step.state}</span>
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
              const evidence = state === "completed" ? window.prompt("Verification evidence (required)") : null;
              if (state === "completed" && !evidence?.trim()) return;
              void request("plan.step.update", {plan_id: plan.id, step_id: step.id, state,
                evidence: evidence ? [{note: evidence}] : undefined});
            }}>
            {["pending", "in_progress", "blocked", "skipped", "completed"].map(state => <option key={state} value={state}>{state}</option>)}
          </select>
        </div>)}
      </section>)}
    </div>
  </aside>;
}
