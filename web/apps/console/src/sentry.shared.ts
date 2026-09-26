/** every runtime reports to the same project under the same build-inlined identity. */
export const sharedOptions = {
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT,
  release: process.env.NEXT_PUBLIC_SENTRY_RELEASE,
  // errors only — tracing is a later milestone, and enabling it here would bill
  // spans against the quota before anyone asked for them.
  tracesSampleRate: 0,
  sendDefaultPii: false,
};
