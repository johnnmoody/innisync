import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// The built UI goes into the Python package, which serves it on 127.0.0.1.
// In dev, `npm run dev` proxies the API to a running InniSync server. The server only accepts requests addressed to
// itself from its own page, so the proxy presents the server's own address and drops the dev page's Origin.
const target = "http://127.0.0.1:8765";
const toServer = {
  target,
  changeOrigin: true,
  configure: (proxy) => proxy.on("proxyReq", (req) => req.removeHeader("origin")),
};

export default defineConfig({
  plugins: [svelte()],
  base: "./",
  build: { outDir: "../innisync/web", emptyOutDir: true, assetsInlineLimit: 0 },
  server: { proxy: { "/api": toServer, "/art": toServer, "/stream": toServer, "/devimg": toServer } },
});
