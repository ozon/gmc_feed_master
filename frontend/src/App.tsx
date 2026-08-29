import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/notifications/styles.css';

import { Center, MantineProvider, Text } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { theme } from './app/theme';

export default function App() {
  return (
    <MantineProvider theme={theme}>
      <Notifications position="top-right" limit={5} />
      <Center h="100vh">
        <Text>GMC Feed Master</Text>
      </Center>
    </MantineProvider>
  );
}
