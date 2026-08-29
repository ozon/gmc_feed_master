import { useState, type FormEvent } from 'react';
import { Button, Center, Paper, PasswordInput, Stack, Text, TextInput, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router';
import { login } from '../../api/client';
import { queryClient } from '../../api/queryClient';
import { queryKeys } from '../../api/queryKeys';

export function LoginPage() {
  const { t } = useTranslation('auth');
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await login(username, password);
      await queryClient.invalidateQueries({ queryKey: queryKeys.session });
      const from = (location.state as { from?: string } | null)?.from ?? '/';
      navigate(from, { replace: true });
    } catch {
      setError(t('login.error'));
    } finally {
      setPending(false);
    }
  }

  return (
    <Center h="100vh">
      <Paper withBorder p="xl" radius="md" w={360}>
        <Stack component="form" onSubmit={submit} gap="md">
          <div>
            <Title order={3}>{t('login.title')}</Title>
            <Text c="dimmed" size="sm">
              {t('login.subtitle')}
            </Text>
          </div>
          {error ? (
            <Text c="red" size="sm" role="alert">
              {error}
            </Text>
          ) : null}
          <TextInput
            label={t('login.username')}
            value={username}
            onChange={(event) => setUsername(event.currentTarget.value)}
            autoComplete="username"
            required
          />
          <PasswordInput
            label={t('login.password')}
            value={password}
            onChange={(event) => setPassword(event.currentTarget.value)}
            autoComplete="current-password"
            required
          />
          <Button type="submit" loading={pending}>
            {pending ? t('login.submitting') : t('login.submit')}
          </Button>
        </Stack>
      </Paper>
    </Center>
  );
}
