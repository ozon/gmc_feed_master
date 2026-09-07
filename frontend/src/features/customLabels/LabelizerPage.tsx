import CustomLabelsUI from './CustomLabelsUI';
import type { PluginScope } from '../../api/hooks';

export function LabelizerPage({ pluginId, scope }: { pluginId: string; scope: PluginScope }) {
  return <CustomLabelsUI pluginId={pluginId} scope={scope} onlyTab="ids" />;
}

export default LabelizerPage;
