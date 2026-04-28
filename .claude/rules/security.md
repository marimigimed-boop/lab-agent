# Security Rules

## Secrets Management (Hard Rules)
- NEVER hardcode API keys, passwords, tokens in source code
- NEVER commit .env files — always in .gitignore
- NEVER log passwords, tokens, or PII
- Use environment variables for all secrets
- .env.example with placeholder values only

## OWASP Top 10 Auto-Enforcement
- **Injection**: Always use parameterized queries / ORM — never string concat SQL
- **Auth**: bcrypt (cost 12+) for passwords; sessions expire after 30min idle
- **XSS**: Sanitize all user input before HTML rendering; use CSP headers
- **Access Control**: Every endpoint checks ownership; deny by default
- **SSRF**: Validate all user-provided URLs; block internal IP ranges
- **Components**: Run dependency audit after every install

## Required Security Headers (all web responses)
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Strict-Transport-Security: max-age=31536000; includeSubDomains
- Content-Security-Policy: default-src 'self'
- Referrer-Policy: strict-origin-when-cross-origin

## Rate Limiting Defaults
- Auth endpoints: 5 req/min per IP
- API read: 100 req/min per user
- API write: 30 req/min per user
- File upload: 10 req/min per user

## Input Validation
- Validate at ALL system boundaries (user input, API responses, file reads)
- Use schema validation libraries (Pydantic, Zod, etc.)
- File uploads: validate by magic bytes, not extension; max 5MB; store outside web root

## Error Handling
- Production: generic error messages with error ID only
- Never expose stack traces, SQL, file paths, or internal IPs to users
- Log full details server-side with same error ID

## Incident Response
If security issue detected during development:
1. STOP current task
2. Alert user with plain-language description
3. Provide specific fix steps
4. Do NOT proceed until user acknowledges
