import { Stack, Tabs, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router';
import { AiAdminPage } from './ai/AiAdminPage';
import { AdminClientsPage } from './AdminClientsPage';
import { AdminSettingsPage } from './AdminSettingsPage';
import { AdminUsersPage } from './AdminUsersPage';

const TAB_VALUES = ['users', 'clients', 'settings', 'ai'] as const;
type AdminTab = (typeof TAB_VALUES)[number];

function tabFromPathname(pathname: string): AdminTab {
  const segment = pathname.split('/')[2];
  return (TAB_VALUES as readonly string[]).includes(segment ?? '')
    ? (segment as AdminTab)
    : 'users';
}

export function AdminPage() {
  const { t } = useTranslation('admin');
  const { t: tCommon } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const tab = tabFromPathname(location.pathname);

  return (
    <Stack>
      <Title order={3}>{tCommon('nav.adminSection')}</Title>
      <Tabs
        value={tab}
        onChange={(value) => {
          if (value) void navigate(`/admin/${value}`);
        }}
        keepMounted={false}
      >
        <Tabs.List>
          <Tabs.Tab value="users">{t('tabs.users')}</Tabs.Tab>
          <Tabs.Tab value="clients">{t('tabs.clients')}</Tabs.Tab>
          <Tabs.Tab value="settings">{t('tabs.settings')}</Tabs.Tab>
          <Tabs.Tab value="ai">{t('tabs.ai')}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="users" pt="md">
          <AdminUsersPage />
        </Tabs.Panel>
        <Tabs.Panel value="clients" pt="md">
          <AdminClientsPage />
        </Tabs.Panel>
        <Tabs.Panel value="settings" pt="md">
          <AdminSettingsPage />
        </Tabs.Panel>
        <Tabs.Panel value="ai" pt="md">
          <AiAdminPage />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
