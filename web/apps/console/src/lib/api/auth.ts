import { clearTokens, storeTokens } from "../auth/tokens";
import { apiFetch, buildQueryString } from "./client";
import type {
  AuthConfig,
  LoginRequest,
  LoginResponse,
  RegisterRequest,
  User,
  UpdateProfileRequest,
  ChangePasswordRequest,
  DeleteAccountRequest,
  Workspace,
  UpdateWorkspaceRequest,
  UserStats,
  APIKey,
  APIKeyCreateRequest,
  APIKeyCreateResponse,
  UpdateAPIKeyRequest,
  UpdateUserStatusRequest,
  UserListResponse,
  Invite,
  InviteCreateRequest,
  InviteListResponse,
  InviteAcceptRequest,
  InviteValidationResponse,
} from "./types";

export function redirectToLogin(): void {
  if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname + window.location.search)}`;
  }
}

export const auth = {
  async config(): Promise<AuthConfig> {
    return apiFetch<AuthConfig>("/auth/config");
  },

  async login(data: LoginRequest): Promise<LoginResponse> {
    const res = await apiFetch<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify(data),
    });
    storeTokens(res.access_token, res.refresh_token);
    return res;
  },

  async register(data: RegisterRequest): Promise<User> {
    return apiFetch<User>("/auth/register", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  async logout(): Promise<void> {
    clearTokens();
  },

  async profile(): Promise<User> {
    return apiFetch<User>("/auth/profile");
  },

  async updateProfile(data: UpdateProfileRequest): Promise<User> {
    return apiFetch<User>("/auth/profile", {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  async changePassword(data: ChangePasswordRequest): Promise<void> {
    return apiFetch<void>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  async deleteAccount(data: DeleteAccountRequest): Promise<void> {
    return apiFetch<void>("/auth/account", {
      method: "DELETE",
      body: JSON.stringify(data),
    });
  },

  async listApiKeys(): Promise<APIKey[]> {
    return apiFetch<APIKey[]>("/auth/api-keys");
  },

  async createApiKey(data: APIKeyCreateRequest): Promise<APIKeyCreateResponse> {
    return apiFetch<APIKeyCreateResponse>("/auth/api-keys", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  async updateApiKey(id: string, data: UpdateAPIKeyRequest): Promise<APIKey> {
    return apiFetch<APIKey>(`/auth/api-keys/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  async rotateApiKey(id: string): Promise<APIKeyCreateResponse> {
    return apiFetch<APIKeyCreateResponse>(`/auth/api-keys/${id}/rotate`, {
      method: "POST",
    });
  },

  async deleteApiKey(id: string): Promise<void> {
    return apiFetch<void>(`/auth/api-keys/${id}`, {
      method: "DELETE",
    });
  },

  async getWorkspace(): Promise<Workspace> {
    return apiFetch<Workspace>("/auth/workspace");
  },

  async updateWorkspace(data: UpdateWorkspaceRequest): Promise<Workspace> {
    return apiFetch<Workspace>("/auth/workspace", {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  async listMembers(params?: { limit?: number; offset?: number }): Promise<UserListResponse> {
    return apiFetch<UserListResponse>(`/auth/workspace/members${buildQueryString(params ?? {})}`);
  },

  async listUsers(params?: {
    search?: string;
    role?: string;
    status_filter?: string;
    limit?: number;
    offset?: number;
  }): Promise<UserListResponse> {
    return apiFetch<UserListResponse>(`/auth/users${buildQueryString(params ?? {})}`);
  },

  async updateUserRole(userId: string, role: string): Promise<{ message: string }> {
    return apiFetch<{ message: string }>(`/auth/users/${userId}/role`, {
      method: "PUT",
      body: JSON.stringify({ role }),
    });
  },

  async updateUserStatus(userId: string, data: UpdateUserStatusRequest): Promise<User> {
    return apiFetch<User>(`/auth/users/${userId}/status`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  async getUserStats(): Promise<UserStats> {
    return apiFetch<UserStats>("/auth/users/stats");
  },

  // invite methods

  async createInvite(data: InviteCreateRequest): Promise<Invite> {
    return apiFetch<Invite>("/auth/workspace/invites", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  async listInvites(params?: {
    invite_status?: string;
    limit?: number;
    offset?: number;
  }): Promise<InviteListResponse> {
    return apiFetch<InviteListResponse>(
      `/auth/workspace/invites${buildQueryString(params ?? {})}`
    );
  },

  async revokeInvite(id: string): Promise<void> {
    return apiFetch<void>(`/auth/workspace/invites/${id}`, {
      method: "DELETE",
    });
  },

  async validateInvite(token: string): Promise<InviteValidationResponse> {
    return apiFetch<InviteValidationResponse>(`/auth/invites/${token}`);
  },

  async acceptInvite(token: string, data: InviteAcceptRequest): Promise<User> {
    return apiFetch<User>(`/auth/invites/${token}/accept`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  async forgotPassword(email: string): Promise<{ message: string }> {
    return apiFetch<{ message: string }>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  },

  async resetPassword(token: string, newPassword: string): Promise<{ message: string }> {
    return apiFetch<{ message: string }>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, new_password: newPassword }),
    });
  },

  async verifyEmail(token: string): Promise<{ message: string }> {
    return apiFetch<{ message: string }>("/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
  },

  async resendVerification(email: string): Promise<{ message: string }> {
    return apiFetch<{ message: string }>("/auth/resend-verification", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  },
};
