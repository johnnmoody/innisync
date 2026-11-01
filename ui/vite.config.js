import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// The built UI goes into the Python package, which serves it on 127.0.0.1.
// In dev, `npm run dev` proxies the API to a running InniSync server.
export default defineConfig({
  plugins: [svelte()],
  base: "./",
  build: { outDir: "../innisync/web", emptyOutDir: true, assetsInlineLimit: 0 },
  server: { proxy: { "/api": "http://127.0.0.1:8765", "/art": "http://127.0.0.1:8765", "/stream": "http://127.0.0.1:8765", "/devimg": "http://127.0.0.1:8765" } },
});
