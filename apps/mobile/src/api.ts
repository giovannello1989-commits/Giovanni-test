import { Platform } from 'react-native';

const defaultAndroidLocalhost = 'http://10.0.2.2:3000';
const defaultIosLocalhost = 'http://localhost:3000';

export const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_URL || (Platform.OS === 'android' ? defaultAndroidLocalhost : defaultIosLocalhost);

export type ApiError = { message: string };

async function request<T>(path: string, options: RequestInit & { token?: string } = {}): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
      ...(options.headers ?? {}),
    },
  });

  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const json = (await res.json()) as any;
      msg = json?.message ?? msg;
    } catch {
      // ignore
    }
    throw new Error(msg);
  }

  // no-content
  if (res.status === 204) return undefined as unknown as T;

  return (await res.json()) as T;
}

export const api = {
  authRequestOtp: (body: { email: string; country?: string; timezone?: string }) =>
    request<{ ok: true }>('/auth/request-otp', { method: 'POST', body: JSON.stringify(body) }),
  authVerifyOtp: (body: { email: string; code: string }) =>
    request<{ accessToken: string; user: { id: string; email: string; timezone?: string | null; country?: string | null } }>(
      '/auth/verify-otp',
      { method: 'POST', body: JSON.stringify(body) },
    ),

  swipeFeed: (token: string, limit = 10) => request<{ cards: any[] }>(`/swipe/feed?limit=${limit}`, { token }),
  swipeAction: (token: string, body: { cardId: string; action: 'PICK_ONE' | 'PICK_TWO' | 'SKIP' }) =>
    request<{ ok: true }>('/swipe/action', { method: 'POST', token, body: JSON.stringify(body) }),

  slipCurrent: (token: string) => request<{ slip: any | null }>('/slip/current', { token }),
  slipAllocateCredits: (token: string, body: { allocations: { slipItemId: string; credits: number }[] }) =>
    request<{ slip: any | null }>('/slip/allocate-credits', { method: 'POST', token, body: JSON.stringify(body) }),
};
