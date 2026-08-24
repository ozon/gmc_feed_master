import { render, screen } from '@testing-library/react';
import App from './App';

it('renders the frontend smoke screen', () => {
  render(<App />);
  expect(screen.getByText('M0')).toBeInTheDocument();
});
