import { useState } from 'react';
import { SegmentedControl, Stack } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { ProvidersPage } from './ProvidersPage';
import { UsagePage } from './UsagePage';

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
          { value: 'usage', label: t('ai.section.usage') },
        ]}
      />
      {section === 'providers' ? <ProvidersPage /> : <UsagePage />}
    </Stack>
  );
}
