import * as Popover from "@radix-ui/react-popover";
import clsx from "clsx";
import {
  ArrowUp,
  Brain,
  Check,
  ChevronDown,
  FileText,
  FolderInput,
  Layers,
  Minus,
  Plus,
  SlidersHorizontal,
  Sparkles,
  Square,
  X,
} from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import type { Direction, DirectionPreset } from "../api/types";
import { useI18n } from "../lib/i18n";
import { Button, Dialog, MenuContent, MenuItem, MenuLabel, MenuRoot, MenuTrigger, Switch, TextField, Tooltip } from "./ui";

export interface ComposerOptions {
  reviewPlan: boolean;
  reviewRounds: number;
  pages: number;
  runId: string;
}

export const DIRECTION_ICONS: Record<string, ReactNode> = {
  context_engineering: <Layers />,
  memory_engine: <Brain />,
  self_evolution: <Sparkles />,
};

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  placeholder: string;
  busy?: boolean;
  disabled?: boolean;
  onStop?: () => void;
  autoFocus?: boolean;
  /** New-run controls; omitted on run pages. */
  directions?: DirectionPreset[];
  direction?: Direction;
  onDirection?: (d: Direction) => void;
  notes?: string;
  onNotes?: (n: string) => void;
  resultsDir?: string;
  onResultsDir?: (d: string) => void;
  options?: ComposerOptions;
  onOptions?: (o: ComposerOptions) => void;
  footer?: ReactNode;
}

export function Composer(props: Props) {
  const { t } = useI18n();
  const ref = useRef<HTMLTextAreaElement>(null);
  const [notesOpen, setNotesOpen] = useState(false);
  const [resultsOpen, setResultsOpen] = useState(false);
  const canSend = props.value.trim().length >= 3 && !props.disabled && !props.busy;

  // Auto-grow up to ~12 lines, like a native chat composer.
  useAutoGrow(ref, props.value, 288);

  useEffect(() => {
    if (props.autoFocus) ref.current?.focus();
  }, [props.autoFocus]);

  const newRun = !!props.onDirection;

  return (
    <div className="w-full">
      <div
        className={clsx(
          "relative flex w-full cursor-text flex-col rounded-4xl bg-composer shadow-composer transition-shadow dark:shadow-none",
          "focus-within:shadow-[0_0_0_1px_rgb(var(--line)/0.16),0_6px_22px_rgb(0_0_0/0.06)]",
        )}
        onClick={(e) => {
          if (e.target === e.currentTarget) ref.current?.focus();
        }}
      >
        {(props.notes || props.resultsDir) && (
          <div className="flex flex-wrap gap-2 px-4 pt-3">
            {props.notes && (
              <Chip icon={<FileText />} label={t("composer.notesAttached")} detail={firstLine(props.notes)} onClick={() => setNotesOpen(true)} onRemove={() => props.onNotes?.("")} />
            )}
            {props.resultsDir && (
              <Chip icon={<FolderInput />} label={t("composer.resultsAttached")} detail={props.resultsDir} onClick={() => setResultsOpen(true)} onRemove={() => props.onResultsDir?.("")} />
            )}
          </div>
        )}
        <textarea
          ref={ref}
          rows={1}
          value={props.value}
          disabled={props.disabled}
          placeholder={props.placeholder}
          onChange={(e) => props.onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
              e.preventDefault();
              if (canSend) props.onSubmit();
            }
          }}
          className="max-h-72 min-h-[52px] w-full resize-none bg-transparent px-5 pb-1 pt-[15px] text-[16px] leading-6 text-fg outline-none placeholder:text-faint disabled:opacity-60"
          aria-label={props.placeholder}
        />
        <div className="flex items-center gap-1.5 px-2.5 pb-2.5 pt-1.5">
          {newRun && (
            <>
              <MenuRoot>
                <Tooltip content={t("composer.attach")}>
                  <MenuTrigger asChild>
                    <button className="flex h-9 w-9 items-center justify-center rounded-full text-fg hover:bg-subtle/[0.06]" aria-label={t("composer.attach")}>
                      <Plus className="h-5 w-5" />
                    </button>
                  </MenuTrigger>
                </Tooltip>
                <MenuContent side="top" align="start" className="w-[300px]">
                  <MenuItem icon={<FileText />} onSelect={() => setNotesOpen(true)}>
                    <span className="block">{t("composer.notesAdd")}</span>
                    <span className="block text-xs text-faint">{t("composer.notesHint")}</span>
                  </MenuItem>
                  <MenuItem icon={<FolderInput />} onSelect={() => setResultsOpen(true)}>
                    <span className="block">{t("composer.import")}</span>
                    <span className="block text-xs text-faint">{t("composer.importHint")}</span>
                  </MenuItem>
                </MenuContent>
              </MenuRoot>
              {props.directions && props.direction && (
                <DirectionPicker directions={props.directions} value={props.direction} onChange={props.onDirection!} />
              )}
              {props.options && props.onOptions && <OptionsPopover options={props.options} onChange={props.onOptions} />}
            </>
          )}
          {props.footer}
          <div className="flex-1" />
          {props.onStop && props.busy ? (
            <Tooltip content={t("composer.stop")}>
              <button
                onClick={props.onStop}
                className="flex h-9 w-9 items-center justify-center rounded-full bg-inverse text-on-inverse transition-opacity hover:opacity-80"
                aria-label={t("composer.stop")}
              >
                <Square className="h-3.5 w-3.5 fill-current" />
              </button>
            </Tooltip>
          ) : (
            <Tooltip content={t("composer.send")}>
              <button
                onClick={() => canSend && props.onSubmit()}
                disabled={!canSend}
                className="flex h-9 w-9 items-center justify-center rounded-full bg-inverse text-on-inverse transition-opacity hover:opacity-80 disabled:bg-subtle/15 disabled:text-main disabled:opacity-100 dark:disabled:bg-subtle/20 dark:disabled:text-[#303030]"
                aria-label={t("composer.send")}
              >
                <ArrowUp className="h-5 w-5" strokeWidth={2.2} />
              </button>
            </Tooltip>
          )}
        </div>
      </div>
      {props.onNotes && <NotesDialog open={notesOpen} onOpenChange={setNotesOpen} value={props.notes ?? ""} onSave={props.onNotes} />}
      {props.onResultsDir && (
        <ResultsDialog open={resultsOpen} onOpenChange={setResultsOpen} value={props.resultsDir ?? ""} onSave={props.onResultsDir} />
      )}
    </div>
  );
}

/** Grow a textarea with its content (or its wrapped placeholder), re-measuring whenever its width changes. */
export function useAutoGrow(ref: RefObject<HTMLTextAreaElement>, value: string, max: number) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      el.style.height = "0px";
      el.style.height = `${Math.min(el.scrollHeight, max)}px`;
    };
    measure();
    const observer = new ResizeObserver(() => measure());
    observer.observe(el.parentElement ?? el);
    return () => observer.disconnect();
  }, [ref, value, max]);
}

function firstLine(text: string) {
  const line = text.trim().split("\n")[0] ?? "";
  return line.length > 40 ? `${line.slice(0, 40)}…` : line;
}

function Chip({ icon, label, detail, onClick, onRemove }: { icon: ReactNode; label: string; detail: string; onClick: () => void; onRemove: () => void }) {
  const { t } = useI18n();
  return (
    <span className="group flex max-w-[280px] items-center gap-2 rounded-2xl border border-line/10 bg-main py-1.5 pl-2 pr-1.5 text-left dark:bg-subtle/[0.04]">
      <button onClick={onClick} className="flex min-w-0 items-center gap-2">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-info/90 text-white [&>svg]:h-4 [&>svg]:w-4">{icon}</span>
        <span className="min-w-0">
          <span className="block text-[13px] font-medium leading-4">{label}</span>
          <span className="block truncate text-xs text-faint">{detail}</span>
        </span>
      </button>
      <button onClick={onRemove} className="rounded-full p-1 text-faint hover:bg-subtle/10 hover:text-fg" aria-label={t("composer.remove")}>
        <X className="h-3.5 w-3.5" />
      </button>
    </span>
  );
}

function DirectionPicker({ directions, value, onChange }: { directions: DirectionPreset[]; value: Direction; onChange: (d: Direction) => void }) {
  const { t } = useI18n();
  const current = directions.find((d) => d.name === value);
  return (
    <MenuRoot>
      <MenuTrigger asChild>
        <button className="flex h-9 items-center gap-1.5 rounded-full border border-line/10 px-3 text-[13px] font-medium text-fg hover:bg-subtle/[0.05] data-[state=open]:bg-subtle/[0.05] [&_svg]:h-4 [&_svg]:w-4">
          {DIRECTION_ICONS[value]}
          <span className="hidden max-w-[180px] truncate sm:inline">{current?.title ?? value}</span>
          <ChevronDown className="text-faint" />
        </button>
      </MenuTrigger>
      <MenuContent side="top" align="start" className="w-[340px]">
        <MenuLabel>{t("composer.direction")}</MenuLabel>
        {directions.map((d) => (
          <MenuItem key={d.name} icon={DIRECTION_ICONS[d.name]} onSelect={() => onChange(d.name)}>
            <span className="flex items-start justify-between gap-3">
              <span>
                <span className="block font-medium">{d.title}</span>
                <span className="line-clamp-2 block text-xs leading-[1.45] text-faint">{d.summary}</span>
              </span>
              {d.name === value && <Check className="mt-0.5 h-4 w-4 shrink-0" />}
            </span>
          </MenuItem>
        ))}
      </MenuContent>
    </MenuRoot>
  );
}

function Stepper({ value, min, max, onChange }: { value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <div className="flex items-center rounded-full border border-line/15">
      <button className="flex h-8 w-8 items-center justify-center text-muted hover:text-fg disabled:opacity-30" disabled={value <= min} onClick={() => onChange(value - 1)} aria-label="Decrease">
        <Minus className="h-3.5 w-3.5" />
      </button>
      <span className="w-6 text-center text-sm tabular-nums">{value}</span>
      <button className="flex h-8 w-8 items-center justify-center text-muted hover:text-fg disabled:opacity-30" disabled={value >= max} onClick={() => onChange(value + 1)} aria-label="Increase">
        <Plus className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function OptionsPopover({ options, onChange }: { options: ComposerOptions; onChange: (o: ComposerOptions) => void }) {
  const { t } = useI18n();
  const set = (patch: Partial<ComposerOptions>) => onChange({ ...options, ...patch });
  return (
    <Popover.Root>
      <Tooltip content={t("composer.options")}>
        <Popover.Trigger asChild>
          <button className="flex h-9 items-center gap-1.5 rounded-full border border-line/10 px-3 text-[13px] font-medium text-fg hover:bg-subtle/[0.05] data-[state=open]:bg-subtle/[0.05]" aria-label={t("composer.options")}>
            <SlidersHorizontal className="h-4 w-4" />
            {options.reviewPlan && <span className="hidden sm:inline">{t("composer.planReviewShort")}</span>}
          </button>
        </Popover.Trigger>
      </Tooltip>
      <Popover.Portal>
        <Popover.Content side="top" align="start" sideOffset={8} collisionPadding={12} className="z-[80] w-[340px] animate-pop-in rounded-2xl bg-elevated p-4 text-sm shadow-menu outline-none">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="font-medium">{t("composer.reviewPlan")}</div>
              <div className="mt-0.5 text-xs leading-5 text-faint">{t("composer.reviewPlanHint")}</div>
            </div>
            <Switch checked={options.reviewPlan} onChange={(v) => set({ reviewPlan: v })} label={t("composer.reviewPlan")} />
          </div>
          <div className="my-3 h-px bg-line/[0.08]" />
          <div className="flex items-center justify-between">
            <span>{t("composer.reviewRounds")}</span>
            <Stepper value={options.reviewRounds} min={0} max={10} onChange={(v) => set({ reviewRounds: v })} />
          </div>
          <div className="mt-2.5 flex items-center justify-between">
            <span>{t("composer.pages")}</span>
            <Stepper value={options.pages} min={1} max={9} onChange={(v) => set({ pages: v })} />
          </div>
          <div className="my-3 h-px bg-line/[0.08]" />
          <label className="block">
            <span className="mb-1.5 block">{t("composer.runId")}</span>
            <TextField
              value={options.runId}
              onChange={(e) => set({ runId: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-").slice(0, 64) })}
              placeholder="mem-study-1"
              className="h-9"
              spellCheck={false}
            />
          </label>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function NotesDialog({ open, onOpenChange, value, onSave }: { open: boolean; onOpenChange: (v: boolean) => void; value: string; onSave: (v: string) => void }) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(value);
  useEffect(() => {
    if (open) setDraft(value);
  }, [open, value]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("composer.notes")} wide>
      <div className="px-6 pb-6">
        <p className="mb-3 text-sm text-muted">{t("composer.notesHint")}</p>
        <textarea
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={12}
          className="w-full resize-y rounded-2xl border border-line/15 bg-transparent p-4 font-mono text-[13px] leading-6 outline-none focus:border-line/30"
          placeholder={"- Design the task so the history exceeds the prompt budget\n- Include at most three competitive baselines"}
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              onSave(draft.trim());
              onOpenChange(false);
            }}
          >
            {t("common.save")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function ResultsDialog({ open, onOpenChange, value, onSave }: { open: boolean; onOpenChange: (v: boolean) => void; value: string; onSave: (v: string) => void }) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(value);
  useEffect(() => {
    if (open) setDraft(value);
  }, [open, value]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("composer.import")}>
      <div className="px-6 pb-6">
        <p className="mb-3 text-sm text-muted">{t("composer.importHint")}</p>
        <TextField autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="/path/to/results" spellCheck={false} />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              onSave(draft.trim());
              onOpenChange(false);
            }}
          >
            {t("common.save")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
