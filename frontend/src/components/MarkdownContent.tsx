import DOMPurify from "dompurify";
import { marked } from "marked";

marked.setOptions({ breaks: true, gfm: true });

export default function MarkdownContent({ content }: { content: string }) {
  const html = DOMPurify.sanitize(marked.parse(content) as string, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ["style", "script", "iframe", "object", "embed", "form"],
    FORBID_ATTR: ["style", "onerror", "onclick", "onload"],
  });
  return <div className="markdown-content text-sm" dangerouslySetInnerHTML={{ __html: html }} />;
}
