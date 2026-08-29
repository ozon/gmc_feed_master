import { describe, expect, it } from 'vitest';
import { theme } from './theme';
import { render } from '../test/render';
import { Button } from '@mantine/core';
import { screen } from '@testing-library/react';

describe('theme', () => {
  it('uses blue as the primary color', () => {
    expect(theme.primaryColor).toBe('blue');
  });

  it('renders Mantine children inside the provider', () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument();
  });
});
