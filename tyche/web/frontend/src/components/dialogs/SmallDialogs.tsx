import { isMac } from "../../lib/hooks";
import { useI18n, type MessageKey } from "../../lib/i18n";
import { useStore } from "../../lib/store";
import { Button, Dialog, Kbd } from "../ui";

export function ConfirmDialog() {
  const { t } = useI18n();
  const { confirmState } = useStore();
  return (
    <Dialog
      open={!!confirmState}
      onOpenChange={(v) => !v && confirmState?.resolve(false)}
      title={confirmState?.title}
      hideClose
    >
      {confirmState?.body && <p className="px-6 text-sm leading-6 text-muted">{confirmState.body}</p>}
      <div className="flex justify-end gap-2 px-6 pb-5 pt-6">
        <Button variant="outline" onClick={() => confirmState?.resolve(false)}>
          {t("common.cancel")}
        </Button>
        <Button
          autoFocus
          variant={confirmState?.destructive ? "danger" : "primary"}
          onClick={() => confirmState?.resolve(true)}
        >
          {confirmState?.confirmLabel ?? t("common.confirm")}
        </Button>
      </div>
    </Dialog>
  );
}

const SHORTCUTS: { keys: string[]; label: MessageKey }[] = [
  { keys: ["mod", "shift", "O"], label: "sc.new" },
  { keys: ["mod", "K"], label: "sc.search" },
  { keys: ["mod", "shift", "S"], label: "sc.sidebar" },
  { keys: ["mod", "."], label: "sc.panel" },
  { keys: ["mod", ","], label: "sc.settings" },
  { keys: ["mod", "/"], label: "sc.help" },
];

export function ShortcutsDialog() {
  const { t } = useI18n();
  const { shortcutsOpen, setShortcutsOpen } = useStore();
  const label = (k: string) => (k === "mod" ? (isMac ? "⌘" : "Ctrl") : k === "shift" ? (isMac ? "⇧" : "Shift") : k);
  return (
    <Dialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} title={t("settings.shortcuts")}>
      <ul className="px-6 pb-6 pt-2">
        {SHORTCUTS.map((s) => (
          <li key={s.label} className="flex items-center justify-between border-b border-line/[0.06] py-3 text-sm last:border-none">
            <span>{t(s.label)}</span>
            <span className="flex gap-1">
              {s.keys.map((k) => (
                <Kbd key={k}>{label(k)}</Kbd>
              ))}
            </span>
          </li>
        ))}
      </ul>
    </Dialog>
  );
}
