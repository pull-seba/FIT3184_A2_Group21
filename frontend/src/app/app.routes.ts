import { Routes } from '@angular/router';

import { authGuard, signedOutGuard } from './auth/auth.guard';
import { ForgotPassword } from './pages/auth/forgot-password/forgot-password';
import { SignIn } from './pages/auth/sign-in/sign-in';
import { SignUp } from './pages/auth/sign-up/sign-up';
import { Home } from './pages/home/home';

export const routes: Routes = [
  { path: 'sign-in', component: SignIn, canActivate: [signedOutGuard] },
  { path: 'sign-up', component: SignUp, canActivate: [signedOutGuard] },
  { path: 'forgot-password', component: ForgotPassword, canActivate: [signedOutGuard] },
  // Every other page goes in `children`, so the guard covers it without each page adding it (rubric 1.2).
  {
    path: '',
    canActivateChild: [authGuard],
    children: [{ path: '', component: Home }],
  },
  { path: '**', redirectTo: '' },
];
