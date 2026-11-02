import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from './auth.service';

// inject() only works before the first `await`, so each guard gets its services first.

// Every page except the auth pages sits behind this guard (rubric 1.2). Signed-out users go to
// sign-up, as the spec asks; it links to sign-in for people who already have an account.
export const authGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  return (await auth.loadUser()) ? true : router.createUrlTree(['/sign-up']);
};

// The auth pages send users who are already signed in to the home page.
export const signedOutGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  return (await auth.loadUser()) ? router.createUrlTree(['/']) : true;
};
