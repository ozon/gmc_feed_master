import { Tabs } from '@mantine/core';
import { Link, Outlet, useLocation, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';

const TABS = [
  { value: 'runs', path: 'runs', labelKey: 'tabs.runs' },
  { value: 'findings', path: 'findings', labelKey: 'tabs.findings' },
  { value: 'dryRun', path: 'dry-run', labelKey: 'tabs.dryRun' },
] as const;

export function MonitoringLayout() {
  const { t } = useTranslation('monitoring');
  const { clientId, feedSourceId } = useParams();
  const location = useLocation();
  const currentTab = location.pathname.split('/').pop() ?? 'runs';
  const base = `/clients/${clientId}/feeds/${feedSourceId}/monitoring`;
  return (
    <Tabs value={currentTab}>
      <Tabs.List>
        {TABS.map((tab) => (
          <Tabs.Tab
            key={tab.value}
            value={tab.value}
            renderRoot={(props) => <Link to={`${base}/${tab.path}`} {...props} />}
          >
            {t(tab.labelKey)}
          </Tabs.Tab>
        ))}
      </Tabs.List>
      <Outlet />
    </Tabs>
  );
}