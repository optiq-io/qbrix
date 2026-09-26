import * as Sentry from "@sentry/nextjs";

import { sharedOptions } from "./sentry.shared";

Sentry.init(sharedOptions);

// no spans are produced while tracesSampleRate is 0; the sdk warns on every
// build if the hook is missing.
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
