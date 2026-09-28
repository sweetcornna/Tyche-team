import { createContext, useCallback, useContext, useEffect, useMemo, useState, type AnchorHTMLAttributes, type ReactNode } from "react";

export type Route =
  | { name: "home" }
  | { name: "run"; id: string; tab?: string }
  | { name: "library" }
  | { name: "lessons" }
  | { name: "notfound" };

export function parseRoute(pathname: string, search = ""): Route {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === "/") return { name: "home" };
  if (path === "/library") return { name: "library" };
  if (path === "/lessons") return { name: "lessons" };
  const m = path.match(/^\/r\/([^/]+)$/);
  if (m) {
    const tab = new URLSearchParams(search).get("panel") ?? undefined;
    return { name: "run", id: decodeURIComponent(m[1]), tab };
  }
  return { name: "notfound" };
}

export function routePath(route: Route): string {
  switch (route.name) {
    case "home":
      return "/";
    case "library":
      return "/library";
    case "lessons":
      return "/lessons";
    case "run":
      return `/r/${encodeURIComponent(route.id)}${route.tab ? `?panel=${encodeURIComponent(route.tab)}` : ""}`;
    default:
      return "/";
  }
}

const RouterContext = createContext<{ route: Route; navigate: (to: string, opts?: { replace?: boolean }) => void }>({
  route: { name: "home" },
  navigate: () => undefined,
});

export function RouterProvider({ children }: { children: ReactNode }) {
  const [route, setRoute] = useState<Route>(() => parseRoute(location.pathname, location.search));
  useEffect(() => {
    const onPop = () => setRoute(parseRoute(location.pathname, location.search));
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, []);
  const navigate = useCallback((to: string, opts?: { replace?: boolean }) => {
    if (to === location.pathname + location.search) return;
    if (opts?.replace) history.replaceState(null, "", to);
    else history.pushState(null, "", to);
    setRoute(parseRoute(location.pathname, location.search));
  }, []);
  const value = useMemo(() => ({ route, navigate }), [route, navigate]);
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

export const useRouter = () => useContext(RouterContext);

/** An <a> that navigates client-side (keeps cmd/ctrl-click opening a new tab). */
export function Link({ to, onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) {
  const { navigate } = useRouter();
  return (
    <a
      href={to}
      onClick={(e) => {
        onClick?.(e);
        if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        navigate(to);
      }}
      {...rest}
    />
  );
}
