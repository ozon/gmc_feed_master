import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { render } from '../../test/render';
import { ChartCard } from './ChartCard';

describe('ChartCard', () => {
  it('renders title and children when data present', () => {
    render(
      <ChartCard title="Pipeline health" isEmpty={false}>
        <div>chart-mock</div>
      </ChartCard>,
    );
    expect(screen.getByText('Pipeline health')).toBeInTheDocument();
    expect(screen.getByText('chart-mock')).toBeInTheDocument();
  });

  it('renders empty state instead of children when isEmpty', () => {
    render(
      <ChartCard title="Pipeline health" isEmpty emptyMessage="No runs yet">
        <div>chart-mock</div>
      </ChartCard>,
    );
    expect(screen.getByText('No runs yet')).toBeInTheDocument();
    expect(screen.queryByText('chart-mock')).not.toBeInTheDocument();
  });
});
