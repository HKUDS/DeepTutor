const { getDefaultConfig } = require('expo/metro-config');
const path = require('node:path');

const webRoot = path.resolve(__dirname, '../../web');
const config = getDefaultConfig(__dirname);
config.watchFolders = [...new Set([...config.watchFolders, webRoot])];
config.resolver.nodeModulesPaths = [
  path.join(__dirname, 'node_modules'),
  ...(config.resolver.nodeModulesPaths ?? []),
];
const expoResolve = config.resolver.resolveRequest;
config.resolver.resolveRequest = (context, moduleName, platform) => {
  const name = moduleName.startsWith('@/')
    ? path.join(webRoot, moduleName.slice(2))
    : moduleName;
  return (expoResolve ?? context.resolveRequest)(context, name, platform);
};

module.exports = config;
