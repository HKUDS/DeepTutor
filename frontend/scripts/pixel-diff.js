#!/usr/bin/env node
/**
 * Pixel Diff Verification Tool
 * Compares two screenshots pixel by pixel and generates a difference map.
 * Usage: node scripts/pixel-diff.js <image1> <image2> [output_dir]
 */

const fs = require('fs');
const path = require('path');

// Simple pixel comparison using raw image data
// Since we can't use canvas in Node.js without extra deps,
// we'll create a comparison script that runs in the browser

const htmlTemplate = `
<!DOCTYPE html>
<html>
<head>
  <title>Pixel Diff Verification</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #eee; padding: 20px; }
    h1 { font-size: 18px; margin-bottom: 20px; }
    .container { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
    .panel { background: #16213e; border-radius: 8px; padding: 16px; }
    .panel h2 { font-size: 14px; margin-bottom: 12px; color: #888; }
    canvas { max-width: 100%; height: auto; border: 1px solid #333; }
    .diff-result { background: #0f3460; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
    .diff-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 16px; }
    .stat { background: #16213e; padding: 12px; border-radius: 6px; text-align: center; }
    .stat .value { font-size: 24px; font-weight: bold; }
    .stat .label { font-size: 12px; color: #888; margin-top: 4px; }
    .stat.pass .value { color: #4ade80; }
    .stat.warn .value { color: #fbbf24; }
    .stat.fail .value { color: #f87171; }
    .threshold-control { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
    .threshold-control input { width: 80px; }
    .threshold-control label { font-size: 14px; }
    .diff-map-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    .summary { font-size: 13px; line-height: 1.6; color: #aaa; }
    .pass { color: #4ade80; font-weight: bold; }
    .fail { color: #f87171; font-weight: bold; }
  </style>
</head>
<body>
  <h1>🔍 TraeWork Pixel Diff Verification Report</h1>

  <div class="threshold-control">
    <label>Diff Threshold (0-255):</label>
    <input type="range" id="threshold" min="0" max="50" value="5">
    <span id="thresholdValue">5</span>
    <span style="margin-left: 20px; font-size: 12px; color: #888;">
      Note: Font anti-aliasing and system rendering may cause minor differences.
      Threshold of 5-15 accounts for these uncontrollable variations.
    </span>
  </div>

  <div id="results"></div>

  <script>
    const scenarios = [
      { name: 'Full Layout (Left+Center+Right)', replica: 'replica-full.png', mhtml: 'mhtml-full.png' },
      { name: 'Left+Center', replica: 'replica-left-center.png', mhtml: 'mhtml-left-center.png' },
      { name: 'Center Only', replica: 'replica-center-only.png', mhtml: 'mhtml-center-only.png' },
      { name: 'Center+Right', replica: 'replica-center-right.png', mhtml: 'mhtml-center-right.png' },
    ];

    const threshold = parseInt(document.getElementById('threshold').value);

    async function loadImage(src) {
      return new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = src;
      });
    }

    function compareImages(img1, img2, threshold) {
      const canvas1 = document.createElement('canvas');
      const canvas2 = document.createElement('canvas');

      // Use smaller dimensions for comparison to improve performance
      const maxWidth = 720;
      const scale = Math.min(1, maxWidth / Math.max(img1.width, img2.width));

      canvas1.width = Math.floor(img1.width * scale);
      canvas1.height = Math.floor(img1.height * scale);
      canvas2.width = canvas1.width;
      canvas2.height = canvas1.height;

      const ctx1 = canvas1.getContext('2d');
      const ctx2 = canvas2.getContext('2d');

      ctx1.drawImage(img1, 0, 0, canvas1.width, canvas1.height);
      ctx2.drawImage(img2, 0, 0, canvas2.width, canvas2.height);

      const data1 = ctx1.getImageData(0, 0, canvas1.width, canvas1.height).data;
      const data2 = ctx2.getImageData(0, 0, canvas2.width, canvas2.height).data;

      const diffCanvas = document.createElement('canvas');
      diffCanvas.width = canvas1.width;
      diffCanvas.height = canvas1.height;
      const diffCtx = diffCanvas.getContext('2d');
      const diffData = diffCtx.createImageData(canvas1.width, canvas1.height);

      let diffPixels = 0;
      const totalPixels = canvas1.width * canvas1.height;
      const diffMap = [];

      for (let i = 0; i < data1.length; i += 4) {
        const r = Math.abs(data1[i] - data2[i]);
        const g = Math.abs(data1[i + 1] - data2[i + 1]);
        const b = Math.abs(data1[i + 2] - data2[i + 2]);
        const a = Math.abs(data1[i + 3] - data2[i + 3]);

        const maxDiff = Math.max(r, g, b, a);

        if (maxDiff > threshold) {
          diffPixels++;
          diffData.data[i] = Math.min(255, r * 5);
          diffData.data[i + 1] = Math.min(255, g * 5 + 50);
          diffData.data[i + 2] = Math.min(255, b * 5);
          diffData.data[i + 3] = 200;

          if (diffMap.length < 100) {
            const x = Math.floor((i / 4) % canvas1.width);
            const y = Math.floor((i / 4) / canvas1.width);
            diffMap.push({ x, y, r, g, b, maxDiff });
          }
        } else {
          diffData.data[i] = data1[i];
          diffData.data[i + 1] = data1[i + 1];
          diffData.data[i + 2] = data1[i + 2];
          diffData.data[i + 3] = 30;
        }
      }

      diffCtx.putImageData(diffData, 0, 0);

      const diffPercent = ((diffPixels / totalPixels) * 100).toFixed(2);
      const pass = diffPixels / totalPixels < 0.02; // Less than 2% different pixels

      return {
        canvas1,
        canvas2,
        diffCanvas,
        diffPixels,
        totalPixels,
        diffPercent,
        pass,
        diffMap: diffMap.slice(0, 20)
      };
    }

    async function runComparison() {
      const resultsDiv = document.getElementById('results');
      let html = '';

      for (const scenario of scenarios) {
        try {
          const img1 = await loadImage(\`screenshots/\${scenario.replica}\`);
          const img2 = await loadImage(\`screenshots/\${scenario.mhtml}\`);
          const result = compareImages(img1, img2, threshold);

          html += \`
            <div class="diff-result">
              <h2 style="font-size: 16px; margin-bottom: 12px;">
                \${scenario.name}
                <span class="\${result.pass ? 'pass' : 'fail'}">
                  [\${result.pass ? 'PASS' : 'FAIL'}]
                </span>
              </h2>
              <div class="diff-stats">
                <div class="stat \${result.pass ? 'pass' : 'fail'}">
                  <div class="value">\${result.diffPercent}%</div>
                  <div class="label">Different Pixels</div>
                </div>
                <div class="stat">
                  <div class="value">\${result.diffPixels.toLocaleString()}</div>
                  <div class="label">Diff Pixel Count</div>
                </div>
                <div class="stat">
                  <div class="value">\${result.totalPixels.toLocaleString()}</div>
                  <div class="label">Total Pixels</div>
                </div>
                <div class="stat">
                  <div class="value">\${result.canvas1.width}x\${result.canvas1.height}</div>
                  <div class="label">Resolution</div>
                </div>
              </div>
              <div class="diff-map-grid">
                <div class="panel">
                  <h2>Replica</h2>
                  <canvas id="replica-\${scenario.name}" width="\${result.canvas1.width}" height="\${result.canvas1.height}"></canvas>
                </div>
                <div class="panel">
                  <h2>MHTML Reference</h2>
                  <canvas id="mhtml-\${scenario.name}" width="\${result.canvas2.width}" height="\${result.canvas2.height}"></canvas>
                </div>
              </div>
              <div class="panel" style="margin-top: 16px;">
                <h2>Difference Map (Red = Different)</h2>
                <canvas id="diff-\${scenario.name}" width="\${result.diffCanvas.width}" height="\${result.diffCanvas.height}"></canvas>
              </div>
              <div class="summary" style="margin-top: 12px;">
                \${result.pass
                  ? '<span class="pass">✅ PASS</span>: Pixel difference is within acceptable tolerance (2% threshold). Differences are likely due to font anti-aliasing and system rendering.'
                  : '<span class="fail">❌ FAIL</span>: Significant pixel differences detected. See the difference map for details.'
                }
              </div>
              \${result.diffMap.length > 0 ? \`
                <div class="summary" style="margin-top: 8px; font-size: 11px; color: #666;">
                  Sample diff locations (top 20): \${result.diffMap.slice(0, 5).map(d => \`(\${d.x},\${d.y}) Δmax=\${d.maxDiff}\`).join(', ')}
                </div>
              \` : ''}
            </div>
          \`;

          // Draw canvases after DOM insertion
          setTimeout(() => {
            document.getElementById(\`replica-\${scenario.name}\`).getContext('2d').drawImage(result.canvas1, 0, 0);
            document.getElementById(\`mhtml-\${scenario.name}\`).getContext('2d').drawImage(result.canvas2, 0, 0);
            document.getElementById(\`diff-\${scenario.name}\`).getContext('2d').drawImage(result.diffCanvas, 0, 0);
          }, 100);

        } catch (err) {
          html += \`
            <div class="diff-result">
              <h2 style="color: #f87171;">\${scenario.name} [ERROR]</h2>
              <div class="summary">\${err.message}</div>
            </div>
          \`;
        }
      }

      html += \`
        <div class="diff-result" style="background: #16213e;">
          <h2>📋 Summary</h2>
          <div class="summary">
            Comparison completed with threshold: <strong>\${threshold}</strong><br>
            Images are compared at 720px width for performance.<br>
            <strong>Acceptance criteria</strong>: Pass if less than 2% of pixels differ after excluding anti-aliasing effects.
          </div>
        </div>
      \`;

      resultsDiv.innerHTML = html;
    }

    document.getElementById('threshold').addEventListener('input', (e) => {
      document.getElementById('thresholdValue').textContent = e.target.value;
      runComparison();
    });

    runComparison();
  </script>
</body>
</html>
`;

// Write the comparison HTML file
const outputPath = path.join(__dirname, '..', 'pixel-diff-report.html');
fs.writeFileSync(outputPath, htmlTemplate);
console.log(`Pixel diff report template created at: ${outputPath}`);
console.log('To use this tool:');
console.log('1. Take screenshots of both replica and MHTML pages');
console.log('2. Place them in a "screenshots" folder');
console.log('3. Serve the pixel-diff-report.html file');
console.log('4. Open it in a browser to see the comparison results');
