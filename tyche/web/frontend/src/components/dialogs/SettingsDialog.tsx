import * as DialogPrimitive from "@radix-ui/react-dialog";
import clsx from "clsx";
import { BookMarked, Check, Cpu, FolderCog, Info, Settings2, X, XCircle } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { Doctor } from "../../api/types";
import { useI18n, type MessageKey } from "../../lib/i18n";
import { usePrefs, type Theme } from "../../lib/prefs";
import { useStore, type SettingsTab } from "../../lib/store";
import { useToast } from "../../lib/toast";
import { LogoMark } from "../Logo";
import { Badge, Button, IconButton, Segmented, Spinner, TextField } from "../ui";

const TABS: { id: SettingsTab; icon: ReactNode; label: MessageKey }[] = [
  { id: "general", icon: <Settings2 />, label: "settings.general" },
  { id: "model", icon: <Cpu />, label: "settings.model" },
  { id: "literature", icon: <BookMarked />, label: "settings.literature" },
  { id: "workspace", icon: <FolderCog />, label: "settings.workspace" },
  { id: "about", icon: <Info />, label: "settings.about" },
];

export function SettingsDialog() {
  const { t } = useI18n();
  const { settingsOpen, closeSettings, settingsTab, openSettings } = useStore();
  return (
    <DialogPrimitive.Root open={settingsOpen} onOpenChange={(v) => !v && closeSettings()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[70] animate-fade-in bg-black/40 dark:bg-black/60" />
        <DialogPrimitive.Content className="fixed left-1/2 top-1/2 z-[71] flex h-[min(600px,calc(100vh-40px))] w-[calc(100vw-24px)] max-w-[720px] -translate-x-1/2 -translate-y-1/2 animate-pop-in flex-col overflow-hidden rounded-3xl bg-elevated shadow-menu outline-none md:flex-row">
          <DialogPrimitive.Description className="sr-only">{t("settings.title")}</DialogPrimitive.Description>
          <div className="flex shrink-0 flex-col border-line/[0.08] md:w-[196px] md:border-r md:p-2">
            <div className="flex items-center justify-between px-4 pb-2 pt-4 md:px-2 md:pb-3 md:pt-2">
              <DialogPrimitive.Close asChild>
                <IconButton label={t("common.close")} tooltip={false} size="sm" className="-ml-1">
                  <X className="h-5 w-5" />
                </IconButton>
              </DialogPrimitive.Close>
              <DialogPrimitive.Title className="text-base font-semibold md:sr-only">{t("settings.title")}</DialogPrimitive.Title>
              <span className="w-8 md:hidden" />
            </div>
            <nav className="flex gap-1 overflow-x-auto px-3 pb-2 md:flex-col md:overflow-visible md:px-0 md:pb-0">
              {TABS.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => openSettings(tab.id)}
                  className={clsx(
                    "flex h-9 shrink-0 items-center gap-2.5 rounded-lg px-2.5 text-sm transition-colors [&>svg]:h-[18px] [&>svg]:w-[18px]",
                    settingsTab === tab.id ? "bg-subtle/[0.07] text-fg" : "text-muted hover:bg-subtle/[0.04] hover:text-fg",
                  )}
                >
                  {tab.icon}
                  {t(tab.label)}
                </button>
              ))}
            </nav>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6 pt-2 md:pt-5">
            <h2 className="mb-2 hidden text-lg font-semibold md:block">{t(TABS.find((x) => x.id === settingsTab)!.label)}</h2>
            {settingsTab === "general" && <GeneralTab />}
            {settingsTab === "model" && <ModelTab />}
            {settingsTab === "literature" && <LiteratureTab />}
            {settingsTab === "workspace" && <WorkspaceTab />}
            {settingsTab === "about" && <AboutTab />}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function Row({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2 border-b border-line/[0.08] py-3.5 last:border-none sm:flex-row sm:items-center sm:justify-between sm:gap-6">
      <div className="min-w-0">
        <div className="text-sm">{label}</div>
        {hint && <div className="mt-0.5 text-xs leading-5 text-faint">{hint}</div>}
      </div>
      <div className="shrink-0 sm:max-w-[60%]">{children}</div>
    </div>
  );
}

function GeneralTab() {
  const { t, lang, setLang } = useI18n();
  const { theme, setTheme } = usePrefs();
  return (
    <div>
      <Row label={t("settings.theme")}>
        <Segmented<Theme>
          value={theme}
          onChange={setTheme}
          options={[
            { value: "system", label: t("settings.theme.system") },
            { value: "light", label: t("settings.theme.light") },
            { value: "dark", label: t("settings.theme.dark") },
          ]}
        />
      </Row>
      <Row label={t("settings.language")}>
        <Segmented
          value={lang}
          onChange={setLang}
          options={[
            { value: "zh", label: "中文" },
            { value: "en", label: "English" },
          ]}
        />
      </Row>
    </div>
  );
}

/** Edits a subset of .env; unchanged fields are not sent. Secrets are write-only. */
function useEnvForm(valueKeys: string[], secretKeys: string[]) {
  const { meta, setMeta } = useStore();
  const toast = useToast();
  const { t } = useI18n();
  const initial = useMemo(() => Object.fromEntries(valueKeys.map((k) => [k, meta?.env[k] ?? ""])), [meta, valueKeys]);
  const [values, setValues] = useState<Record<string, string>>(initial);
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  useEffect(() => setValues(initial), [initial]);

  const changedValues = Object.fromEntries(Object.entries(values).filter(([k, v]) => v !== initial[k]));
  const changedSecrets = Object.fromEntries(Object.entries(secrets).filter(([k, v]) => secretKeys.includes(k) && v !== ""));
  const dirty = Object.keys(changedValues).length + Object.keys(changedSecrets).length > 0;

  const save = async () => {
    setSaving(true);
    try {
      const next = await api.saveEnv(changedValues, changedSecrets);
      setMeta(next);
      setSecrets({});
      toast("success", t("settings.saved"));
    } catch (e) {
      toast("error", t("common.error"), (e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  return { meta, values, setValues, secrets, setSecrets, dirty, saving, save };
}

function KeyField({ name, form, label }: { name: string; form: ReturnType<typeof useEnvForm>; label: string }) {
  const { t } = useI18n();
  const set = form.meta?.keys[name];
  return (
    <Row
      label={label}
      hint={t("settings.keyHint", { file: form.meta?.env_file ?? ".env" })}
    >
      <div className="flex w-full items-center gap-2 sm:w-[280px]">
        <Badge tone={set ? "ok" : "warn"}>{set ? t("settings.keySet") : t("settings.keyMissing")}</Badge>
        <TextField
          type="password"
          autoComplete="off"
          spellCheck={false}
          placeholder={t("settings.keyReplace")}
          value={form.secrets[name] ?? ""}
          onChange={(e) => form.setSecrets((s) => ({ ...s, [name]: e.target.value }))}
          className="h-9"
        />
      </div>
    </Row>
  );
}

function ValueField({ name, form, label, placeholder }: { name: string; form: ReturnType<typeof useEnvForm>; label: string; placeholder?: string }) {
  return (
    <Row label={label}>
      <TextField
        value={form.values[name] ?? ""}
        placeholder={placeholder}
        spellCheck={false}
        onChange={(e) => form.setValues((v) => ({ ...v, [name]: e.target.value }))}
        className="h-9 sm:w-[280px]"
      />
    </Row>
  );
}

const MODEL_VALUES = ["API_BASE", "MODEL_NAME", "MODEL_PROVIDER", "MODEL_CONTEXT_WINDOW", "TYCHE_REVIEW_MODEL_NAME", "TYCHE_EXPERIMENT_MODEL_NAME"];
const MODEL_SECRETS = ["API_KEY"];

function ModelTab() {
  const { t } = useI18n();
  const form = useEnvForm(MODEL_VALUES, MODEL_SECRETS);
  return (
    <div>
      <ValueField name="API_BASE" form={form} label={t("settings.apiBase")} placeholder="https://api.example.com/v1" />
      <ValueField name="MODEL_NAME" form={form} label={t("settings.modelName")} />
      <ValueField name="MODEL_PROVIDER" form={form} label={t("settings.provider")} placeholder="OpenAI" />
      <ValueField name="MODEL_CONTEXT_WINDOW" form={form} label={t("settings.contextWindow")} placeholder="131072" />
      <KeyField name="API_KEY" form={form} label={t("settings.apiKey")} />
      <ValueField name="TYCHE_REVIEW_MODEL_NAME" form={form} label={t("settings.reviewModel")} />
      <ValueField name="TYCHE_EXPERIMENT_MODEL_NAME" form={form} label={t("settings.experimentModel")} />
      <div className="flex justify-end pt-4">
        <Button variant="primary" disabled={!form.dirty} loading={form.saving} onClick={form.save}>
          {t("settings.save")}
        </Button>
      </div>
    </div>
  );
}

function LiteratureTab() {
  const { t } = useI18n();
  const form = useEnvForm(["TYCHE_CONTACT_EMAIL"], ["S2_API_KEY", "OPENALEX_API_KEY"]);
  return (
    <div>
      <p className="mb-2 text-[13px] leading-6 text-muted">{t("settings.literatureHint")}</p>
      <KeyField name="S2_API_KEY" form={form} label={t("settings.s2")} />
      <KeyField name="OPENALEX_API_KEY" form={form} label={t("settings.openalex")} />
      <ValueField name="TYCHE_CONTACT_EMAIL" form={form} label={t("settings.contact")} placeholder="name@example.org" />
      <div className="flex justify-end pt-4">
        <Button variant="primary" disabled={!form.dirty} loading={form.saving} onClick={form.save}>
          {t("settings.save")}
        </Button>
      </div>
    </div>
  );
}

function WorkspaceTab() {
  const { t } = useI18n();
  const { meta } = useStore();
  const [doctor, setDoctor] = useState<Doctor>();
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string>();
  const run = async () => {
    setChecking(true);
    setError(undefined);
    try {
      setDoctor(await api.doctor());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setChecking(false);
    }
  };
  return (
    <div>
      <Row label={t("settings.workspacePath")}>
        <code className="block max-w-full truncate rounded-md bg-subtle/[0.05] px-2 py-1 text-xs" title={meta?.workspace}>
          {meta?.workspace}
        </code>
      </Row>
      <Row label={t("settings.envFile")}>
        <code className="block max-w-full truncate rounded-md bg-subtle/[0.05] px-2 py-1 text-xs">{meta?.env_file ?? "—"}</code>
      </Row>
      <Row label={t("settings.version")}>
        <span className="text-sm text-muted">tyche {meta?.version}</span>
      </Row>
      <div className="mt-5 flex items-center justify-between">
        <h3 className="text-sm font-semibold">{t("settings.diagnostics")}</h3>
        <Button size="sm" variant="outline" loading={checking} onClick={run}>
          {checking ? t("settings.checking") : t("settings.runChecks")}
        </Button>
      </div>
      {error && <p className="mt-3 text-sm text-bad">{error}</p>}
      {doctor && (
        <div className="mt-3 space-y-4 text-[13px]">
          <CheckList
            title={t("settings.tools")}
            items={[
              ...Object.entries(doctor.tools).map(([k, v]) => ({ label: k, ok: !!v, detail: v ?? "missing" })),
              { label: "openjiuwen", ok: doctor.openjiuwen, detail: doctor.openjiuwen ? "importable" : "missing" },
              { label: "reference docs", ok: doctor.reference_docs, detail: doctor.reference_docs ? "present" : "missing" },
            ]}
          />
          <CheckList
            title={t("settings.sources")}
            items={Object.entries(doctor.sources).map(([k, v]) => ({ label: k, ok: v.startsWith("reachable"), detail: v }))}
          />
          <CheckList
            title={t("settings.model")}
            items={Object.entries(doctor.roles).map(([role, r]) => ({
              label: role,
              ok: true,
              detail: `${r.model_name} · ${r.cache_profile}`,
            }))}
          />
        </div>
      )}
      {!doctor && !checking && (
        <p className="mt-3 text-[13px] text-faint">
          {meta && Object.entries(meta.keys).map(([k, v]) => `${k}: ${v ? "✓" : "—"}`).join("   ")}
        </p>
      )}
    </div>
  );
}

function CheckList({ title, items }: { title: string; items: { label: string; ok: boolean; detail: string }[] }) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-medium text-faint">{title}</div>
      <ul className="rounded-xl border border-line/[0.08]">
        {items.map((it) => (
          <li key={it.label} className="flex items-center gap-2.5 border-b border-line/[0.06] px-3 py-2 last:border-none">
            {it.ok ? <Check className="h-4 w-4 shrink-0 text-ok" /> : <XCircle className="h-4 w-4 shrink-0 text-bad" />}
            <span className="w-32 shrink-0 font-medium">{it.label}</span>
            <span className="min-w-0 truncate text-muted" title={it.detail}>
              {it.detail}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AboutTab() {
  const { t } = useI18n();
  const { meta } = useStore();
  return (
    <div className="pt-2">
      <div className="flex items-center gap-3">
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-inverse text-on-inverse">
          <LogoMark className="h-7 w-7" />
        </span>
        <div>
          <div className="text-base font-semibold">Tyche</div>
          <div className="text-xs text-faint">
            {t("app.tagline")} · v{meta?.version}
          </div>
        </div>
      </div>
      <p className="mt-4 text-sm leading-6 text-muted">{t("settings.aboutBody")}</p>
      <div className="mt-4 flex flex-wrap gap-2 text-sm">
        <a className="text-accent hover:underline" href="https://github.com/sweetcornna/Tyche" target="_blank" rel="noopener noreferrer">
          GitHub
        </a>
        <span className="text-faint">·</span>
        <a className="text-accent hover:underline" href="https://github.com/openJiuwen-ai/jiuwenswarm" target="_blank" rel="noopener noreferrer">
          JiuwenSwarm
        </a>
        <span className="text-faint">·</span>
        <a className="text-accent hover:underline" href="https://paperreview.ai" target="_blank" rel="noopener noreferrer">
          Stanford Agentic Reviewer
        </a>
      </div>
      {!meta && <Spinner className="mt-4 h-4 w-4" />}
    </div>
  );
}
