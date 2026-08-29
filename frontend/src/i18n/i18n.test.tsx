import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from './index';
import { render } from '../test/render';
import { LanguageSwitcher } from './LanguageSwitcher';
import { LocaleProvider } from './LocaleProvider';
import { useTranslation } from 'react-i18next';

function Probe() {
  const { t } = useTranslation();
  return <span>{t('nav.dashboard')}</span>;
}

describe('i18n', () => {
  it('configures en fallback and the en/de allowlist', () => {
    expect(i18n.options.fallbackLng).toContain('en');
    expect(i18n.options.supportedLngs).toEqual(expect.arrayContaining(['en', 'de']));
  });

  it('translates from the common namespace', async () => {
    await i18n.changeLanguage('en');
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>,
    );
    expect(await screen.findByText('Dashboard')).toBeInTheDocument();
  });

  it('switches language without reload, updates html lang, and translates', async () => {
    const user = userEvent.setup();
    render(
      <LocaleProvider>
        <LanguageSwitcher />
        <Probe />
      </LocaleProvider>,
    );

    const switcher = await screen.findByRole('combobox', { name: 'Language' });
    await user.click(switcher);
    const german = await screen.findByRole('option', { name: 'German' });
    await user.click(german);

    expect(await screen.findByText('Übersicht')).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('de');

    await i18n.changeLanguage('en');
  });
});
