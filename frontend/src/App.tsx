import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/notifications/styles.css';

import { Suspense } from 'react';
import { Center, Loader, MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { theme } from './app/theme';
import { AppRouter } from './app/router';
import { LocaleProvider } from './i18n/LocaleProvider';

export default function App() {
  return (
    <MantineProvider theme={theme} env={import.meta.env.VITEST ? 'test' : undefined}>
      <Notifications position="top-right" limit={5} />
      <LocaleProvider>
        <Suspense
          fallback={
            <Center h="100vh">
              <Loader />
            </Center>
          }
        >
          <AppRouter />
        </Suspense>
      </LocaleProvider>
    </MantineProvider>
  );
}
