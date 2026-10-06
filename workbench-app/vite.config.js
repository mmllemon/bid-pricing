var _a, _b;
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
var apiProxy = ((_b = (_a = globalThis.process) === null || _a === void 0 ? void 0 : _a.env) === null || _b === void 0 ? void 0 : _b.VITE_API_PROXY)
    || 'http://localhost:3456';
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            '/api': {
                target: apiProxy,
                changeOrigin: true,
            },
        },
    },
    build: {
        outDir: 'dist',
        sourcemap: false,
    },
});
