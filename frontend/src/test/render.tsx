import { render as testingLibraryRender, renderHook as testingLibraryRenderHook } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import type { RenderHookOptions, RenderOptions } from '@testing-library/react';
import { theme } from '../app/theme';

export function makeTestQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

type TestProvidersProps = { children: ReactNode; queryClient: QueryClient };

function TestProviders({ children, queryClient }: TestProvidersProps) {
  return (
    <QueryClientProvider client={queryClient}>
      <MantineProvider theme={theme} env="test">{children}</MantineProvider>
    </QueryClientProvider>
  );
}

export function render(ui: ReactNode, options?: Omit<RenderOptions, 'wrapper'> & {
  queryClient?: QueryClient;
}) {
  const { queryClient = makeTestQueryClient(), ...rest } = options ?? {};
  return testingLibraryRender(<>{ui}</>, {
    ...rest,
    wrapper: ({ children }: { children: ReactNode }) => (
      <TestProviders queryClient={queryClient}>{children}</TestProviders>
    ),
  });
}

export function renderHook<Result, Props>(
  hook: (initialProps: Props) => Result,
  options?: Omit<RenderHookOptions<Props>, 'wrapper'> & {
    queryClient?: QueryClient;
    initialProps?: Props;
  },
) {
  const { queryClient = makeTestQueryClient(), ...rest } = options ?? {};
  return testingLibraryRenderHook<Result, Props>(hook, {
    ...rest,
    wrapper: ({ children }: { children: ReactNode }) => (
      <TestProviders queryClient={queryClient}>{children}</TestProviders>
    ),
  });
}
