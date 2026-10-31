import { inject, Injectable } from '@angular/core';
import { Router } from '@angular/router';

import { AuthService } from '../auth/auth.service';
import { environment } from '../../environments/environment';

// The error shape every route returns (docs/contracts/api-routes.md, "Errors").
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

type Query = Record<string, string | number | undefined>;

// Every call to the gateway goes through here (rubric 1.2).
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  get<T>(path: string, query?: Query): Promise<T> {
    return this.request<T>('GET', path, undefined, query);
  }

  post<T>(path: string, body: unknown, query?: Query): Promise<T> {
    return this.request<T>('POST', path, body, query);
  }

  put<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>('PUT', path, body);
  }

  private async request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
    const token = await this.auth.getIdToken();
    if (!token) return this.signedOut();

    const response = await fetch(this.url(path, query), {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    if (response.status === 401) return this.signedOut();
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const error = data?.error;
      throw new ApiError(response.status, error?.code ?? 'error', error?.message ?? `Request failed (${response.status})`);
    }
    return data as T;
  }

  private url(path: string, query?: Query): string {
    const url = new URL(environment.apiBase + path);
    for (const [name, value] of Object.entries(query ?? {})) {
      if (value !== undefined) url.searchParams.set(name, String(value));
    }
    return url.toString();
  }

  private async signedOut(): Promise<never> {
    await this.auth.signOut();
    await this.router.navigateByUrl('/sign-in');
    throw new ApiError(401, 'unauthenticated', 'Your session has ended. Please sign in again.');
  }
}
