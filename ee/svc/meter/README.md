# metersvc

EE service that consumes the `qbrix:selection` stream and reports selection
usage to a Stripe billing meter for real-time usage-based billing.

Single instance by design — see `service.py` for why.

## Deployment

Built and pushed to ECR (`qbrix/meter`) by the CI build matrix and deployed to
EKS via the umbrella chart (`ee.meter.enabled`).
