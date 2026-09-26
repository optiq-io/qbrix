import { routes } from "@/config/routes";

export type ErrorAction = {
  label: string;
  href?: string;
};

export type ErrorEntry = {
  title: string;
  description?: (detail: string, context?: Record<string, unknown>) => string;
  hint?: string;
  action?: ErrorAction;
};

export const errorRegistry: Record<string, ErrorEntry> = {
  POOL_HAS_EXPERIMENTS: {
    title: "Pool has active experiments",
    description: () =>
      "This pool has experiments attached. Delete or reassign them before deleting the pool.",
    action: { label: "View experiments", href: routes.home },
  },
  EXPERIMENT_LIMIT_REACHED: {
    title: "Experiment limit reached",
    description: () =>
      "You've hit the active experiment cap on your current plan. Archive an existing experiment or upgrade to add more.",
    action: { label: "Upgrade plan", href: routes.settingsBilling },
  },
  API_KEY_LIMIT_REACHED: {
    title: "API key limit reached",
    description: () =>
      "Your workspace has used every active API key your plan allows, across all its members. Revoke an existing key or upgrade to create more.",
    action: { label: "Manage API keys", href: routes.settingsApiKeys },
  },
  UNKNOWN_PRICE_ID: {
    title: "That plan can't be purchased right now",
    description: () =>
      "Checkout was refused because this deployment has no Stripe price configured for the plan. Nothing was charged.",
    hint: "This is a configuration problem, not something you did — contact support and we'll sort it.",
  },
  RATE_LIMITED: {
    title: "Rate limit exceeded",
    description: () =>
      "You're sending requests faster than your plan allows. Slow down or upgrade for a higher rate limit.",
    action: { label: "Upgrade plan", href: routes.settingsBilling },
  },
  INSUFFICIENT_SCOPES: {
    title: "Not enough permissions",
    hint: "Ask a workspace admin to grant you the role or scope needed for this action.",
  },
  FORBIDDEN: {
    title: "Not enough permissions",
    description: (detail) => detail,
    hint: "Ask a workspace admin to perform this action.",
  },
  INVALID_POLICY_PARAMS: {
    title: "Policy parameters are invalid",
    description: (detail) => detail,
    hint: "Check the parameter constraints in the policy reference and try again.",
  },
  INVALID_CONTEXT_PROPERTIES: {
    title: "Context doesn't match the schema",
    description: (detail) => detail,
    hint: "Properties are encoded against the schema declared when the experiment was created. Send the declared names, or the experiment's vector if it has no schema.",
  },
  CONTEXT_DIM_IMMUTABLE: {
    title: "Context width can't be changed",
    description: (detail) => detail,
    hint: "The learned parameters are shaped by the width, so changing it would invalidate everything trained so far. Create a new experiment to change the shape.",
  },
  CONTEXT_SCHEMA_IMMUTABLE: {
    title: "Context schema can't be changed",
    description: (detail) => detail,
    hint: "Learned parameters have the schema's width baked in, so changing it would invalidate everything trained so far. Create a new experiment to change the shape.",
  },
  LEARNER_EXPERIMENT_DELETE_FORBIDDEN: {
    title: "Cannot delete a learner experiment",
    description: () =>
      "This experiment is managed by a meta-experiment learner and can't be deleted directly. Delete the parent meta-experiment instead.",
  },
  USER_ALREADY_EXISTS: {
    title: "Email already registered",
    hint: "Try logging in instead, or use a different email address.",
    action: { label: "Go to login", href: routes.login },
  },
  INVALID_IDENTITY: {
    title: "That name can't be used",
    description: (detail) => detail,
    hint: "Names can't contain links. Slugs use lowercase letters, digits and hyphens.",
  },
  INVITE_LIMIT_EXCEEDED: {
    title: "Daily invite limit reached",
    description: (detail) => detail,
    hint: "Pending and revoked invites count toward the limit. It resets at midnight UTC.",
  },
  INVALID_TOKEN: {
    title: "Session expired",
    description: () => "Your session is no longer valid. Please log in again.",
    action: { label: "Log in", href: routes.login },
  },
  EMAIL_NOT_VERIFIED: {
    title: "Email not verified",
    description: () =>
      "Verify your email address before signing in. Check your inbox for the verification link.",
    hint: "Didn't get it? Request a new link from the login screen.",
  },
  INVALID_API_KEY: {
    title: "Invalid API key",
    hint: "Check that the key is active and was copied correctly.",
  },
  POOL_NOT_FOUND: {
    title: "Pool not found",
    description: () => "This pool may have been deleted. Refresh the page to see the latest data.",
  },
  EXPERIMENT_NOT_FOUND: {
    title: "Experiment not found",
    description: () => "This experiment may have been deleted. Refresh the page to see the latest data.",
  },
  GATE_NOT_FOUND: {
    title: "Feature gate not found",
    description: () => "No gate is configured for this experiment yet.",
  },
  GATE_ALREADY_EXISTS: {
    title: "This experiment already has a gate",
    description: () =>
      "The page was working from a stale view of the gate. Refresh and try again — your saved gate is untouched.",
  },
};
