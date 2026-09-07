import CustomLabelsUI from './CustomLabelsUI';
import type { PluginScope } from '../../api/hooks';

export function LabelizerSetup({ pluginId, scope }: { pluginId: string; scope: PluginScope }) {
  return <CustomLabelsUI pluginId={pluginId} scope={scope} onlyTab="rules" />;
}

export default LabelizerSetup;
