// Protocol: one JSON request on stdin; metadata and digests only on stdout.
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import path from 'node:path';

const input = [];
for await (const part of process.stdin) input.push(part);
const request = JSON.parse(Buffer.concat(input).toString('utf8'));
const require = createRequire(import.meta.url);
const ts = require(path.join(request.root, 'frontend/node_modules/typescript/lib/typescript.js'));
const digest = value => createHash('sha256').update(value).digest('hex');
const file = ts.createSourceFile(request.path, request.text, ts.ScriptTarget.Latest, true);
if (file.parseDiagnostics.length) {
  process.stdout.write(JSON.stringify({error: 'typescript_parse_diagnostics',
    diagnostics: file.parseDiagnostics.map(d => ({code: d.code, start: d.start ?? 0}))}));
  process.exit(2);
}
const sites = [], calls = [], symbols = {}, dependencies = [];
const scopes = [new Map()];
const owners = ['<module>'];
const owner = () => owners.join('.');
const pos = node => {
  const p = file.getLineAndCharacterOfPosition(node.getStart(file));
  return {line: p.line + 1, column: p.character};
};
const shape = node => digest(node.getText(file));
const lookup = name => {
  for (let i = scopes.length - 1; i >= 0; i--) if (scopes[i].has(name)) return scopes[i].get(name);
  return name;
};
const resolve = node => {
  if (ts.isIdentifier(node)) return lookup(node.text);
  if (ts.isPropertyAccessExpression(node)) return `${resolve(node.expression)}.${node.name.text}`;
  if (ts.isElementAccessExpression(node)) return '<dynamic-member>';
  if (ts.isParenthesizedExpression(node)) return resolve(node.expression);
  return '<dynamic-callee>';
};
const site = (node, category, unresolved = []) => sites.push({owner: owner(), ...pos(node),
  category, shape: shape(node), unresolved});
const sql = /(?:^|\.)(?:execute|executemany|executescript|query|raw|RunSQL)$/;
const object = /(?:^|\.)(?:putObject|copyObject|deleteObject|deleteObjects|upload|download|put_object|copy_object|delete_object|delete_objects|upload_file|download_file|send)$/;
const settings = /(?:^|\.)(?:env|environ|settings|config)(?:\.|$)/i;
const namespace = /(?:evidence|backup|tenant|makerspace|private|media|uploads)[/\\]/i;

function visit(node) {
  if (ts.isImportDeclaration(node)) {
    const module = node.moduleSpecifier.text;
    dependencies.push(module);
    const clause = node.importClause;
    if (clause?.name) scopes.at(-1).set(clause.name.text, module);
    const bindings = clause?.namedBindings;
    if (bindings && ts.isNamespaceImport(bindings)) scopes.at(-1).set(bindings.name.text, module);
    if (bindings && ts.isNamedImports(bindings)) for (const e of bindings.elements)
      scopes.at(-1).set(e.name.text, `${module}.${e.propertyName?.text ?? e.name.text}`);
  }
  if (ts.isFunctionLike(node) && node.body) {
    const name = node.name?.getText(file) ?? `<anonymous@${pos(node).line}:${pos(node).column}>`;
    scopes.push(new Map()); owners.push(name);
    symbols[owner()] = shape(node);
    for (const p of node.parameters ?? []) scopes.at(-1).set(p.name.getText(file), '<parameter>');
    ts.forEachChild(node, visit);
    owners.pop(); scopes.pop();
    return;
  }
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) {
    const value = node.initializer;
    const branch = (() => { for (let p = node.parent; p; p = p.parent)
      if (ts.isIfStatement(p) || ts.isConditionalExpression(p) || ts.isIterationStatement(p, false)) return true;
      return false; })();
    scopes.at(-1).set(node.name.text, value && !branch ? resolve(value) : '<unresolved-binding>');
    if (value && (ts.isArrowFunction(value) || ts.isFunctionExpression(value)))
      scopes.at(-1).set(node.name.text, `${owner()}.${node.name.text}`);
  }
  if (ts.isVariableDeclaration(node) && !ts.isIdentifier(node.name))
    site(node, 'unresolved_dynamic', ['destructured_binding_requires_context_review']);
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken) {
    if (ts.isIdentifier(node.left)) scopes.at(-1).set(node.left.text, '<rebound-binding>');
    if (/\.(?:meta|metadata)$/.test(node.left.getText(file))) site(node, 'mixed_semantic');
  }
  if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
    const target = resolve(node.expression);
    calls.push({owner: owner(), target, ...pos(node)});
    if (sql.test(target)) site(node, 'raw_sql');
    if (object.test(target)) site(node, 'object_storage');
    if (/\.(?:save|update|bulk_update|bulk_create)$/.test(target)) site(node, 'mixed_semantic');
    if (/\b(?:eval|Function|exec|spawn|require)$/.test(target) || target.includes('<'))
      site(node, 'unresolved_dynamic', ['dynamic_or_opaque_callee']);
    if (settings.test(target)) site(node, 'settings_environment');
  }
  if ((ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) &&
      settings.test(node.getText(file))) site(node, 'settings_environment');
  if (ts.isPropertyAccessExpression(node) &&
      !(ts.isCallExpression(node.parent) && node.parent.expression === node)) {
    const reference = resolve(node);
    if (sql.test(reference) || object.test(reference))
      site(node, 'unresolved_dynamic', ['primitive_callable_reference_or_escape']);
  }
  if (ts.isElementAccessExpression(node))
    site(node, 'unresolved_dynamic', ['computed_member_requires_context_review']);
  if ((ts.isStringLiteralLike(node) || ts.isTemplateExpression(node)) && namespace.test(node.getText(file)))
    site(node, 'generated_path');
  ts.forEachChild(node, visit);
}
symbols['<module>'] = digest(request.text);
visit(file);
process.stdout.write(JSON.stringify({sites, calls, symbols,
  dependencies: [...new Set(dependencies)].sort(), parser: `typescript-${ts.version}`}));
