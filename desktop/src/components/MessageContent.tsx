import { useRef, useState } from "react";
import Markdown, { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

function CopyButton({ text, label = "Copy" }: { text: string | (() => string); label?: string }) {
  const [status, setStatus] = useState(label);
  return <button type="button" className="copy-button" onClick={() => {
    void window.localAgent.copyText(typeof text === "function" ? text() : text).then(() => setStatus("Copied")).catch(() => setStatus("Copy failed"));
  }}>{status}</button>;
}

function CodeBlock({children}: {children?: React.ReactNode}) {
  const pre = useRef<HTMLPreElement>(null);
  return <div className="code-block"><CopyButton text={() => pre.current?.textContent ?? extractText(children)} label="Copy code" /><pre ref={pre}>{children}</pre></div>;
}

const markdownComponents: Components = {
      // Raw HTML is disabled by react-markdown; javascript: URLs are filtered.
      a: ({ children, href }) => <a href={href} target="_blank" rel="noreferrer">{children}</a>,
      pre: CodeBlock,
};

export function MessageContent({ text, markdown }: { text: string; markdown: boolean }) {
  return <div className="message-content">
    {markdown ? <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{text}</Markdown> : <div className="plain-message">{text}</div>}
    {text && <CopyButton text={text} label="Copy message" />}
  </div>;
}

function extractText(node: unknown): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (node && typeof node === "object" && "props" in node) {
    return extractText((node as { props: { children?: unknown } }).props.children);
  }
  return "";
}
