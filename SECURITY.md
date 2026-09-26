# Security policy

## Reporting a vulnerability

Please don't report security issues in public GitHub issues, discussions or pull
requests.

Email [support@optiqio.com](mailto:support@optiqio.com) with "security" in the
subject, or use GitHub's
[private vulnerability reporting](https://github.com/optiq-io/qbrix/security/advisories/new).
Include:

- the affected component (proxy, motor, cortex, trace, console, helm chart, compose)
  and version or commit
- steps to reproduce, or a proof of concept
- the impact as you understand it

We aim to acknowledge a report within three working days and to agree a disclosure
timeline with you once we have confirmed the issue. We will credit you in the
advisory unless you ask us not to.

## Supported versions

qbrix is pre-1.0. Security fixes land on `main` and ship in the next release. Only
the latest release is supported; we do not backport to older ones.

| Version | Supported |
|---------|-----------|
| latest release | yes |
| older releases | no |

## Scope

This policy covers the code in this repository and the images and chart published
from it. The SDKs have their own repositories:
[qbrix-python](https://github.com/optiq-io/qbrix-python) and
[qbrix-js](https://github.com/optiq-io/qbrix-js).

If you run qbrix yourself, you are responsible for your deployment: keep the
generated secrets secret, put TLS in front of the gateway, and don't expose
Postgres, Redis or ClickHouse to the internet.
