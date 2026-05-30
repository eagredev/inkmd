# Security policy

## Supported versions

Security fixes target the most recent release on the `main` branch.
Older versions are not back-patched.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security
vulnerabilities.

The preferred reporting channel is **GitHub's private vulnerability
reporting** for this repository:

  https://github.com/eagredev/inkmd/security/advisories/new

If that is not workable for any reason, email
`eagre.dev@gmail.com` with the subject line
`[inkmd security]` and a description of the issue.

You can expect:

- An acknowledgement within seven days.
- A first assessment of the report (accepted, needs more
  information, or not a security issue) within fourteen days.
- For accepted reports, public disclosure coordinated with the
  reporter once a fix is in place.

## Scope

inkmd is a markdown-to-PDF library and CLI. The relevant attack
surface includes:

- Compiling untrusted markdown to PDF and the integrity of the
  resulting bytes.
- The URL-scheme allow-list for link annotations
  (``safe=True``, default).
- The inline HTML allow-list (``html=True``, default).
- The optional remote-image fetcher (``allow_remote_images=True``,
  off by default).

The full threat model, known issues, and caller responsibilities
when feeding untrusted input are documented in
[`docs/security.md`](docs/security.md).

## Out of scope

- Bugs in the PDF reader used to view the output. inkmd emits PDF
  1.4 bytes; rendering is the reader's responsibility.
- Issues that require disabling the on-by-default URL-scheme
  filter (``safe=False``) or the on-by-default HTML allow-list
  (``html=False``). These are explicit opt-outs into a less
  filtered mode.
- Denial-of-service via inputs that legitimately require large
  amounts of memory or CPU to render. inkmd's resource posture is
  documented in `docs/security.md`.
