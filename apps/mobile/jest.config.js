module.exports = {
  preset: '@react-native/jest-preset',
  moduleDirectories: ['node_modules', '<rootDir>/node_modules'],
  moduleNameMapper: { '^@/(.*)$': '<rootDir>/../../web/$1' },
};
