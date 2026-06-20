PWA support notes:
- manifest.webmanifest and sw.js are included for deployment.
- Streamlit local dev may not register a service worker from a single-file app.
- For full installability, deploy behind HTTPS and serve these assets from the same origin.
