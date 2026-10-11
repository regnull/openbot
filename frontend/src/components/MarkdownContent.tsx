import DOMPurify from "dompurify";
import { marked } from "marked";

marked.setOptions({ breaks: true, gfm: true });

function pointsOutsideApp(href: string): boolean {
  try {
    return new URL(href, window.location.href).origin !== window.location.origin;
  } catch {
    return false;
  }
}

// A link in a message that points outside the app opens in a new tab rather than navigating the
// thread away. The desktop app routes new-tab requests to the system browser (electron/main.cjs).
// The hook runs after sanitizing, so DOMPurify has already dropped unsafe hrefs such as javascript:.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  const href = node.tagName === "A" ? node.getAttribute("href") : null;
  if (!href || !pointsOutsideApp(href)) return;
  node.setAttribute("target", "_blank");
  node.setAttribute("rel", "noopener noreferrer");
});

export default function MarkdownContent({ content }: { content: string }) {
  const html = DOMPurify.sanitize(marked.parse(content) as string, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ["style", "script", "iframe", "object", "embed", "form"],
    FORBID_ATTR: ["style", "onerror", "onclick", "onload"],
  });
  return <div className="markdown-content text-sm" dangerouslySetInnerHTML={{ __html: html }} />;
}
