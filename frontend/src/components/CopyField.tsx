import { ActionIcon, CopyButton, Group, TextInput, Tooltip } from '@mantine/core';
import { IconCheck, IconCopy } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

export function CopyField({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation();
  return (
    <Group gap="xs" wrap="nowrap">
      <TextInput readOnly value={value} label={label} style={{ flex: 1 }} />
      <CopyButton value={value}>
        {({ copied, copy }) => (
          <Tooltip label={copied ? t('actions.copied') : t('actions.copy')}>
            <ActionIcon
              variant="default"
              onClick={copy}
              aria-label={copied ? t('actions.copied') : t('actions.copy')}
              color={copied ? 'teal' : undefined}
            >
              {copied ? <IconCheck size={16} /> : <IconCopy size={16} />}
            </ActionIcon>
          </Tooltip>
        )}
      </CopyButton>
    </Group>
  );
}
