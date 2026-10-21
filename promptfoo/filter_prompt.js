/**
 * Builds the stage-2 request: tidy wording + redact names.
 * Reads the live prompts/report_filter.md, so editing it changes this eval.
 */
const fs = require('fs');
const path = require('path');

module.exports = async function ({ vars }) {
  // Route to the prompt for this document type, exactly as the app does.
  const byType = {
    mantenimiento: 'filter_mantenimiento.md',
    seguridad: 'filter_seguridad.md',
  };
  const promptFile = byType[vars.tipo] || 'filter_mantenimiento.md';
  const system = fs.readFileSync(
    path.resolve(__dirname, '..', 'prompts', promptFile),
    'utf8',
  );
  // promptfoo expands a YAML list in vars into separate test cases, so the
  // entries arrive as one newline-separated block.
  const lines = String(vars.trabajos)
    .split('\n')
    .map((t) => t.trim())
    .filter(Boolean);
  const entries = lines.map((t, i) => `${i + 1}. ${t}`).join('\n');
  return [
    { role: 'system', content: system },
    {
      role: 'user',
      content:
        `FICHA: ${vars.titulo}\nFECHA: ${vars.fecha}\n` +
        `OPERARIOS: ${vars.operarios}\n\nANOTACIONES (${lines.length}):\n${entries}`,
    },
  ];
};
