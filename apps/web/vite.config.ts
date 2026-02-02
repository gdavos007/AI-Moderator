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
  }
});
