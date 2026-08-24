import { FormEvent, useEffect, useState } from 'react';
import { getCurrentUser, login, logout, recordInteraction, User } from './api';
import './App.css';

type AppState = 'loading' | 'login' | 'authenticated';

export default function App() {
  const [state, setState] = useState<AppState>('loading');
  const [user, setUser] = useState<User | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getCurrentUser()
      .then((currentUser) => {
        setUser(currentUser);
        setState('authenticated');
      })
      .catch(() => setState('login'));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const signedInUser = await login(username, password);
      setUser(signedInUser);
      setState('authenticated');
      setPassword('');
    } catch {
      setError('Unable to sign in. Check your credentials and try again.');
    } finally {
      setPending(false);
    }
  }

  async function signOut() {
    setPending(true);
    try {
      await logout();
      setUser(null);
      setState('login');
      setError(null);
    } catch {
      setError('Unable to sign out. Please try again.');
    } finally {
      setPending(false);
    }
  }

  async function interaction() {
    setPending(true);
    setError(null);
    try {
      await recordInteraction();
    } catch {
      setError('Unable to record interaction. Please try again.');
    } finally {
      setPending(false);
    }
  }

  if (state === 'loading') return <main className="app"><p role="status">Loading…</p></main>;

  if (state === 'login') {
    return (
      <main className="app">
        <section className="card" aria-labelledby="login-heading">
          <h1 id="login-heading">Sign in</h1>
          <p>Use your operator account to continue.</p>
          {error && <p className="error" role="alert">{error}</p>}
          <form onSubmit={submit}>
            <label htmlFor="username">Username</label>
            <input id="username" name="username" value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
            <label htmlFor="password">Password</label>
            <input id="password" name="password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
            <button type="submit" disabled={pending}>{pending ? 'Signing in…' : 'Sign in'}</button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="app">
      <section className="card" aria-labelledby="shell-heading">
        <h1 id="shell-heading">Authenticated shell</h1>
        <p>Signed in as {user?.username}</p>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="actions">
          <button type="button" onClick={interaction} disabled={pending}>Record interaction</button>
          <button type="button" onClick={signOut} disabled={pending}>Sign out</button>
        </div>
      </section>
    </main>
  );
}
