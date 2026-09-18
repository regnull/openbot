// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import MarkdownContent from "./MarkdownContent";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function renderContent(content: string) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<MarkdownContent content={content} />);
  });
  return { container, cleanup: () => { root.unmount(); container.remove(); } };
}

describe("MarkdownContent", () => {
  let cleanup = () => {};
  afterEach(() => cleanup());
  it("renders common markdown without leaking syntax", async () => {
    const rendered = await renderContent('# Title\n\n**bold** and `code`\n\n- item\n\n> quote\n\n```ts\nconst x = 1;\n```');
    cleanup = rendered.cleanup;
    expect(rendered.container.querySelector("h1")?.textContent).toBe("Title");
    expect(rendered.container.querySelector("strong")?.textContent).toBe("bold");
    expect(rendered.container.textContent).toContain("const x = 1;");
    expect(rendered.container.textContent).not.toContain("**bold**");
  });
  it("renders quoted content as a blockquote for readable themed styling", async () => {
    const rendered = await renderContent("> quoted reply");
    cleanup = rendered.cleanup;
    const quote = rendered.container.querySelector("blockquote");

    expect(quote).not.toBeNull();
    expect(quote?.textContent).toContain("quoted reply");
  });
  it("removes unsafe HTML and javascript links", async () => {
    const rendered = await renderContent('<script>alert(1)</script> [bad](javascript:alert(1))');
    cleanup = rendered.cleanup;
    expect(rendered.container.querySelector("script")).toBeNull();
    expect(rendered.container.querySelector('a[href^="javascript:"]')).toBeNull();
  });
});
