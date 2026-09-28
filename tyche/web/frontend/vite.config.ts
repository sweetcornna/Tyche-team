import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

declare const process: { env: Record<string, string | undefined> };

// `npm run dev` proxies the API to a running `tyche ui --no-browser` (default port 8765).
const backend = process.env.TYCHE_UI_BACKEND ?? "http://127.0.0.1:8765";
const devPort = 5178;
const devOrigin = new RegExp(`^http://(localhost|127\\.0\\.0\\.1|\\[::1\\]):${devPort}$`);

type ProxyRequest = { getHeader(name: string): unknown; setHeader(name: string, value: string): void };
type ProxyEvents = { on(event: "proxyReq", listener: (req: ProxyRequest) => void): void };

export default defineConfig({
  plugins: [react()],
  server: {
    port: devPort,
    proxy: {
      "/api": {
        target: backend,
        changeOrigin: false,
        // Requests from the dev page itself carry the dev server's origin, which the API's Origin
        // guard rejects; present them as the backend's own. Any other origin is passed through
        // unchanged, so a cross-site page still cannot act through the dev server.
        configure: (proxy) =>
          (proxy as unknown as ProxyEvents).on("proxyReq", (req) => {
            const origin = req.getHeader("origin");
            if (typeof origin === "string" && devOrigin.test(origin)) req.setHeader("origin", backend);
          }),
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return undefined;
          if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return "react";
          if (id.includes("@radix-ui") || id.includes("@floating-ui")) return "radix";
          if (/node_modules\/(react-markdown|remark-|mdast-|micromark|unified|hast-|unist-|vfile|highlight\.js)/.test(id)) return "markdown";
          return undefined;
        },
      },
    },
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
