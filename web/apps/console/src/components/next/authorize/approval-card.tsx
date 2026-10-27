import type { ConnectionRequest, User } from "@/lib/api/types";
import { Autonomy } from "./autonomy";
import { AuthorizeFrame, AuthorizeTitle } from "./frame";

function webUri(uri: string | null): string | null {
  if (!uri) return null;
  try {
    const { protocol } = new URL(uri);
    return protocol === "https:" || protocol === "http:" ? uri : null;
  } catch {
    return null;
  }
}

export function ApprovalCard({
  request,
  workspace,
  role,
  pending,
  onDecide,
}: {
  request: ConnectionRequest;
  workspace: string;
  role: User["role"];
  pending: boolean;
  onDecide: (approve: boolean) => void;
}) {
  const client = request.client.name;
  const person = request.acts_for.name;
  const uri = webUri(request.client.uri);
  const viewer = role === "viewer";

  return (
    <AuthorizeFrame
      workspace={workspace}
      footnote={`After connecting, go back to ${client}. This tab can be closed.`}
    >
      <div className="flex flex-col gap-1.5">
        <AuthorizeTitle>
          {uri ? (
            <a href={uri} target="_blank" rel="noopener noreferrer" className="hover:underline">
              {client}
            </a>
          ) : (
            client
          )}{" "}
          wants to act for you in {workspace}
        </AuthorizeTitle>
        <div className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="flex size-4 items-center justify-center rounded-full bg-n-viz-3 text-[9px] font-medium text-n-text-1"
          >
            {person.charAt(0).toUpperCase()}
          </span>
          <span className="n-meta text-n-text-2">
            Signed in as {person} · {role}
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <p className="n-body text-n-text-2">
          {viewer
            ? "It can read what you can read as a viewer, and can't make changes."
            : `It can do what you can do as ${role === "admin" ? "an" : "a"} ${role}, never more, and every change it makes shows as ${person} via ${client}.`}
        </p>
        {request.client.registered_by_itself && (
          <p className="n-meta text-n-text-3">
            {client} registered itself, so its name is the one it gave.
          </p>
        )}
      </div>

      {!viewer && <Autonomy request={request} />}

      <p className="n-meta text-n-text-3">
        Revoke it any time in Connections, without signing out anywhere else. Access renews on its
        own while you use it, and ends after 90 days unused.
      </p>

      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={pending}
          onClick={() => onDecide(true)}
          className="n-body rounded-n-control bg-n-ink px-3.5 py-2 font-semibold text-n-on-ink disabled:opacity-60"
        >
          Connect {client}
        </button>
        <button
          type="button"
          disabled={pending}
          onClick={() => onDecide(false)}
          className="n-body rounded-n-control px-2.5 py-2 font-medium text-n-text-3 hover:text-n-text-1 disabled:opacity-60"
        >
          Cancel
        </button>
      </div>
    </AuthorizeFrame>
  );
}
