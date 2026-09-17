import { Component, type ReactNode } from 'react';
import { Alert, Button, Stack, Text } from '@mantine/core';
import { captureException } from '../logging/logger';

type Props = { children: ReactNode };
type State = { error: Error | null };

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error): void {
    captureException(error, { scope: 'boundary' });
  }

  render() {
    if (this.state.error !== null) {
      return (
        <Alert color="red" title="Something went wrong" m="md">
          <Stack gap="xs" mt={4}>
            <Text size="sm" c="dimmed">
              An unexpected error occurred. The error has been reported.
            </Text>
            <div>
              <Button size="xs" onClick={() => this.setState({ error: null })}>
                Reload view
              </Button>
            </div>
          </Stack>
        </Alert>
      );
    }
    return this.props.children;
  }
}
