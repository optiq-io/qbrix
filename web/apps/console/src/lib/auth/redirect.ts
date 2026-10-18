const HOME = "/";

// the app router navigates the window to anything absolute or
// protocol-relative, so only a path on this origin is ever followed
export function safeRedirect(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return HOME;
  if (value.includes("\\") || /[\u0000-\u001f\u007f]/.test(value)) return HOME;
  const origin =
    typeof window === "undefined" ? "http://localhost" : window.location.origin;
  try {
    const url = new URL(value, origin);
    if (url.origin !== origin) return HOME;
    return url.pathname + url.search + url.hash;
  } catch {
    return HOME;
  }
}

export function withRedirect(path: string, redirect: string): string {
  if (redirect === HOME) return path;
  const [pathname, search = ""] = path.split("?");
  const params = new URLSearchParams(search);
  params.set("redirect", redirect);
  return `${pathname}?${params}`;
}
