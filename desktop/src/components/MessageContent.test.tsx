import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MessageContent } from "./MessageContent";

describe("message rendering", () => {
  it("renders Markdown code and tables without executing HTML or dangerous links", () => {
    const html = renderToStaticMarkup(<MessageContent markdown text={"### Result\n\n```python\nprint(1)\n```\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\n<script>alert(1)</script>\n\n[unsafe](javascript:alert(1))"} />);
    expect(html).toContain("<h3>Result</h3>");
    expect(html).toContain("<table>");
    expect(html).toContain("language-python");
    expect(html).not.toContain("<script>");
    expect(html).not.toContain('href="javascript:');
  });

  it("preserves user input as plain text", () => {
    const html = renderToStaticMarkup(<MessageContent markdown={false} text={"<img src=x onerror=alert(1)>\n**literal**"} />);
    expect(html).not.toContain("<img");
    expect(html).toContain("**literal**");
    expect(html).toContain("&lt;img");
  });
});
