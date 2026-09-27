import { CloudOff, Compass } from "lucide-react";
import { lazy, Suspense } from "react";
import { SearchDialog } from "./components/dialogs/SearchDialog";
import { SettingsDialog } from "./components/dialogs/SettingsDialog";
import { ConfirmDialog, ShortcutsDialog } from "./components/dialogs/SmallDialogs";
import { Header } from "./components/Header";
import { Sidebar } from "./components/Sidebar";
import { Button, EmptyState, Spinner, TooltipProvider } from "./components/ui";
import { useHotkeys } from "./lib/hooks";
import { I18nProvider, useI18n } from "./lib/i18n";
import { PrefsProvider, usePrefs } from "./lib/prefs";
import { RouterProvider, useRouter } from "./lib/router";
import { StoreProvider, useStore } from "./lib/store";
import { ToastProvider } from "./lib/toast";
import { Home } from "./pages/Home";

const RunView = lazy(() => import("./pages/RunView").then((m) => ({ default: m.RunView })));
const Library = lazy(() => import("./pages/Library").then((m) => ({ default: m.Library })));
const Lessons = lazy(() => import("./pages/Lessons").then((m) => ({ default: m.Lessons })));

export function App() {
  return (
    <I18nProvider>
      <PrefsProvider>
        <RouterProvider>
          <ToastProvider>
            <StoreProvider>
              <TooltipProvider delayDuration={350} skipDelayDuration={200}>
                <Shell />
              </TooltipProvider>
            </StoreProvider>
          </ToastProvider>
        </RouterProvider>
      </PrefsProvider>
    </I18nProvider>
  );
}

function Shell() {
  const { route, navigate } = useRouter();
  const { setSidebarOpen } = usePrefs();
  const { setSearchOpen, openSettings, setShortcutsOpen, metaError, meta } = useStore();

  useHotkeys({
    "mod+k": () => setSearchOpen(true),
    "mod+shift+o": () => navigate("/"),
    "mod+shift+s": () => setSidebarOpen((v) => !v),
    "mod+,": () => openSettings("general"),
    "mod+/": () => setShortcutsOpen(true),
    "mod+.": () => window.dispatchEvent(new Event("tyche:toggle-panel")),
  });

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-main text-fg">
      <Sidebar />
      <main className="relative flex min-w-0 flex-1 flex-col">
        {metaError && !meta ? (
          <Offline />
        ) : (
          <Suspense fallback={<RouteLoading />}>
            {route.name === "home" && <Home />}
            {route.name === "run" && <RunView key={route.id} id={route.id} tab={route.tab} />}
            {route.name === "library" && <Library />}
            {route.name === "lessons" && <Lessons />}
            {route.name === "notfound" && <NotFound />}
          </Suspense>
        )}
      </main>
      <SearchDialog />
      <SettingsDialog />
      <ShortcutsDialog />
      <ConfirmDialog />
    </div>
  );
}

function RouteLoading() {
  return (
    <div className="flex h-full items-center justify-center">
      <Spinner className="h-5 w-5 text-faint" />
    </div>
  );
}

function NotFound() {
  const { t } = useI18n();
  const { navigate } = useRouter();
  return (
    <div className="flex h-full flex-col">
      <Header />
      <EmptyState
        icon={<Compass />}
        title={t("notfound.title")}
        body={t("notfound.body")}
        action={
          <Button variant="primary" onClick={() => navigate("/")}>
            {t("nav.new")}
          </Button>
        }
      />
    </div>
  );
}

function Offline() {
  const { t } = useI18n();
  const { reloadMeta } = useStore();
  return (
    <div className="flex h-full flex-col">
      <Header />
      <EmptyState
        icon={<CloudOff />}
        title={t("app.offline")}
        body={t("app.offlineBody")}
        action={
          <Button variant="outline" onClick={() => void reloadMeta()}>
            {t("common.retry")}
          </Button>
        }
      />
    </div>
  );
}
