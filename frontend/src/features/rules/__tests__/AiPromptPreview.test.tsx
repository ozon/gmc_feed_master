import { beforeAll, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import { AiPromptPreview } from '../AiPromptPreview';

beforeAll(async () => {
  await i18n.loadNamespaces(['rules', 'common']);
});

it('renders messages and warnings', async () => {
  stubFetch(
    () =>
      new Response(
        JSON.stringify({
          messages: [
            { role: 'system', content: 'sys' },
            { role: 'user', content: 'Hello Red Socks' },
          ],
          used_variables: ['title'],
          warnings: ["variable 'color' is missing in the sample product; rendered empty"],
          errors: [],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
  );
  render(
    <AiPromptPreview
      opened
      onClose={() => {}}
      payload={{ feed_source_id: 1, taskType: 'rule_value', system: 's', user: 'u', variables: [] }}
    />,
  );
  expect(await screen.findByText(/Hello Red Socks/)).toBeInTheDocument();
  expect(await screen.findByText(/color/)).toBeInTheDocument();
});
