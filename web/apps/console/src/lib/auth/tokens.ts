const TOKEN_MAX_AGE = 7 * 24 * 60 * 60; // 7 days

export function storeTokens(accessToken: string, refreshToken: string): void {
  if (typeof document === "undefined") return;
  document.cookie = `access_token=${accessToken}; path=/; max-age=${TOKEN_MAX_AGE}; SameSite=Lax`;
  document.cookie = `refresh_token=${refreshToken}; path=/; max-age=${TOKEN_MAX_AGE}; SameSite=Lax`;
}

export function clearTokens(): void {
  if (typeof document === "undefined") return;
  document.cookie = "access_token=; path=/; max-age=0";
  document.cookie = "refresh_token=; path=/; max-age=0";
}

export function getAccessToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/access_token=([^;]+)/);
  return match ? match[1] : null;
}

export function getRefreshToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/refresh_token=([^;]+)/);
  return match ? match[1] : null;
}
