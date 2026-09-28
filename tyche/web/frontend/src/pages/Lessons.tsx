import clsx from "clsx";
import { Lightbulb } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Lesson } from "../api/types";
import { Header } from "../components/Header";
import { Badge, EmptyState, Segmented, Skeleton } from "../components/ui";
import { humanize, relativeTime } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { useI18n, type MessageKey } from "../lib/i18n";

type Filter = "all" | "active" | "candidate" | "retired";

export function Lessons() {
  const { t } = useI18n();
  const lessons = useAsync(() => api.lessons(), []);
  const [filter, setFilter] = useState<Filter>("all");
  const all = lessons.data ?? [];
  const list = useMemo(
    () =>
      all
        .filter((l) => filter === "all" || l.status === filter)
        .sort((a, b) => rank(a) - rank(b) || b.helped - a.helped || b.updated_at.localeCompare(a.updated_at)),
    [all, filter],
  );
  const count = (s: Filter) => (s === "all" ? all.length : all.filter((l) => l.status === s).length);

  return (
    <div className="flex h-full flex-col">
      <Header />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[820px] px-4 pb-16 pt-6 md:px-8">
          <h1 className="text-[28px] font-semibold tracking-[-0.01em]">{t("lessons.title")}</h1>
          <p className="mt-1 max-w-[620px] text-[15px] leading-6 text-muted">{t("lessons.subtitle")}</p>
          <div className="mt-5">
            <Segmented<Filter>
              value={filter}
              onChange={setFilter}
              options={(["all", "active", "candidate", "retired"] as Filter[]).map((f) => ({
                value: f,
                label: `${f === "all" ? t("claims.all") : t(`lessons.${f}` as MessageKey)} ${count(f)}`,
              }))}
            />
          </div>
          <ul className="mt-5 space-y-3">
            {lessons.loading && !lessons.data
              ? Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-24 w-full rounded-2xl" />)
              : list.map((l) => <LessonCard key={l.id} lesson={l} />)}
          </ul>
          {lessons.data && !list.length && <EmptyState icon={<Lightbulb />} title={t("lessons.empty")} />}
          {lessons.error && <EmptyState title={t("common.error")} body={lessons.error.message} />}
        </div>
      </div>
    </div>
  );
}

const rank = (l: Lesson) => ({ active: 0, candidate: 1, retired: 2 })[l.status as "active"] ?? 3;

function LessonCard({ lesson }: { lesson: Lesson }) {
  const { t } = useI18n();
  const tone = lesson.status === "active" ? "ok" : lesson.status === "candidate" ? "info" : "neutral";
  return (
    <li className={clsx("rounded-2xl border border-line/10 p-4", lesson.status === "retired" && "opacity-60")}>
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={tone}>{t(`lessons.${lesson.status}` as MessageKey) || lesson.status}</Badge>
        <Badge>{humanize(lesson.category)}</Badge>
        {lesson.sections.map((s) => (
          <span key={s} className="text-xs text-faint">
            {humanize(s)}
          </span>
        ))}
        <code className="ml-auto font-mono text-[11px] text-faint">{lesson.id}</code>
      </div>
      <p className="mt-2.5 text-[14.5px] leading-6">{lesson.guidance}</p>
      <div className="mt-2.5 flex flex-wrap gap-x-3 text-xs text-faint">
        <span>{t("lessons.runs", { n: lesson.runs })}</span>
        <span>{t("lessons.helped", { n: lesson.helped })}</span>
        {lesson.misses > 0 && <span>{t("lessons.misses", { n: lesson.misses })}</span>}
        <span>{relativeTime(lesson.updated_at, t)}</span>
      </div>
    </li>
  );
}
