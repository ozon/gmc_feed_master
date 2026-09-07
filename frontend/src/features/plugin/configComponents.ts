import type { ComponentType } from 'react';
import type { PluginScope } from '../../api/hooks';
import { LabelizerSetup } from '../customLabels/LabelizerSetup';

export type ConfigComponentProps = { pluginId: string; scope: PluginScope };

// Plugin id -> Pipeline Editor Setup surface. Extend as plugins split their
// page and config UIs (ADR-0007 two-surface model).
export const CONFIG_COMPONENTS: Record<string, ComponentType<ConfigComponentProps>> = {
  custom_labels: LabelizerSetup,
};
