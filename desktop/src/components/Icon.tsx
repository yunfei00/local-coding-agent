const paths = {
  back: "M19 12H5m6-6-6 6 6 6",
  forward: "M5 12h14m-6-6 6 6-6 6",
  sidebar: "M4 4h16v16H4V4ZM9 4v16",
  plus: "M12 5v14M5 12h14",
  compose: "M12 4H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h13a2 2 0 0 0 2-2v-7M16 3l5 5-10 10-4 1 1-4L18 5M14 5l5 5",
  folder: "M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Z",
  settings: "m9 3-.8 3-2.9.8-2.2 2.7L5 12l-1.9 2.5 2.2 2.7 2.9.8L9 21h6l.8-3 2.9-.8 2.2-2.7L19 12l1.9-2.5-2.2-2.7-2.9-.8L15 3H9ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  changes: "M5 3v18M12 6h8M12 12h8M12 18h8",
  task: "m4 7 2 2 4-4M13 7h7M4 16l2 2 4-4M13 16h7",
  context: "M4 4h16v16H4V4ZM9 4v16M13 9h3M13 13h3",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  chevron: "m8 10 4 4 4-4",
  open: "M14 3h7v7M21 3 10 14M10 3H4a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-6"
};

export function Icon({name}: {name:keyof typeof paths}) {
  return <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round"><path d={paths[name]} /></svg>;
}
