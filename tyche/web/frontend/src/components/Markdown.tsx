import clsx from "clsx";
import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import json from "highlight.js/lib/languages/json";
import latex from "highlight.js/lib/languages/latex";
import markdown from "highlight.js/lib/languages/markdown";
import python from "highlight.js/lib/languages/python";
import yaml from "highlight.js/lib/languages/yaml";
import plaintext from "highlight.js/lib/languages/plaintext";
import { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

hljs.registerLanguage("python", python);
hljs.registerLanguage("json", json);
hljs.registerLanguage("bash", bash);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("latex", latex);
hljs.registerLanguage("markdown", markdown);
hljs.registerLanguage("plaintext", plaintext);

const EXT_LANG: Record<string, string> = {
  py: "python",
  json: "json",
  sh: "bash",
  bash: "bash",
  yaml: "yaml",
  yml: "yaml",
  tex: "latex",
  bib: "latex",
  sty: "latex",
  md: "markdown",
  txt: "plaintext",
  toml: "yaml",
  cfg: "plaintext",
  ini: "plaintext",
};

export function languageForPath(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  return EXT_LANG[ext] ?? "plaintext";
}

export function highlight(code: string, language: string): string {
  try {
    if (hljs.getLanguage(language)) return hljs.highlight(code, { language, ignoreIllegals: true }).value;
  } catch {
    /* fall through */
  }
  return hljs.highlight(code, { language: "plaintext" }).value;
}

/** Syntax-highlighted code with line numbers. hljs escapes its input, so the HTML is safe. */
export const CodeView = memo(function CodeView({ code, language, className }: { code: string; language: string; className?: string }) {
  const lines = useMemo(() => highlight(code, language).split("\n"), [code, language]);
  return (
    <div className={clsx("overflow-auto font-mono text-[12.5px] leading-[1.65]", className)}>
      <table className="w-full border-collapse">
        <tbody>
          {lines.map((html, i) => (
            <tr key={i} className="align-top">
              <td className="select-none pl-4 pr-4 text-right text-faint/70 [font-variant-numeric:tabular-nums]">{i + 1}</td>
              <td className="whitespace-pre pr-6">
                <span dangerouslySetInnerHTML={{ __html: html || " " }} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
});

/**
 * Markdown from run artifacts. Artifacts contain model-written text, so raw HTML stays disabled
 * (react-markdown's default) and links open in a new tab without referrer.
 */
/** Split a leading YAML front-matter block (`---` … `---`) from the Markdown body. */
export function splitFrontMatter(text: string): { meta: string | null; body: string } {
  const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(text);
  return m ? { meta: m[1], body: text.slice(m[0].length) } : { meta: null, body: text };
}

export const Markdown = memo(function Markdown({ text, compact, className }: { text: string; compact?: boolean; className?: string }) {
  const { meta, body } = splitFrontMatter(text);
  return (
    <div className={clsx("prose-chat", compact && "compact", className)}>
      {meta && (
        <details className="not-prose mb-4 rounded-xl border border-line/10 px-3 py-2 text-xs text-muted">
          <summary className="cursor-pointer select-none font-medium">Metadata</summary>
          <pre className="mt-2 overflow-x-auto whitespace-pre font-mono text-[11.5px] leading-5">{meta}</pre>
        </details>
      )}
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
          code: ({ className: cls, children }) => {
            const lang = /language-(\w+)/.exec(cls ?? "")?.[1];
            const source = String(children ?? "");
            if (!lang && !source.includes("\n")) return <code>{children}</code>;
            return <code className="hljs" dangerouslySetInnerHTML={{ __html: highlight(source.replace(/\n$/, ""), lang ?? "plaintext") }} />;
          },
          table: ({ children }) => (
            <div className="overflow-x-auto">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {body}
      </ReactMarkdown>
    </div>
  );
});
