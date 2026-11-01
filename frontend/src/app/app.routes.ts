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
  // Loaded on first visit, so the gallery's Material components stay out of the initial bundle.
  {
    path: 'upload',
    title: 'Upload',
    loadComponent: () => import('./pages/upload/upload').then((m) => m.Upload),
  },
  { path: 'search', title: 'Search', component: Placeholder, data: { title: 'Search', owner: 4 } },
  {
    path: 'query-by-file',
    title: 'Search by file',
    loadComponent: () => import('./pages/query-by-file/query-by-file').then((m) => m.QueryByFile),
  },
  {
    path: 'lost-pet',
    title: 'Lost pet',
    loadComponent: () => import('./pages/lost-pet/lost-pet').then((m) => m.LostPet),
  },
  { path: 'tags', title: 'Manage tags', component: Placeholder, data: { title: 'Manage tags', owner: 4 } },
  // Lazy-loaded, so the AWS SDK only downloads when someone opens Chat.
  { path: 'chat', title: 'Chat', loadComponent: () => import('./pages/chat/chat').then((m) => m.Chat) },
  {
    path: 'notifications',
    title: 'Alerts',
    loadComponent: () => import('./pages/notifications/notifications').then((m) => m.Notifications),
  },
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
