import {FormEvent, useEffect, useState} from "react";
import {Modal} from "./Modal";

export function NewProjectDialog({model, onCreated, onClose}: {
  model?:string; onCreated:(event:AgentEnvelope) => Promise<void>; onClose:() => void;
}) {
  const [name, setName] = useState("");
  const [parent, setParent] = useState("");
  const [initializeGit, setInitializeGit] = useState(true);
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    void window.localAgent.projectCreationDefaults().then(value => {if (alive) setParent(value.parent_path);})
      .catch(cause => {if (alive) setError(String(cause));});
    return () => {alive = false;};
  }, []);
  const create = async (event:FormEvent) => {
    event.preventDefault();
    if (busy || picking || !name.trim() || !parent) return;
    setBusy(true); setError("");
    try {
      const result = await window.localAgent.createProject({name:name.trim(), parent_path:parent, initialize_git:initializeGit, model});
      await onCreated(result);
      onClose();
    } catch (cause) {setError(String(cause));}
    finally {setBusy(false);}
  };
  return <Modal title="New project" onClose={onClose} busy={busy || picking}>
    <p className="modal-description">Create a project folder and start a new conversation.</p>
    <form className="modal-form" onSubmit={event => void create(event)}>
      <label>Project name<input autoFocus aria-label="Project name" value={name} maxLength={100} disabled={busy || picking} placeholder="my-project" onChange={e => setName(e.target.value)} required /></label>
      <label>Location<div className="project-location-row"><input aria-label="Project location" value={parent} readOnly title={parent} /><button type="button" disabled={busy || picking} onClick={() => {
        setPicking(true); setError("");
        void window.localAgent.chooseProjectParent(parent).then(result => {if (!result.canceled && result.path) setParent(result.path);})
          .catch(cause => setError(String(cause))).finally(() => setPicking(false));
      }}>Choose…</button></div></label>
      <p className="project-location-preview">A new folder <strong>{name.trim() || "my-project"}</strong> will be created inside this location. Existing folders are kept.</p>
      <label className="modal-checkbox"><input type="checkbox" checked={initializeGit} disabled={busy || picking} onChange={e => setInitializeGit(e.target.checked)} />Initialize Git repository</label>
      <p className="modal-description">Creates an empty repository. Commits and publishing remain explicit Git actions.</p>
      {error ? <p className="error-banner" role="alert">{error}</p> : null}
      <footer className="modal-actions"><button type="button" disabled={busy || picking} onClick={onClose}>Cancel</button><button className="primary-action" type="submit" disabled={busy || picking || !name.trim() || !parent}>{busy ? "Creating…" : "Create project"}</button></footer>
    </form>
  </Modal>;
}
