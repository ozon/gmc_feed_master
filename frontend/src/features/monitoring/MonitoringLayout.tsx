import { Tabs } from '@mantine/core';
import { Link, Outlet, useLocation, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';

const TABS = [
  { value: 'runs', path: 'runs', labelKey: 'tabs.runs' },
  { value: 'findings', path: 'findings', labelKey: 'tabs.findings' },
  { value: 'dryRun', path: 'dry-run', labelKey: 'tabs.dryRun' },
] as const;

function resolveTab(pathname: string): string {
  for (const tab of TABS) {
    if (pathname === `/${tab.path}` || pathname.endsWith(`/${tab.path}`)) {
      return tab.value;
    }
  }
  return 'runs';
}

export function MonitoringLayout() {
  const { t } = useTranslation('monitoring');
  const { clientId, feedSourceId } = useParams();
  const location = useLocation();
  const currentTab = resolveTab(location.pathname);
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