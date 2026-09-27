import clsx from "clsx";
import { Braces, ChevronRight, File, FileCode2, FileText, Folder } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../../api/client";
import type { ArtifactInfo, ArtifactVersion } from "../../api/types";
import { formatBytes, relativeTime } from "../../lib/format";
import { useAsync } from "../../lib/hooks";
import { useI18n } from "../../lib/i18n";
import { CodeView, languageForPath, Markdown } from "../Markdown";
import { PanelLoading, PanelMessage, type TabProps } from "./RightPanel";

const KIND_ICON = { json: Braces, md: FileText, tex: FileCode2, bib: FileCode2, pdf: File, dir: Folder, other: File } as const;

interface Selection {
  artifact: ArtifactInfo;
  version: ArtifactVersion;
  path?: string;
}

/** Every artifact version in the run's provenance, grouped by stage, with an inline viewer. */
export default function FilesTab({ runId, detail }: TabProps) {
  const { t } = useI18n();
  const list = useAsync(() => api.artifacts(runId), [runId, detail.updated_at]);
  const [sel, setSel] = useState<Selection | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const byStage = useMemo(() => {
    const map = new Map<string, ArtifactInfo[]>();
    for (const a of list.data ?? []) {
      const stage = a.versions[a.versions.length - 1]?.stage ?? "other";
      map.set(stage, [...(map.get(stage) ?? []), a]);
    }
    return [...map.entries()];
  }, [list.data]);

  if (list.loading && !list.data) return <PanelLoading />;
  if (!list.data?.length) return <PanelMessage>{t("panel.empty")}</PanelMessage>;

  return (
    <div className="flex h-full min-h-0">
      <nav className="w-[40%] min-w-[170px] max-w-[260px] shrink-0 overflow-y-auto border-r border-line/[0.06] py-2">
        {byStage.map(([stage, items]) => (
          <div key={stage} className="mb-2">
            <div className="px-3 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">{stage}</div>
            {items.map((a) => {
              const Icon = KIND_ICON[a.kind] ?? File;
              const latest = a.versions[a.versions.length - 1];
              const isOpen = expanded === a.name;
              return (
                <div key={a.name}>
                  <button
                    onClick={() => {
                      setSel({ artifact: a, version: latest });
                      setExpanded(isOpen ? null : a.name);
                    }}
                    className={clsx(
                      "flex w-full items-center gap-1.5 py-1.5 pl-3 pr-2 text-left text-[12.5px]",
                      sel?.artifact.name === a.name ? "bg-subtle/[0.07] text-fg" : "text-muted hover:bg-subtle/[0.04] hover:text-fg",
                    )}
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0" />
                    <span className="min-w-0 flex-1 truncate font-mono">{a.name}</span>
                    {a.versions.length > 1 && <span className="text-[10.5px] text-faint">v{latest.version}</span>}
                    {a.versions.length > 1 && <ChevronRight className={clsx("h-3 w-3 shrink-0 text-faint transition-transform", isOpen && "rotate-90")} />}
                  </button>
                  {isOpen && a.versions.length > 1 && (
                    <div className="pb-1">
                      {[...a.versions].reverse().map((v) => (
                        <button
                          key={v.version}
                          onClick={() => setSel({ artifact: a, version: v })}
                          className={clsx(
                            "flex w-full items-center gap-2 py-1 pl-8 pr-2 text-left text-[11.5px]",
                            sel?.artifact.name === a.name && sel.version.version === v.version ? "text-fg" : "text-faint hover:text-fg",
                          )}
                        >
                          <span className="font-mono">v{v.version}</span>
                          <span className="truncate">{v.stage}</span>
                          <span className="ml-auto shrink-0">{relativeTime(v.created_at, t)}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="min-w-0 flex-1 overflow-auto">{sel ? <ArtifactViewer runId={runId} sel={sel} onPath={(path) => setSel({ ...sel, path })} /> : <PanelMessage>{t("exp.selectFile")}</PanelMessage>}</div>
    </div>
  );
}

function ArtifactViewer({ runId, sel, onPath }: { runId: string; sel: Selection; onPath: (p: string | undefined) => void }) {
  const { t } = useI18n();
  const { artifact, version, path } = sel;
  const isDir = artifact.kind === "dir";
  const dir = useAsync(() => api.artifactDir(runId, artifact.name, version.version), [runId, artifact.name, version.version], { enabled: isDir });
  const viewPath = isDir ? path : undefined;
  const canText = artifact.kind !== "pdf" && (!isDir || !!viewPath);
  const text = useAsync(
    () => api.artifactText(runId, artifact.name, version.version, viewPath),
    [runId, artifact.name, version.version, viewPath],
    { enabled: canText },
  );
  const fileName = viewPath ?? version.path;
  const lang = artifact.kind === "json" ? "json" : artifact.kind === "md" ? "markdown" : languageForPath(fileName);
  const body = typeof text.data === "string" ? text.data : text.data != null ? JSON.stringify(text.data, null, 2) : "";

  return (
    <div className="min-h-full">
      <div className="sticky top-0 z-[1] flex items-center gap-2 border-b border-line/[0.06] bg-main/95 px-4 py-2 text-[11.5px] text-faint backdrop-blur">
        {isDir && viewPath && (
          <button onClick={() => onPath(undefined)} className="hover:text-fg">
            {artifact.name}/
          </button>
        )}
        <span className="min-w-0 truncate font-mono">{viewPath ?? `${artifact.name} v${version.version}`}</span>
        <span className="ml-auto shrink-0 font-mono">sha256 {version.sha256.slice(0, 12)}</span>
        <span className="shrink-0">{formatBytes(version.size)}</span>
      </div>
      {artifact.kind === "pdf" ? (
        <PanelMessage>
          <a className="underline" href={`/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifact.name)}/${version.version}`} target="_blank" rel="noopener noreferrer">
            {t("panel.openNew")}
          </a>
        </PanelMessage>
      ) : isDir && !viewPath ? (
        dir.loading && !dir.data ? (
          <PanelLoading />
        ) : (
          <ul className="py-1">
            {(dir.data?.files ?? []).map((f) => (
              <li key={f.path}>
                <button onClick={() => onPath(f.path)} className="flex w-full items-center gap-2 px-4 py-1.5 text-left font-mono text-[12px] text-muted hover:bg-subtle/[0.04] hover:text-fg">
                  <File className="h-3.5 w-3.5 shrink-0 text-faint" />
                  <span className="truncate">{f.path}</span>
                  <span className="ml-auto shrink-0 text-faint">{formatBytes(f.size)}</span>
                </button>
              </li>
            ))}
          </ul>
        )
      ) : text.loading && text.data == null ? (
        <PanelLoading />
      ) : text.error ? (
        <PanelMessage>{text.error.message}</PanelMessage>
      ) : lang === "markdown" ? (
        <div className="px-5 py-4">
          <Markdown text={body} />
        </div>
      ) : (
        <CodeView code={body} language={lang} />
      )}
    </div>
  );
}
