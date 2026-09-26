// the shell itself is `components/auth/auth-shell.tsx`, composed per page:
// sign in and register pass a showcase, the rest render the form column alone.
export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <div className="bg-bg">{children}</div>;
}
