import clsx from "clsx";
import { ChevronDown, ExternalLink, Quote, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../../api/client";
import type { Reference } from "../../api/types";
import { useAsync } from "../../lib/hooks";
import { useI18n } from "../../lib/i18n";
import { humanize, safeUrl } from "../../lib/format";
import { Badge, Segmented } from "../ui";
import { PanelLoading, PanelMessage, type TabProps } from "./RightPanel";

type Filter = "all" | "cited" | "carded";

export default function SourcesTab({ runId, detail }: TabProps) {
  const { t } = useI18n();
  const refs = useAsync(() => api.references(runId), [runId, detail.stages.find((s) => s.name === "survey")?.status]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [open, setOpen] = useState<string | null>(null);

  const papers = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (refs.data?.papers ?? [])
      .filter((p) => filter === "all" || (filter === "cited" ? p.cited : p.cards.length > 0))
      .filter((p) => !q || `${p.title} ${p.authors.join(" ")} ${p.venue} ${p.key}`.toLowerCase().includes(q))
      .sort((a, b) => Number(b.cited) - Number(a.cited) || b.relevance - a.relevance);
  }, [refs.data, query, filter]);

  if (refs.loading && !refs.data) return <PanelLoading />;
  if (!refs.data?.papers.length) return <PanelMessage>{t("panel.unavailable")}</PanelMessage>;
  const all = refs.data.papers;

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 space-y-3 px-5 pb-3 pt-4">
        <div className="flex h-10 items-center gap-2 rounded-xl border border-line/15 px-3 focus-within:border-line/30">
          <Search className="h-4 w-4 text-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("sources.search")}
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-faint"
          />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Segmented<Filter>
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: `${t("claims.all")} ${all.length}` },
              { value: "cited", label: `${t("sources.cited")} ${all.filter((p) => p.cited).length}` },
              { value: "carded", label: `${t("sources.carded")} ${all.filter((p) => p.cards.length).length}` },
            ]}
          />
          <span className="text-xs text-faint">{t("sources.verifiedNote")}</span>
        </div>
      </div>
      <ul className="min-h-0 flex-1 divide-y divide-line/[0.06] overflow-y-auto border-t border-line/[0.06]">
        {papers.map((p) => (
          <SourceRow key={p.key} paper={p} open={open === p.key} onToggle={() => setOpen(open === p.key ? null : p.key)} />
        ))}
        {!papers.length && <li className="px-5 py-10 text-center text-sm text-faint">{t("search.empty")}</li>}
      </ul>
    </div>
  );
}

const SOURCE_COLORS: Record<string, string> = { arxiv: "bg-[#b31b1b]", semantic_scholar: "bg-[#1857b6]", openalex: "bg-[#d97706]", crossref: "bg-[#3a7d44]" };

function SourceRow({ paper, open, onToggle }: { paper: Reference; open: boolean; onToggle: () => void }) {
  const { t } = useI18n();
  const authors = paper.authors.length > 3 ? `${paper.authors.slice(0, 3).join(", ")} et al.` : paper.authors.join(", ");
  return (
    <li className="px-5 py-3.5">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <a href={safeUrl(paper.url)} target="_blank" rel="noopener noreferrer" className="group inline text-[14px] font-medium leading-snug hover:underline">
            {paper.title}
            <ExternalLink className="ml-1 inline h-3 w-3 text-faint opacity-0 group-hover:opacity-100" />
          </a>
          <div className="mt-1 truncate text-[12.5px] text-muted">
            {authors}
            {paper.year ? ` · ${paper.year}` : ""}
            {paper.venue ? ` · ${paper.venue}` : ""}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <code className="rounded bg-subtle/[0.06] px-1.5 py-0.5 font-mono text-[11px] text-muted">{paper.key}</code>
            {paper.cited && <Badge tone="info">{t("sources.cited")}</Badge>}
            {paper.role && <Badge>{humanize(paper.role)}</Badge>}
            {paper.citation_count != null && <span className="text-[11.5px] text-faint">{t("sources.citations", { n: paper.citation_count })}</span>}
            <span className="flex gap-1">
              {paper.sources.map((s) => (
                <span key={s} title={s} className={clsx("h-2 w-2 rounded-full", SOURCE_COLORS[s] ?? "bg-faint")} />
              ))}
            </span>
          </div>
        </div>
        {(paper.abstract || paper.cards.length > 0) && (
          <button onClick={onToggle} className="mt-0.5 flex h-7 shrink-0 items-center gap-1 rounded-lg px-2 text-xs text-muted hover:bg-subtle/[0.05] hover:text-fg" aria-expanded={open}>
            {paper.cards.length > 0 && (
              <span className="inline-flex items-center gap-0.5">
                <Quote className="h-3 w-3" />
                {paper.cards.length}
              </span>
            )}
            <ChevronDown className={clsx("h-4 w-4 transition-transform", open && "rotate-180")} />
          </button>
        )}
      </div>
      {open && (
        <div className="mt-3 space-y-3 animate-fade-in">
          {paper.cards.map((c, i) => (
            <figure key={i} className="rounded-xl border-l-2 border-accent/50 bg-subtle/[0.03] py-2 pl-3 pr-2">
              <figcaption className="text-[13px] font-medium">{c.claim}</figcaption>
              <blockquote className="mt-1 text-[12.5px] italic leading-5 text-muted">“{c.quote}”</blockquote>
            </figure>
          ))}
          {paper.abstract && <p className="text-[12.5px] leading-5 text-muted">{paper.abstract}</p>}
          {(paper.doi || paper.arxiv_id) && (
            <div className="flex gap-3 text-[11.5px] text-faint">
              {paper.doi && <span>DOI {paper.doi}</span>}
              {paper.arxiv_id && <span>arXiv {paper.arxiv_id}</span>}
            </div>
          )}
        </div>
      )}
    </li>
  );
}
