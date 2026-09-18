// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { createRoot } from "react-dom/client";
import MarkdownContent from "./MarkdownContent";

function renderContent(content: string) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  root.render(<MarkdownContent content={content} />);
  return { container, cleanup: () => { root.unmount(); container.remove(); } };
}
const tick = () => new Promise((resolve) => setTimeout(resolve, 10));

describe("MarkdownContent", () => {
  let cleanup = () => {};
  afterEach(() => cleanup());
  it("renders common markdown without leaking syntax", async () => {
    const rendered = renderContent('# Title\n\n**bold** and `code`\n\n- item\n\n> quote\n\n```ts\nconst x = 1;\n```');
    cleanup = rendered.cleanup;
    await tick();
    expect(rendered.container.querySelector("h1")?.textContent).toBe("Title");
    expect(rendered.container.querySelector("strong")?.textContent).toBe("bold");
    expect(rendered.container.textContent).toContain("const x = 1;");
    expect(rendered.container.textContent).not.toContain("**bold**");
  });
  it("removes unsafe HTML and javascript links", async () => {
    const rendered = renderContent('<script>alert(1)</script> [bad](javascript:alert(1))');
    cleanup = rendered.cleanup;
    await tick();
    expect(rendered.container.querySelector("script")).toBeNull();
    expect(rendered.container.querySelector('a[href^="javascript:"]')).toBeNull();
  });
});
