import {ReactNode, useEffect, useId, useRef} from "react";
import {createPortal} from "react-dom";

/** Native modal provides focus trapping, Escape, and focus restoration. */
export function Modal({title, onClose, busy = false, children}: {
  title:string; onClose:() => void; busy?:boolean; children:ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    return () => element.close();
  }, []);
  return createPortal(<dialog ref={dialog} className="app-modal" aria-labelledby={titleId} aria-modal="true"
    onCancel={event => {event.preventDefault(); if (!busy) onClose();}}
    onClick={event => {
      if (event.target !== event.currentTarget || busy) return;
      const rect = event.currentTarget.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose();
    }}>
    <header className="modal-header"><h2 id={titleId}>{title}</h2><button type="button" aria-label="Close dialog" disabled={busy} onClick={onClose}>×</button></header>
    {children}
  </dialog>, document.body);
}
