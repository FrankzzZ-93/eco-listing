import client from './client';
import type { AccountStatus } from '../types/settings';

export async function getAccountStatus(probe = false): Promise<AccountStatus> {
  const res = await client.get<AccountStatus>(`/account/status${probe ? '?probe=true' : ''}`);
  return res.data;
}

export async function startAccountLogin(): Promise<AccountStatus> {
  const res = await client.post<AccountStatus>('/account/login');
  return res.data;
}

// User finished signing in manually in the real-Chrome window — re-check it.
export async function confirmAccountLogin(): Promise<AccountStatus> {
  const res = await client.post<AccountStatus>('/account/confirm');
  return res.data;
}

export async function accountLogout(): Promise<AccountStatus> {
  const res = await client.post<AccountStatus>('/account/logout');
  return res.data;
}
