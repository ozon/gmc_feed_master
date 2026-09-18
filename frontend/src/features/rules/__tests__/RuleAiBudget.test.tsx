import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { queryKeys } from '../../../api/queryKeys';
import { RuleAiBudget } from '../RuleAiBudget';

beforeAll(async () => {
  await i18n.loadNamespaces(['rules']);
});

describe('RuleAiBudget', () => {
  it('initializes budget values from a warm query cache on first render', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    queryClient.setQueryData(queryKeys.feedSource(7).detail, {
      id: 7,
      configuration: { ai_rules: { enabled: true, limit: 91, budget: 92 } },
    });

    render(<RuleAiBudget feedSourceId={7} />, { queryClient });

    expect(screen.getByLabelText('Enable AI rule actions')).toBeChecked();
    expect(screen.getByLabelText('Max products per run')).toHaveValue('91');
    expect(screen.getByLabelText('Max AI calls per run')).toHaveValue('92');
  });
});
