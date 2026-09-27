import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

declare const process: { env: Record<string, string | undefined> };

// `npm run dev` proxies the API to a running `tyche ui --no-browser` (default port 8765).
const backend = process.env.TYCHE_UI_BACKEND ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5178,
    proxy: { "/api": { target: backend, changeOrigin: false } },
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
