import "@testing-library/jest-dom/vitest";
import { vi, afterEach } from "vitest";

// Polyfill crypto.randomUUID for jsdom
if (!globalThis.crypto) {
  globalThis.crypto = {
    randomUUID: () => `test-${Math.random().toString(16).slice(2)}`
  } as Crypto;
}

// Reset fetch mock after each test
afterEach(() => {
  vi.unstubAllGlobals();
});
