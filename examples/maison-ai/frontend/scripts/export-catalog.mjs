import fs from 'node:fs';
import ts from 'typescript';
import {createCatalog,extractCatalogComponentSchemas} from '@copilotkit/a2ui-renderer';
fs.mkdirSync('.local',{recursive:true});
const source=fs.readFileSync('src/app/a2ui/definitions.ts','utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
fs.writeFileSync('.local/definitions.mjs',js);
const {definitions}=await import('../.local/definitions.mjs');
const renderers=Object.fromEntries(Object.keys(definitions).map(name=>[name,()=>null]));
const catalog=createCatalog(definitions,renderers,{catalogId:'copilotkit://maison-restaurant',includeBasicCatalog:true});
fs.mkdirSync('../.local',{recursive:true});
fs.writeFileSync('../.local/catalog.json',JSON.stringify(extractCatalogComponentSchemas(catalog)));
const raw=extractCatalogComponentSchemas(catalog);
const components=Object.fromEntries(Object.keys(definitions).map(name=>{
 const schema=raw.components[name].allOf.find(part=>part.properties);
 return [name,{type:'object',...schema,properties:{id:{type:'string',minLength:1},...schema.properties},required:['id',...schema.required],additionalProperties:false}];
}));
fs.writeFileSync('../backend/data/ui-catalog.json',JSON.stringify({catalogId:raw.catalogId,components},null,2)+'\n');
console.log('Exported the actual renderer catalog for integration checks.');
