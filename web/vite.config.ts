import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  // Built into the Python package so `uv tool install` / pip installs ship the dashboard too.
  build: { outDir: "../jobsmith/web_dist", emptyOutDir: true },
  // `jobsmith dev` points this at the practice copy (port 8766); plain `npm run dev` uses your real engine.
  server: { proxy: { "/api": process.env.JOBSMITH_API || "http://127.0.0.1:8765" } },
});
