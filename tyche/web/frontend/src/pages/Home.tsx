import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Direction } from "../api/types";
import { Composer, DIRECTION_ICONS, type ComposerOptions } from "../components/Composer";
import { Header, ModelPicker } from "../components/Header";
import { useI18n } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import { useRouter } from "../lib/router";
import { useStore } from "../lib/store";
import { useToast } from "../lib/toast";

const EXAMPLES: Record<Direction, { zh: string; en: string }> = {
  memory_engine: {
    zh: "带更正链的智能体记忆，能否在固定提示预算下减少过期事实回答？",
    en: "Do provenance-tagged correction chains reduce stale-fact answers under a fixed prompt budget?",
  },
  context_engineering: {
    zh: "按来源优先级打包工具输出，能否比截断和滚动摘要更好地保留关键证据？",
    en: "Does provenance-aware packing of tool outputs keep decisive evidence better than truncation and rolling summaries?",
  },
  self_evolution: {
    zh: "自演进智能体提炼的经验，是否必须先在留出任务上证明有效，才能进入提示词？",
    en: "Must a self-evolving agent's lesson show a verified gain on held-out tasks before it enters the prompt?",
  },
};

export function Home() {
  const { t, lang } = useI18n();
  const { meta, runs, refreshRuns } = useStore();
  const { model, effort } = usePrefs();
  const { navigate } = useRouter();
  const toast = useToast();
  const [topic, setTopic] = useState("");
  const [direction, setDirection] = useState<Direction>("memory_engine");
  const [notes, setNotes] = useState("");
  const [resultsDir, setResultsDir] = useState("");
  const [options, setOptions] = useState<ComposerOptions>({ reviewPlan: true, reviewRounds: 3, pages: 5, runId: "" });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (meta) setOptions((o) => ({ ...o, reviewRounds: meta.defaults.review_max_rounds, pages: meta.defaults.max_main_pages }));
  }, [meta]);

  const submit = async () => {
    setSubmitting(true);
    try {
      const res = await api.create({
        topic: topic.trim(),
        direction,
        notes,
        run_id: options.runId.trim() || null,
        stop_after: options.reviewPlan ? "plan" : null,
        engine: resultsDir ? "imported" : null,
        results_dir: resultsDir || null,
        model: {
          model_name: model,
          reasoning_effort: effort,
          max_tokens: effort && ["high", "xhigh", "max"].includes(effort) ? 65536 : null,
          timeout: effort && ["xhigh", "max"].includes(effort) ? 1800 : null,
          reviewer_model: null,
        },
        settings: {
          review_max_rounds: meta && options.reviewRounds === meta.defaults.review_max_rounds ? null : options.reviewRounds,
          max_main_pages: meta && options.pages === meta.defaults.max_main_pages ? null : options.pages,
        },
      });
      toast("success", t("toast.started"), res.run_id);
      await refreshRuns();
      navigate(`/r/${encodeURIComponent(res.run_id)}`);
    } catch (e) {
      toast("error", t("common.error"), (e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const running = runs.filter((r) => r.status === "running").length;

  return (
    <div className="flex h-full flex-col">
      <Header left={<ModelPicker />} />
      <div className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-4">
        <div className="flex w-full max-w-[768px] flex-1 flex-col justify-center pb-[12vh] pt-8">
          <h1 className="mb-7 text-center text-[28px] font-medium leading-tight tracking-[-0.01em] text-fg sm:text-[30px]">
            {running > 0 ? t("home.greetingRunning") : t("home.greeting")}
          </h1>
          <Composer
            autoFocus
            value={topic}
            onChange={setTopic}
            onSubmit={submit}
            busy={submitting}
            placeholder={t("home.placeholder")}
            directions={meta?.directions}
            direction={direction}
            onDirection={setDirection}
            notes={notes}
            onNotes={setNotes}
            resultsDir={resultsDir}
            onResultsDir={setResultsDir}
            options={options}
            onOptions={setOptions}
          />
          <div className="mt-6 grid gap-2 sm:grid-cols-3">
            {(meta?.directions ?? []).map((d) => (
              <button
                key={d.name}
                onClick={() => {
                  setDirection(d.name);
                  setTopic(EXAMPLES[d.name]?.[lang] ?? "");
                }}
                className="group flex flex-col gap-2 rounded-2xl border border-line/10 p-3.5 text-left transition-colors hover:bg-subtle/[0.03]"
              >
                <span className="flex items-center gap-2 text-[13px] font-medium text-fg [&>svg]:h-4 [&>svg]:w-4 [&>svg]:text-muted">
                  {DIRECTION_ICONS[d.name]}
                  {d.title}
                </span>
                <span className="line-clamp-3 text-[13px] leading-5 text-muted">{EXAMPLES[d.name]?.[lang]}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
      <p className="shrink-0 px-4 pb-3 pt-1 text-center text-xs text-faint">{t("home.disclaimer")}</p>
    </div>
  );
}
