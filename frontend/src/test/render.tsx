import { render as testingLibraryRender } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import type { ReactNode } from 'react';
import type { RenderOptions } from '@testing-library/react';
import { theme } from '../app/theme';

export function render(ui: ReactNode, options?: RenderOptions) {
  const { wrapper: CustomWrapper, ...rest } = options ?? {};
  return testingLibraryRender(<>{ui}</>, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <MantineProvider theme={theme} env="test">
        {CustomWrapper ? <CustomWrapper>{children}</CustomWrapper> : children}
      </MantineProvider>
    ),
    ...rest,
  });
}
