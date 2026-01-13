import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Test files location
    include: ['tests/**/*.test.js'],

    // Environment - use Node (not jsdom) since we mock window ourselves
    environment: 'node',

    // Globals - use import/require instead of globals
    globals: false,

    // Coverage
    coverage: {
      provider: 'v8',
      include: ['services/frontend-economics/*.js'],
      exclude: ['**/*.test.js', '**/node_modules/**']
    },

    // Timeout for slow tests
    testTimeout: 10000,

    // Reporter
    reporters: ['verbose']
  }
});
