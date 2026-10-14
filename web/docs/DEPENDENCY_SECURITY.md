# Frontend Dependency Security

## Baseline — 14 October 2026

- Framework: Next.js 16.4.0
- React: 19.3.0
- Production audit: 0 reported vulnerabilities
- Full audit: 5 high-severity findings
- Affected chain:
  eslint-config-next -> @next/eslint-plugin-next ->
  fast-glob -> micromatch -> braces
- Advisory: GHSA-vfj7-8cjw-p6xm

## Decision

Do not apply npm audit fix --force because its proposed
ESLint configuration downgrade is incompatible with
the project's Next.js major version.

Continue local frontend development while tracking
the advisory and upstream dependency updates.

Reassess before deployment. A clean production audit
does not establish that the application is secure.

## Verification

Run from web/:

npm audit --omit=dev
npm audit
npm run build
npm run lint
