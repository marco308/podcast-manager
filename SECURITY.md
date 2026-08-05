# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Instead, use GitHub's private vulnerability reporting: the **Security** tab of this repository → **Report a vulnerability**. You'll get a response as soon as practical, and a fix will be coordinated before any public disclosure.

## Supported versions

Only the latest code on `main` is supported. There are no maintained release branches.

## Scope notes

Podcast Manager is a self-hosted application. Securing the deployment itself — TLS termination, reverse-proxy configuration, network exposure, and the host — is the operator's responsibility. Reports about the application's own behavior (authentication, session handling, CSRF, token encryption, the Spotify OAuth flow) are very welcome.
