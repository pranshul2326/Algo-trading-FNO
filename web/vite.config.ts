import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

const root = import.meta.dirname;

// Multi-page build: each page keeps the same path as the Python app.
export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: resolve(root, "index.html"),
        charts: resolve(root, "charts/index.html"),
        chain: resolve(root, "chain/index.html"),
        combo: resolve(root, "combo/index.html"),
        notFound: resolve(root, "404.html"),
      },
    },
  },
  test: {
    include: ["tests/**/*.test.ts"],
  },
});
