# Frontend compatibility entry point

The canonical React application now lives in `modules/analysis/dashboard`.
The npm commands in this directory delegate to that package so existing local
workflows continue to work. Do not add chart or study behavior here.

```bash
npm run dev
npm run build
```

The old components remain temporarily as migration references and will be
removed after downstream callers have moved to the dashboard contracts.
