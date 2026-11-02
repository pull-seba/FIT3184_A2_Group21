import { Component, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { LexRuntimeV2Client, Message, RecognizeTextCommand } from '@aws-sdk/client-lex-runtime-v2';
// Not @aws-sdk/credential-providers, whose Node-only providers break Angular's browser build.
import { fromCognitoIdentityPool } from '@aws-sdk/credential-provider-cognito-identity';

import { AuthService } from '../../auth/auth.service';
import { environment } from '../../../environments/environment';

// The bot in aws/lex (stack ecoguard-chat). Public IDs, like those in environment.ts.
const region = 'us-east-1';
const bot = { botId: '7KZX2N302L', botAliasId: 'TSTALIASID', localeId: 'en_AU' };

interface Line {
  from: 'you' | 'bot';
  text: string;
  url?: string;
}

class SignedOut extends Error {}

@Component({
  selector: 'app-chat',
  imports: [MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule],
  templateUrl: './chat.html',
  styleUrl: './chat.css',
})
export class Chat {
  private readonly auth = inject(AuthService);

  // The identity pool swaps the user's ID token for short-lived credentials that may only call
  // this bot (aws/iam/chat-widget.json), so the app ships no AWS keys.
  private readonly lex = new LexRuntimeV2Client({
    region,
    credentials: fromCognitoIdentityPool({
      identityPoolId: environment.identityPoolId,
      logins: {
        [`cognito-idp.${region}.amazonaws.com/${environment.userPoolId}`]: () => this.idToken(),
      },
    }),
  });

  readonly lines = signal<Line[]>([]);
  readonly pending = signal(false);

  async send(box: HTMLInputElement): Promise<void> {
    const text = box.value.trim();
    if (!text || this.pending()) return;
    box.value = '';
    this.add({ from: 'you', text });
    this.pending.set(true);
    try {
      const reply = await this.lex.send(
        new RecognizeTextCommand({
          ...bot,
          // One session per user, so a follow-up like "rabbits" answers Lex's last question.
          sessionId: this.auth.user()?.sub,
          text,
          // The fulfilment Lambda forwards this to the gateway. Request attributes last one turn,
          // so Lex never stores the token.
          requestAttributes: { idToken: await this.idToken() },
        }),
      );
      this.add(...botLines(reply.messages));
    } catch (error) {
      this.add({ from: 'bot', text: problem(error) });
    } finally {
      this.pending.set(false);
    }
  }

  private add(...lines: Line[]): void {
    this.lines.update((all) => [...all, ...lines]);
  }

  private async idToken(): Promise<string> {
    const token = await this.auth.getIdToken();
    if (!token) throw new SignedOut();
    return token;
  }
}

// Lex replies with sentences, then one CustomPayload {"label", "url"} per search result
// (aws/lex/README.md, "Replies"). Anything else is skipped, so an odd reply can't break the page.
function botLines(messages: Message[] = []): Line[] {
  const lines: Line[] = [];
  for (const { contentType, content = '' } of messages) {
    if (contentType === 'PlainText' && content) lines.push({ from: 'bot', text: content });
    if (contentType === 'CustomPayload') lines.push(...link(content));
  }
  return lines.length
    ? lines
    : [{ from: 'bot', text: "Sorry, I didn't catch that. Try asking another way." }];
}

function link(content: string): Line[] {
  try {
    const { label, url } = JSON.parse(content);
    if (typeof label === 'string' && typeof url === 'string' && url.startsWith('https://')) {
      return [{ from: 'bot', text: label, url }];
    }
  } catch {}
  return [];
}

// The SDK has already retried throttling and dropped connections by now.
function problem(error: unknown): string {
  const name = error instanceof Error ? error.name : '';
  if (name === 'AccessDeniedException') {
    return "The chatbot isn't available right now. Please try again later.";
  }
  // Lex calls it ThrottlingException, Cognito TooManyRequestsException.
  if (name === 'ThrottlingException' || name === 'TooManyRequestsException') {
    return 'Too many messages at once. Wait a moment, then try again.';
  }
  if (error instanceof SignedOut || name === 'NotAuthorizedException') {
    return 'Your sign-in has expired. Please sign in again.';
  }
  // fetch rejects with a TypeError when the network is down.
  if (error instanceof TypeError) {
    return "I can't reach the chatbot. Check your internet connection, then try again.";
  }
  return 'Sorry, something went wrong. Please try again.';
}
