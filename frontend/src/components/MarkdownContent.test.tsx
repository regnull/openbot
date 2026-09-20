// @vitest-environment jsdom
/// <reference types="node" />
import { afterEach, describe, expect, it } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
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

  it("themes inline code through the shared palette tokens, in both theme mechanisms", () => {
    const css = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");
    // Colors are semantic tokens flipped per theme. The toggle pins a theme with
    // `<html data-theme>`; without it the OS preference applies. Both must define
    // the same tokens, and no rule may hard-code a per-theme color or use a `.dark`
    // class selector that nothing sets.
    expect(css).not.toMatch(/\.dark\s/);
    const codeRule = css.match(/\.markdown-content code\s*\{([^}]*)\}/);
    expect(codeRule, "expected a .markdown-content code rule").not.toBeNull();
    expect(codeRule![1]).toMatch(/background:\s*var\(--sunken\)/);
    expect(codeRule![1]).toMatch(/color:\s*var\(--fg\)/);
    // Code blocks keep their own background: inline-code styling must not leak into them.
    expect(css).toMatch(/\.markdown-content pre code\s*\{[^}]*background:\s*transparent/);
    expect(css).toMatch(/\.markdown-content blockquote\s*\{[^}]*var\(--accent\)/);
    const pinned = css.match(/:root\[data-theme="dark"\]\s*\{([^}]*)\}/);
    const system = css.match(/@media \(prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme="light"\]\)\s*\{([^}]*)\}/);
    expect(pinned, "expected a pinned dark theme block").not.toBeNull();
    expect(system, "expected an OS-preference dark theme block").not.toBeNull();
    for (const token of ["--canvas", "--surface", "--sunken", "--fg", "--muted", "--accent"]) {
      expect(pinned![1]).toContain(`${token}:`);
      expect(system![1]).toContain(`${token}:`);
    }
    // The two dark definitions must agree, or the toggle and the OS preference would drift apart.
    expect(pinned![1].replace(/\s+/g, "")).toBe(system![1].replace(/\s+/g, ""));
  });
});
