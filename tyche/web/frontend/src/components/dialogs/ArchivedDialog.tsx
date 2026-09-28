import { ArchiveRestore, Trash2 } from "lucide-react";
import { api } from "../../api/client";
import { relativeTime } from "../../lib/format";
import { useAsync } from "../../lib/hooks";
import { useI18n } from "../../lib/i18n";
import { useRouter } from "../../lib/router";
import { useStore } from "../../lib/store";
import { useToast } from "../../lib/toast";
import { Dialog, EmptyState, IconButton, Spinner } from "../ui";

export function ArchivedDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { t } = useI18n();
  const { refreshRuns, confirm } = useStore();
  const { navigate } = useRouter();
  const toast = useToast();
  const archived = useAsync(() => api.runs(true), [open], { enabled: open });

  const restore = async (id: string) => {
    try {
      await api.patch(id, { archived: false });
      toast("success", t("toast.unarchived"));
      archived.reload();
      await refreshRuns();
    } catch (e) {
      toast("error", t("common.error"), (e as Error).message);
    }
  };
  const remove = async (id: string) => {
    const ok = await confirm({ title: t("run.deleteConfirm"), body: t("run.deleteBody"), confirmLabel: t("run.delete"), destructive: true });
    if (!ok) return;
    try {
      await api.remove(id);
      toast("success", t("toast.deleted"));
      archived.reload();
    } catch (e) {
      toast("error", t("common.error"), (e as Error).message);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("nav.archived")} wide>
      <div className="min-h-[240px] overflow-y-auto px-3 pb-4 pt-2">
        {archived.loading && !archived.data && (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        )}
        {archived.data?.length === 0 && <EmptyState title={t("panel.empty")} />}
        <ul>
          {archived.data?.map((r) => (
            <li key={r.run_id} className="group flex items-center gap-3 rounded-xl px-3 py-2.5 hover:bg-subtle/[0.04]">
              <button
                className="min-w-0 flex-1 text-left"
                onClick={() => {
                  onOpenChange(false);
                  navigate(`/r/${encodeURIComponent(r.run_id)}`);
                }}
              >
                <div className="truncate text-sm">{r.title}</div>
                <div className="truncate text-xs text-faint">
                  {r.run_id} · {relativeTime(r.updated_at, t)}
                </div>
              </button>
              <IconButton label={t("run.unarchive")} size="sm" onClick={() => restore(r.run_id)}>
                <ArchiveRestore className="h-4 w-4" />
              </IconButton>
              <IconButton label={t("run.delete")} size="sm" onClick={() => remove(r.run_id)} className="hover:text-bad">
                <Trash2 className="h-4 w-4" />
              </IconButton>
            </li>
          ))}
        </ul>
      </div>
    </Dialog>
  );
}
