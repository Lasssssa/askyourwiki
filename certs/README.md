# Custom CA certificates

Drop any extra CA certificates this deployment needs to trust into this folder,
then rebuild the Docker image. This is entirely optional: with an empty folder
the build behaves exactly as before and trusts the standard public CAs.

## Usage

- Add one file per CA, PEM-encoded and named `*.crt` (the `.crt` extension is
  required — `update-ca-certificates` ignores anything else). Rename a `.pem`
  file to `.crt` if needed.
- The certificates are installed into the OS trust store at build time and the
  application's Python HTTP client (httpx) is pointed at the same bundle, so
  both system tools and the app trust them.

## Git

The certificates themselves are gitignored so they are never committed; only
this README and `.gitkeep` are tracked to keep the folder present in the build
context.
