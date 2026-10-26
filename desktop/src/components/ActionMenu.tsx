import {ReactNode, useEffect, useId, useRef, useState} from "react";
import {createPortal} from "react-dom";

type Action = {label:string; onSelect:() => void; disabled?:boolean};

/** Anchored menu with keyboard navigation and focus restoration. */
export function ActionMenu({label, children, actions, disabled = false, className = ""}: {
  label:string; children:ReactNode; actions:Action[]; disabled?:boolean; className?:string;
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const id = useId();
  const [position, setPosition] = useState<{left:number; top:number} | null>(null);
  const close = (restore = false) => {setPosition(null); if (restore) trigger.current?.focus();};
  const open = () => {
    const rect = trigger.current!.getBoundingClientRect();
    setPosition({left:Math.max(8, Math.min(rect.left, window.innerWidth - 248)), top:rect.bottom + 6});
  };
  useEffect(() => {
    if (!position) return;
    // Keep the full menu inside the viewport, including at high display scaling.
    const element = menu.current!;
    element.style.top = Math.max(8, Math.min(position.top, window.innerHeight - element.offsetHeight - 8)) + "px";
    element.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
    const outside = (event:PointerEvent) => {
      if (!element.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) close();
    };
    const dismiss = () => close();
    document.addEventListener("pointerdown", outside);
    window.addEventListener("resize", dismiss);
    window.addEventListener("scroll", dismiss, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      window.removeEventListener("resize", dismiss);
      window.removeEventListener("scroll", dismiss, true);
    };
  }, [position]);
  useEffect(() => {if (disabled) setPosition(null);}, [disabled]);
  return <>
    <button ref={trigger} type="button" className={className} aria-label={label} title={label}
      aria-haspopup="menu" aria-expanded={Boolean(position)} aria-controls={position ? id : undefined} disabled={disabled}
      onClick={() => position ? close(true) : open()}
      onKeyDown={event => {if (event.key === "ArrowDown" || event.key === "ArrowUp") {event.preventDefault(); open();}}}>
      {children}
    </button>
    {position ? createPortal(<div ref={menu} id={id} role="menu" aria-label={label} className="action-menu" style={position}
      onKeyDown={event => {
        const buttons = [...menu.current!.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        if (event.key === "Escape") {event.preventDefault(); event.stopPropagation(); close(true);}
        else if (event.key === "Tab") close();
        else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
          event.preventDefault();
          const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
            : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
          buttons[next]?.focus();
        }
      }}>
      {actions.map(action => <button type="button" role="menuitem" key={action.label} disabled={action.disabled}
        onClick={() => {close(true); action.onSelect();}}>{action.label}</button>)}
    </div>, document.body) : null}
  </>;
}
