import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClient} from '@tanstack/react-query';
import i18n from '../../../i18n';
import { render } from '../../../test/render';
import { stubFetch } from '../../../test/fetch';
import { PromptLibraryPage } from './PromptLibraryPage';
import { TemplateEditor } from './TemplateEditor';
import { HighlightedTextarea } from './HighlightedTextarea';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const templates = [
  {
    id: 1, task_type: 'policy_check', client_id: null, version: 1, name: 'Default',
    system_prompt: 'Check {{title}}.', user_prompt: '{{title}} {{description}}',
    variables: ['title', 'description'], is_active: true, created_at: '2026-09-11T10:00:00Z',
    created_by: 'operator',
  },
  {
    id: 2, task_type: 'policy_check', client_id: null, version: 2, name: 'Stricter',
    system_prompt: 'Strictly check {{title}}.', user_prompt: '{{title}} {{description}}',
    variables: ['title', 'description'], is_active: false, created_at: '2026-09-11T11:00:00Z',
    created_by: 'operator',
  },
];

beforeAll(async () => {
  await i18n.loadNamespaces('admin');
});

beforeEach(() => {
  stubFetch((url) => {
    if (url === '/admin/ai/prompt-templates') return jsonResponse(templates);
    if (url === '/clients') return jsonResponse([]);
    return jsonResponse({});
  });
});


describe('PromptLibraryPage', () => {
  it('groups versions by task type with active badge and activate button', async () => {
    render(<PromptLibraryPage />);
    expect(await screen.findByTestId('template-group-policy_check')).toBeInTheDocument();
    expect(screen.getByText('Default')).toBeInTheDocument();
    expect(screen.getByText('Stricter')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
    expect(screen.getByText('Activate')).toBeInTheDocument();
    expect(screen.queryByTestId('template-row-1')?.textContent).not.toContain('Activate');
  });
});

describe('TemplateEditor warnings', () => {
  it('warns when a declared variable is missing from the template text', async () => {
    const user = userEvent.setup();
    render(
      <TemplateEditor
        opened
        template={null}
        clientId={null}
        feedOptions={[]}
        onClose={() => {}}
      />,
    );
    await user.click(screen.getByRole('combobox', { name: /task type/i }));
    await user.click(screen.getByRole('option', { name: 'title_optimization' }));
    const [systemInput] = screen
      .getAllByRole('textbox')
      .filter((el) => (el as HTMLTextAreaElement).value === '');
    await user.type(systemInput, 'Rewrite {{title}}');
    const variablesInput = screen.getByRole('textbox', { name: /variables/i });
    await user.type(variablesInput, 'brand, title');
    expect(await screen.findByTestId('unused-variable-brand')).toBeInTheDocument();
  });

  it('shows a malformed-brace warning for {{Title}}', async () => {
    const user = userEvent.setup();
    render(
      <TemplateEditor
        opened
        template={null}
        clientId={null}
        feedOptions={[]}
        onClose={() => {}}
      />,
    );
    const [, userInput] = screen
      .getAllByRole('textbox')
      .filter((el) => (el as HTMLTextAreaElement).value === '');
    await user.type(userInput, 'Check {{{{Title}}}}');
    expect(screen.getByTestId('malformed-brace-{{Title}}')).toBeInTheDocument();
  });
});

describe('HighlightedTextarea', () => {
  it('marks placeholders: yellow for known, red for unknown', () => {
    const { container } = render(
      <HighlightedTextarea
        label="System prompt"
        value="Check {{title}} and {{secret}}"
        onChange={() => {}}
        known={new Set(['title'])}
      />,
    );
    const marks = container.querySelectorAll('mark');
    expect(marks).toHaveLength(2);
    expect(marks[0].textContent).toBe('{{title}}');
    expect(marks[0].style.background).toContain('yellow');
    expect(marks[1].textContent).toBe('{{secret}}');
    expect(marks[1].style.background).toContain('red');
  });
});
