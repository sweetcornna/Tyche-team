import clsx from "clsx";
import { BookOpen, Download, FileText, ShieldAlert, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { LibraryPaper } from "../api/types";
import { Header } from "../components/Header";
import { EmptyState, Skeleton } from "../components/ui";
import { relativeTime } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { useI18n } from "../lib/i18n";
import { Link } from "../lib/router";
import { useStore } from "../lib/store";

export function Library() {
  const { t } = useI18n();
  const { meta } = useStore();
  const papers = useAsync(() => api.library(), []);
  const [direction, setDirection] = useState<string>("all");
  const list = useMemo(() => (papers.data ?? []).filter((p) => direction === "all" || p.direction === direction), [papers.data, direction]);
  const directions = meta?.directions ?? [];

  return (
    <div className="flex h-full flex-col">
      <Header />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[1080px] px-4 pb-16 pt-6 md:px-8">
          <h1 className="text-[28px] font-semibold tracking-[-0.01em]">{t("library.title")}</h1>
          <p className="mt-1 text-[15px] text-muted">{t("library.subtitle")}</p>
          {directions.length > 0 && (
            <div className="mt-5 flex flex-wrap gap-2">
              {[{ name: "all", title: t("claims.all") }, ...directions].map((d) => (
                <button
                  key={d.name}
                  onClick={() => setDirection(d.name)}
                  className={clsx(
                    "h-8 rounded-full border px-3.5 text-[13px] font-medium transition-colors",
                    direction === d.name ? "border-transparent bg-inverse text-on-inverse" : "border-line/15 text-fg hover:bg-subtle/[0.04]",
                  )}
                >
                  {d.title}
                </button>
              ))}
            </div>
          )}
          <div className="mt-6 grid grid-cols-2 gap-x-5 gap-y-8 sm:grid-cols-3 lg:grid-cols-4">
            {papers.loading && !papers.data
              ? Array.from({ length: 4 }, (_, i) => (
                  <div key={i}>
                    <Skeleton className="aspect-[8.5/11] w-full rounded-2xl" />
                    <Skeleton className="mt-3 h-4 w-4/5" />
                  </div>
                ))
              : list.map((p) => <PaperTile key={p.run_id} paper={p} />)}
          </div>
          {papers.data && !list.length && <EmptyState icon={<BookOpen />} title={t("library.empty")} />}
          {papers.error && <EmptyState title={t("common.error")} body={papers.error.message} />}
        </div>
      </div>
    </div>
  );
}

function PaperTile({ paper }: { paper: LibraryPaper }) {
  const { t } = useI18n();
  const [broken, setBroken] = useState(false);
  return (
    <div className="group">
      <Link
        to={`/r/${encodeURIComponent(paper.run_id)}?panel=paper`}
        className="relative block aspect-[8.5/11] overflow-hidden rounded-2xl border border-line/10 bg-white shadow-card transition-transform group-hover:-translate-y-0.5"
        aria-label={paper.title}
      >
        {!broken ? (
          <img src={paper.thumb_url} alt="" loading="lazy" onError={() => setBroken(true)} className="h-full w-full object-cover object-top" />
        ) : (
          <div className="flex h-full items-center justify-center text-[#999]">
            <FileText className="h-10 w-10" />
          </div>
        )}
        <div className="absolute left-2 top-2 flex flex-wrap gap-1">
          {paper.unverified && (
            <span className="inline-flex h-[22px] items-center gap-1 rounded-full bg-[#d13438] px-2 text-[11px] font-semibold text-white shadow-sm">
              <ShieldAlert className="h-3 w-3" /> UNVERIFIED
            </span>
          )}
          {paper.synthetic && (
            <span className="inline-flex h-[22px] items-center rounded-full bg-[#8a5a00] px-2 text-[11px] font-semibold text-white shadow-sm">{t("library.fixture")}</span>
          )}
        </div>
        <a
          href={paper.pdf_url}
          download={`${paper.run_id}.pdf`}
          onClick={(e) => e.stopPropagation()}
          className="absolute bottom-2 right-2 flex h-8 w-8 items-center justify-center rounded-full bg-[#0d0d0d]/80 text-white opacity-0 transition-opacity hover:bg-[#0d0d0d] group-hover:opacity-100"
          aria-label="PDF"
        >
          <Download className="h-4 w-4" />
        </a>
      </Link>
      <Link to={`/r/${encodeURIComponent(paper.run_id)}`} className="mt-3 line-clamp-2 block text-[14px] font-medium leading-snug hover:underline">
        {paper.title}
      </Link>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-faint">
        <span>{relativeTime(paper.updated_at, t)}</span>
        {paper.main_pages != null && <span>· {t("library.pages", { n: paper.main_pages })}</span>}
        {paper.composite != null && <span className="tabular-nums">· {paper.composite.toFixed(2)}</span>}
        {paper.gates_passed && <ShieldCheck className="h-3.5 w-3.5 text-ok" aria-label={t("review.gatesPassed")} />}
      </div>
    </div>
  );
}
