import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from './auth.service';

// Every page except the auth pages sits behind this guard (rubric 1.2): signed-out users go to sign-in.
export const authGuard: CanActivateFn = async () => {
  const signedIn = await inject(AuthService).loadUser();
  return signedIn ? true : inject(Router).createUrlTree(['/sign-in']);
};

// The auth pages send users who are already signed in to the home page.
export const signedOutGuard: CanActivateFn = async () => {
  const signedIn = await inject(AuthService).loadUser();
  return signedIn ? inject(Router).createUrlTree(['/']) : true;
};
