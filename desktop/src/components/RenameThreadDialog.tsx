import {useEffect, useRef, useState} from "react";
import {Modal} from "./Modal";

export function RenameThreadDialog({title, onSave, onClose}: {
  title:string; onSave:(title:string) => Promise<void>; onClose:() => void;
}) {
  const [value, setValue] = useState(title);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {input.current?.select();}, []);
  return <Modal title="Rename thread" onClose={onClose} busy={busy}>
    <form className="modal-form" onSubmit={event => {
      event.preventDefault();
      if (busy || !value.trim()) return;
      setBusy(true); setError("");
      void onSave(value.trim()).then(onClose).catch(cause => setError(String(cause))).finally(() => setBusy(false));
    }}>
      <label htmlFor="thread-rename-input">Name</label>
      <input id="thread-rename-input" ref={input} autoFocus maxLength={120} value={value} disabled={busy} onChange={event => setValue(event.target.value)} />
      {error ? <p className="error-banner" role="alert">{error}</p> : null}
      <footer className="modal-actions"><button type="button" disabled={busy} onClick={onClose}>Cancel</button><button className="primary-action" type="submit" disabled={busy || !value.trim()}>{busy ? "Saving…" : "Save"}</button></footer>
    </form>
  </Modal>;
}
