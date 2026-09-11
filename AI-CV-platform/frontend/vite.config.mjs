import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const backend = process.env.AICV_BACKEND ?? "http://127.0.0.1:8002";
const here = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  cacheDir: path.join(here, ".vite"),
  server: {
    host: "0.0.0.0",
    port: 5174,
    allowedHosts: true,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
    },
  },
});
