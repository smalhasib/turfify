import axios, { type AxiosInstance } from "axios";

import { useAuthStore } from "@/lib/authStore";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8800/v1";

export type HealthCheckResponse = {
  status: string;
  checks: {
    db: string;
    redis: string;
    version: string;
  };
};

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
};

export async function fetchHealth(): Promise<HealthCheckResponse> {
  const res = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Health check failed: ${res.status}`);
  }
  return res.json();
}

let _client: AxiosInstance | null = null;
let _refreshing: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (_refreshing) return _refreshing;

  _refreshing = (async () => {
    const refresh = useAuthStore.getState().refreshToken;
    if (!refresh) return null;
    try {
      const { data } = await axios.post<TokenPair>(`${API_BASE_URL}/auth/refresh`, {
        refresh_token: refresh,
      });
      useAuthStore.getState().setTokens(data.access_token, data.refresh_token);
      return data.access_token;
    } catch {
      useAuthStore.getState().clear();
      return null;
    } finally {
      _refreshing = null;
    }
  })();

  return _refreshing;
}

export function getApiClient(): AxiosInstance {
  if (_client) return _client;
  _client = axios.create({ baseURL: API_BASE_URL });

  _client.interceptors.request.use((config) => {
    const access = useAuthStore.getState().accessToken;
    if (access) {
      config.headers.Authorization = `Bearer ${access}`;
    }
    return config;
  });

  _client.interceptors.response.use(
    (resp) => resp,
    async (error) => {
      const original = error.config;
      if (
        error.response?.status === 401 &&
        original &&
        !original._retry &&
        useAuthStore.getState().refreshToken
      ) {
        original._retry = true;
        const newAccess = await refreshAccessToken();
        if (newAccess) {
          original.headers.Authorization = `Bearer ${newAccess}`;
          return _client!.request(original);
        }
      }
      return Promise.reject(error);
    },
  );

  return _client;
}
