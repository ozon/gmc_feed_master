import type { ComponentType } from 'react';
import type { PluginScope } from '../../api/hooks';
import RulesUI from '../../../../plugins/core/rules/frontend/component';
import FilterUI from '../../../../plugins/core/filter/frontend/component';
import CustomLabelsUI from '../../../../plugins/core/custom_labels/frontend/component';

export type CustomComponentProps = { pluginId: string; scope: PluginScope };

// Plugin id -> custom UI component. Extend as core plugins gain custom UIs.
// Full build-time discovery (ADR 0002) replaces this static map as follow-up.
export const CUSTOM_COMPONENTS: Record<string, ComponentType<CustomComponentProps>> = {
  rules: RulesUI,
  filter: FilterUI,
  custom_labels: CustomLabelsUI,
};
