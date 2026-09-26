import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  output: "standalone",
  transpilePackages: ["@qbrix/ui"],
};

export default withSentryConfig(nextConfig, {
  silent: true,
  telemetry: false,
  // source maps are not uploaded yet, so stack traces stay minified until the
  // auth-token wiring lands. leaving upload enabled without a token only adds
  // a failing build step.
  sourcemaps: { disable: true },
});
