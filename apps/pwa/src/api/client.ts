const fallback = 'http://localhost:3000';

export const API_BASE_URL = (import.meta as any).env?.VITE_API_BASE_URL || fallback;

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

  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

export const api = {
  requestOtp: (body: { email: string; timezone?: string }) =>
    request<{ ok: true }>('/auth/request-otp', { method: 'POST', body: JSON.stringify(body) }),
  verifyOtp: (body: { email: string; code: string }) =>
    request<{ accessToken: string; user: { id: string; email: string } }>('/auth/verify-otp', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  feed: (token: string, limit = 12) => request<{ cards: any[] }>(`/swipe/feed?limit=${limit}`, { token }),
  action: (token: string, body: { cardId: string; action: 'PICK_ONE' | 'PICK_TWO' | 'SKIP' }) =>
    request<{ ok: true }>('/swipe/action', { method: 'POST', token, body: JSON.stringify(body) }),

  slipCurrent: (token: string) => request<{ slip: any | null }>('/slip/current', { token }),
  slipAllocate: (token: string, body: { allocations: { slipItemId: string; credits: number }[] }) =>
    request<{ slip: any | null }>('/slip/allocate-credits', { method: 'POST', token, body: JSON.stringify(body) }),
};
