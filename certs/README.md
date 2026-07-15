# Custom CA certificates

Drop any extra CA certificates this deployment needs to trust into this folder,
then rebuild the Docker image. This is optional: with an empty folder the build
still works and trusts the standard public CAs.

Use this when your environment presents certificates signed by a private CA —
for example a self-hosted GitLab behind a TLS-intercepting corporate proxy.

## Usage

- Add one file per CA, PEM-encoded and named `*.crt` (the `.crt` extension is
  required — `update-ca-certificates` ignores anything else). Rename a `.pem`
  file to `.crt` if needed.
- At build time the certificates are installed into the OS trust store
  (`update-ca-certificates`), and the image is configured so Python trusts the
  same bundle:
  - `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` point the standard library, `httpx`
    and `requests` at `/etc/ssl/certs/ca-certificates.crt`.
  - `pip-system-certs` makes pip and any certifi-based client use the OS trust
    store as well.

## Proxy vs. certificates

These are two independent concerns:

- **Proxy** — to *reach* the network through a corporate proxy while building,
  pass `--build-arg HTTP_PROXY=... HTTPS_PROXY=... NO_PROXY=...` (see the
  `Dockerfile`). Needed when the build host has no direct internet access.
- **Certificates** — to *trust* a private CA (proxy interception or an internal
  GitLab), drop the CA here. Needed when TLS is terminated/re-signed by
  something whose CA isn't publicly trusted.

Depending on your setup you may need one, the other, or both.

## Git

The certificates themselves are gitignored so they are never committed; only
this README and `.gitkeep` are tracked to keep the folder present in the build
context.
