import {useEffect, useRef, useState} from "react";
import {createPortal} from "react-dom";

export function ThreadItem({title, active, disabled, onOpen, onRename, onDelete}: {
  title:string; active:boolean; disabled:boolean; onOpen:() => void; onRename:(trigger:HTMLElement) => void; onDelete:(trigger:HTMLElement) => void;
}) {
  const more = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{x:number; y:number} | null>(null);
  const show = (x:number, y:number) => {
    if (!disabled) setPosition({x:Math.max(8, Math.min(x, window.innerWidth - 188)), y:Math.max(8, Math.min(y, window.innerHeight - 96))});
  };
  const showAtButton = () => {
    const rect = more.current!.getBoundingClientRect();
    show(rect.left, rect.bottom + 4);
  };
  useEffect(() => {
    if (!position) return;
    menu.current?.querySelector("button")?.focus();
    const outside = (event:PointerEvent) => {
      if (!menu.current?.contains(event.target as Node) && !more.current?.contains(event.target as Node)) setPosition(null);
    };
    const key = (event:KeyboardEvent) => {
      if (event.key === "Escape") {event.preventDefault(); setPosition(null); more.current?.focus();}
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const buttons = [...menu.current!.querySelectorAll<HTMLButtonElement>("button")];
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        buttons[(index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length]?.focus();
      }
    };
    const dismiss = () => setPosition(null);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    window.addEventListener("resize", dismiss);
    window.addEventListener("scroll", dismiss, true);
    return () => {
      document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", key);
      window.removeEventListener("resize", dismiss); window.removeEventListener("scroll", dismiss, true);
    };
  }, [position]);
  return <div className="thread-row" onContextMenu={event => {event.preventDefault(); show(event.clientX, event.clientY);}}>
    <button className={"thread-item project-tree-thread " + (active ? "active" : "")} disabled={disabled} title={title} onClick={onOpen}
      onKeyDown={event => {if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {event.preventDefault(); showAtButton();}}}>
      <span className="project-tree-thread-icon" aria-hidden="true">◦</span><span className="project-tree-thread-name">{title}</span>
    </button>
    <button className="thread-actions-button" ref={more} aria-label={"More actions for " + title} aria-haspopup="menu" aria-expanded={Boolean(position)} disabled={disabled}
      onClick={() => position ? setPosition(null) : showAtButton()}>⋯</button>
    {position ? createPortal(<div className="thread-context-menu" ref={menu} role="menu" aria-label="Conversation actions" style={{left:position.x, top:position.y}}>
      <button role="menuitem" onClick={() => {setPosition(null); onRename(more.current!);}}>Rename</button>
      <button role="menuitem" className="delete-conversation" onClick={() => {setPosition(null); onDelete(more.current!);}}>Delete</button>
    </div>, document.body) : null}
  </div>;
}
