import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
const ROOT = process.cwd();
function walk(d, out=[]) {
  for (const e of fs.readdirSync(d,{withFileTypes:true})) {
    if (["node_modules",".next","dist","public","vendor"].includes(e.name)) continue;
    const f = path.join(d,e.name);
    if (e.isDirectory()) walk(f,out);
    else if (/\.tsx?$/.test(e.name)) out.push(f);
  }
  return out;
}
const roots = process.argv.slice(2);
const keys = new Map();
for (const r of roots) {
  for (const file of walk(path.join(ROOT,r))) {
    const src = fs.readFileSync(file,"utf8");
    const sf = ts.createSourceFile(file,src,ts.ScriptTarget.Latest,true, file.endsWith("x")?ts.ScriptKind.TSX:ts.ScriptKind.TS);
    (function visit(n){
      if (ts.isCallExpression(n)) {
        const e = n.expression;
        const isT = (ts.isIdentifier(e)&&(e.text==="t"||e.text==="i18n.t")) ||
          (ts.isPropertyAccessExpression(e)&&e.name.getText(sf)==="t");
        if (isT && n.arguments.length) {
          const a = n.arguments[0];
          if (ts.isStringLiteral(a)||ts.isNoSubstitutionTemplateLiteral(a)) {
            const k = a.text;
            if (!keys.has(k)) keys.set(k,new Set());
            keys.get(k).add(path.relative(ROOT,file));
          }
        }
      }
      ts.forEachChild(n,visit);
    })(sf);
  }
}
console.log(JSON.stringify([...keys].map(([k,v])=>[k,[...v]]),null,0));
