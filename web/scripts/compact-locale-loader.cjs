// English uses the displayed copy as most translation keys. Store those
// strings once in the bundle, while keeping the authored JSON and the runtime
// resource dictionary unchanged (including explicit translations).
module.exports = function compactLocaleLoader(source) {
  this.cacheable?.();
  const identities = [];
  const translations = [];
  for (const [key, value] of Object.entries(JSON.parse(source))) {
    if (key === value) identities.push(key);
    else translations.push([key, value]);
  }
  return `module.exports = Object.fromEntries([
    ...${JSON.stringify(identities)}.map(key => [key, key]),
    ...${JSON.stringify(translations)}
  ]);`;
};
