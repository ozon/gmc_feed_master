import { Button, Center, Loader, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export function LoadingState() {
  const { t } = useTranslation();
  return (
    <Center py="xl">
      <Loader role="progressbar" aria-label={t('state.loading')} />
    </Center>
  );
}

export function EmptyState({ message }: { message?: string }) {
  const { t } = useTranslation();
  return (
    <Center py="xl">
      <Text c="dimmed">{message ?? t('state.empty')}</Text>
    </Center>
  );
}

export function ErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <Center py="xl">
      <Stack align="center" gap="sm">
        <Text c="red" role="alert">
          {message ?? t('state.error')}
        </Text>
        {onRetry ? (
          <Button variant="light" onClick={onRetry}>
            {t('actions.retry')}
          </Button>
        ) : null}
      </Stack>
    </Center>
  );
}
