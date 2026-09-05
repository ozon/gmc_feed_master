import { beforeAll, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import i18n from '../../i18n';
import { render } from '../../test/render';
import { PipelineOverviewStrip } from './PipelineOverviewStrip';
import type { LocalInstance } from './dndUtils';

beforeAll(async () => {
  await i18n.loadNamespaces(['pipeline', 'common']);
});

const instances: LocalInstance[] = [
  { id: 1, position: 0, plugin_id: 'upper', name: 'Upper', configuration: {}, enabled: true, clientId: 'upper-0' },
  { id: 2, position: 1, plugin_id: 'lower', name: 'Lower', configuration: {}, enabled: false, clientId: 'lower-1' },
];

describe('PipelineOverviewStrip', () => {
  it('shows total, enabled and disabled counts', () => {
    render(<PipelineOverviewStrip instances={instances} dirty={false} />);
    expect(screen.getByTestId('overview-strip')).toBeInTheDocument();
    expect(screen.getByText(/^2 instances$/i)).toBeInTheDocument();
    expect(screen.getByText(/^1 enabled$/i)).toBeInTheDocument();
    expect(screen.getByText(/^1 disabled$/i)).toBeInTheDocument();
  });

  it('shows a dirty badge when dirty', () => {
    render(<PipelineOverviewStrip instances={instances} dirty={true} />);
    expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();
  });
});
