import { Check, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { ModelInfo } from "../api/types";
import { useI18n } from "../lib/i18n";
import { IconButton, TextField } from "./ui";

export function ModelSelect({ value, models, onChange, label, disabled, inherit }: {
  value: string;
  models: ModelInfo[];
  onChange: (model: string) => void;
  label: string;
  disabled?: boolean;
  inherit?: string;
}) {
  const { t } = useI18n();
  const [manual, setManual] = useState(false);
  const [draft, setDraft] = useState(value);
  useEffect(() => { setDraft(value); setManual(false); }, [value]);
  const options = value && !models.some((m) => m.id === value) ? [{ id: value }, ...models] : models;
  if (manual) return (
    <div className="flex w-full min-w-0 items-center gap-1 sm:w-[260px]">
      <TextField aria-label={label} value={draft} disabled={disabled} autoFocus
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.nativeEvent.isComposing && draft.trim()) onChange(draft.trim());
          if (e.key === "Escape") setManual(false);
        }} className="h-9 min-w-0" data-testid="model-select-manual" />
      <IconButton label={t("settings.save")} disabled={disabled || !draft.trim()} onClick={() => onChange(draft.trim())}>
        <Check className="h-4 w-4" />
      </IconButton>
      <IconButton label={t("common.cancel")} onClick={() => setManual(false)}><X className="h-4 w-4" /></IconButton>
    </div>
  );
  return (
    <select aria-label={label} value={value} disabled={disabled} data-testid="model-select"
      onChange={(e) => e.target.value === "__manual__" ? setManual(true) : onChange(e.target.value)}
      className="h-9 w-full min-w-0 truncate rounded-lg border border-line/15 bg-elevated px-2 text-sm outline-none focus:border-accent disabled:opacity-50 sm:w-[260px]">
      {inherit !== undefined && <option value="">{t("model.inherit", { model: inherit })}</option>}
      {!value && inherit === undefined && <option value="" disabled>{t("model.choose")}</option>}
      {options.map((model) => <option key={model.id} value={model.id}>{model.id}</option>)}
      <option value="__manual__">{t("model.manual")}</option>
    </select>
  );
}
