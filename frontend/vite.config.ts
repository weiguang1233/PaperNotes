import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8766" }
  },
  // Cross-platform launchers serve this prebuilt directory without Node.js.
  build: { outDir: "dist-portable", sourcemap: false }
});
