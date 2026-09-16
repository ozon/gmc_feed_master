import { useState } from 'react';
import { SegmentedControl, Stack } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { ProvidersPage } from './ProvidersPage';
import { AiSettingsPage } from './AiSettingsPage';
import { UsagePage } from './UsagePage';
import { PromptLibraryPage } from '../promptLibrary/PromptLibraryPage';

export function AiAdminPage() {
  const { t } = useTranslation('admin');
  const [section, setSection] = useState('providers');
  return (
    <Stack gap="md">
      <SegmentedControl
        value={section}
        onChange={setSection}
        data={[
          { value: 'providers', label: t('ai.section.providers') },
          { value: 'settings', label: t('ai.section.settings') },
          { value: 'templates', label: t('ai.section.templates') },
          { value: 'usage', label: t('ai.section.usage') },
        ]}
      />
      {section === 'providers' ? (
        <ProvidersPage />
      ) : section === 'settings' ? (
        <AiSettingsPage />
      ) : section === 'templates' ? (
        <PromptLibraryPage />
      ) : (
        <UsagePage />
      )}
    </Stack>
  );
}
