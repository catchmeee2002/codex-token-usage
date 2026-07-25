# Security Policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

Use the repository's **Security** tab and choose **Report a vulnerability** to submit a private
GitHub Security Advisory. Include:

- Affected command or component
- Reproduction steps or a minimal proof of concept
- Expected and observed impact
- Suggested mitigation, if known

Avoid attaching real API keys, prompts, responses, session IDs, or private local paths. The
maintainer will acknowledge the report, investigate it, and coordinate disclosure and remediation
through the private advisory.

## Scope

Security reports may include accidental disclosure of local session content, unsafe path handling,
command execution, privilege-boundary issues, or dependency vulnerabilities. Incorrect token totals
without a security impact should be reported with the bug template instead.
