import { Routes } from '@angular/router';

import { authGuard, signedOutGuard } from './auth/auth.guard';
import { ForgotPassword } from './pages/auth/forgot-password/forgot-password';
import { SignIn } from './pages/auth/sign-in/sign-in';
import { SignUp } from './pages/auth/sign-up/sign-up';
import { Home } from './pages/home/home';
import { Placeholder } from './placeholder';

// The pages in the shell's navigation. Paths are the page folders under pages/; when a page is
// ready, its owner swaps Placeholder for their component here.
export const pages: Routes = [
  { path: 'upload', title: 'Upload', component: Placeholder, data: { title: 'Upload', owner: 2 } },
  { path: 'search', title: 'Search', component: Placeholder, data: { title: 'Search', owner: 4 } },
  { path: 'query-by-file', title: 'Search by file', component: Placeholder, data: { title: 'Search by file', owner: 3 } },
  { path: 'lost-pet', title: 'Lost pet', component: Placeholder, data: { title: 'Lost pet', owner: 3 } },
  { path: 'tags', title: 'Manage tags', component: Placeholder, data: { title: 'Manage tags', owner: 4 } },
  // Lazy-loaded, so the AWS SDK only downloads when someone opens Chat.
  { path: 'chat', title: 'Chat', loadComponent: () => import('./pages/chat/chat').then((m) => m.Chat) },
  { path: 'notifications', title: 'Alerts', component: Placeholder, data: { title: 'Alerts', owner: 1 } },
];

export const routes: Routes = [
  { path: 'sign-in', component: SignIn, canActivate: [signedOutGuard] },
  { path: 'sign-up', component: SignUp, canActivate: [signedOutGuard] },
  { path: 'forgot-password', component: ForgotPassword, canActivate: [signedOutGuard] },
  // Every other page goes in `children`, so the guard covers it without each page adding it (rubric 1.2).
  {
    path: '',
    canActivateChild: [authGuard],
    children: [{ path: '', component: Home }, ...pages],
  },
  { path: '**', redirectTo: '' },
];
