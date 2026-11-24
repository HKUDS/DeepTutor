const expoPreset = require('jest-expo/jest-preset');

module.exports = {
  preset: 'jest-expo',
  moduleDirectories: ['node_modules', '<rootDir>/node_modules'],
  moduleNameMapper: { '^@/(.*)$': '<rootDir>/../../web/$1' },
  // query-string uses a CommonJS bridge to the patched ESM decoder.
  transformIgnorePatterns: expoPreset.transformIgnorePatterns.map(pattern =>
    pattern.replace('|standard-navigation)', '|standard-navigation|decode-uri-component)'),
  ),
};
