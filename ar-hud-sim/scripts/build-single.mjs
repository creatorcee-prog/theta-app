// Bundles the app into one self-contained HTML body (dist/hud-optics.html)
// for hosts that serve a single page. three.js still loads from jsDelivr's
// ESM build, so the page needs network access to cdn.jsdelivr.net.
// Usage: npm run build:single
import { build } from 'esbuild';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';

const THREE = 'https://cdn.jsdelivr.net/npm/three@0.160.0';
const cdnThree = {
  name: 'cdn-three',
  setup(b) {
    b.onResolve({ filter: /^three$/ }, () => ({ path: `${THREE}/+esm`, external: true }));
    b.onResolve({ filter: /^three\/addons\// }, (a) => ({ path: `${THREE}/examples/jsm/${a.path.slice('three/addons/'.length)}/+esm`, external: true }));
  },
};

const out = await build({ entryPoints: ['js/main.js'], bundle: true, format: 'esm', write: false, minify: true, plugins: [cdnThree], target: 'es2022' });
const js = out.outputFiles[0].text;
const html = readFileSync('index.html', 'utf8');
const css = readFileSync('css/styles.css', 'utf8');
const body = html.split('<!-- BODY-START -->')[1].split('<!-- BODY-END -->')[0];
const title = html.match(/<title>.*?<\/title>/)[0];
const fonts = html.match(/<link rel="stylesheet" href="https:\/\/fonts[^>]+>/)[0];
const page = `${title}
<meta name="claude:viewport-fit-sides" content="cover">
${fonts}
<style>
${css}
</style>
${body}
<script type="module">
${js.replace(/<\/script/g, '<\\/script')}
</script>
`;
mkdirSync('dist', { recursive: true });
writeFileSync('dist/hud-optics.html', page);
console.log(`dist/hud-optics.html ${(page.length / 1024).toFixed(0)} KB`);
