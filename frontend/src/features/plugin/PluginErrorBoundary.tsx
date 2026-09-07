import { Component, type ReactNode } from 'react';
import { Alert, Button, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

function PluginErrorFallback({
  pluginName,
  message,
  onRetry,
}: {
  pluginName: string;
  message?: string;
  onRetry: () => void;
}) {
  const { t } = useTranslation('plugins');
  return (
    <Alert color="red" title={t('errorBoundary.title')} data-testid="plugin-error-boundary">
      <Stack gap="xs" mt={4}>
        <Text size="sm" fw={600}>{pluginName}</Text>
        {message ? <Text size="sm" c="dimmed">{message}</Text> : null}
        <div>
          <Button size="xs" variant="light" onClick={onRetry} data-testid="plugin-error-retry">
            {t('errorBoundary.retry')}
          </Button>
        </div>
      </Stack>
    </Alert>
  );
}

type Props = { pluginName: string; children: ReactNode };
type State = { error: Error | null };

export class PluginErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    const { error } = this.state;
    if (error !== null) {
      return (
        <PluginErrorFallback
          pluginName={this.props.pluginName}
          message={error.message}
          onRetry={() => this.setState({ error: null })}
        />
      );
    }
    return this.props.children;
  }
}
