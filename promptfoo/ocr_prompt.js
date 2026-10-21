/**
 * Builds the vision request for one fixture page.
 *
 * Reads the live prompt file, so editing prompts/transcription.md changes what
 * this eval measures. Does its own base64 encoding rather than relying on
 * promptfoo's file:// loader, which hands over raw bytes for images.
 */
const fs = require('fs');
const path = require('path');

module.exports = async function ({ vars }) {
  const promptFile = vars.prompt_file || 'transcription.md';
  const instructions = fs.readFileSync(
    path.resolve(__dirname, '..', 'prompts', promptFile),
    'utf8',
  );
  const image = fs.readFileSync(
    path.resolve(__dirname, 'fixtures', `${vars.page}.jpg`),
  ).toString('base64');

  return [
    {
      role: 'user',
      content: [
        { type: 'text', text: instructions },
        {
          type: 'image_url',
          image_url: { url: `data:image/jpeg;base64,${image}` },
        },
      ],
    },
  ];
};
