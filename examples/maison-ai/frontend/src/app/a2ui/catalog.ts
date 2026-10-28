import {createCatalog} from '@copilotkit/a2ui-renderer';
import {definitions} from './definitions';
import {renderers} from './renderers';
export const catalog=createCatalog(definitions,renderers,{catalogId:'copilotkit://maison-restaurant',includeBasicCatalog:true});
