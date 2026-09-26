# qbrix cloud edition

The `ee` directories hold the cloud plugin, the code that runs qbrix as a
managed, billed service:

- `ee/svc/meter/`: metersvc, which emits selection usage to Stripe.
- `svc/proxy/src/proxysvc/ee/`: billing and checkout, plan tiers, and the
  selection quota. The proxy loads it only when `PROXY_EE_ENABLED=true`,
  through `proxysvc/edition.py`.
- `web/apps/console/src/ee/` and `web/apps/console/src/app/(ee)/`: the billing,
  checkout and plan screens. The console renders them only when the backend
  reports the cloud edition, through `src/lib/edition.ts`.
- `svc/proxy/tests/ee/`: their tests.

The complete list is `bin/ee-paths.txt`. Everything outside those paths is the
core product, licensed under Apache-2.0, and runs without them: CI deletes
every listed path and runs the suite on every push.

The content under these paths is licensed under the qbrix Enterprise License
in `ee/LICENSE`: free to read, modify and test, with production use requiring
an agreement with Optiq B.V.
