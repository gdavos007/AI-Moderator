/// <reference types="vitest" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Use vitest/config instead of vite to get test config types
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true, // Enable global test APIs (describe, it, expect)
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    css: true,
    restoreMocks: true, // Auto-restore mocks between tests
  },
  server: {
    // Add your ngrok host here
    allowedHosts: ["a2a922a6e4ef.ngrok-free.app", "localhost", "http://127.0.0.1"]
  }
});
