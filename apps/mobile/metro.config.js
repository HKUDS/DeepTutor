const { getDefaultConfig, mergeConfig } = require('@react-native/metro-config');
const path = require('node:path');

/**
 * Metro configuration
 * https://reactnative.dev/docs/metro
 *
 * @type {import('@react-native/metro-config').MetroConfig}
 */
const webRoot = path.resolve(__dirname, '../../web');
const config = {
  watchFolders: [webRoot],
  resolver: {
    nodeModulesPaths: [path.join(__dirname, 'node_modules')],
    resolveRequest(context, moduleName, platform) {
      const name = moduleName.startsWith('@/')
        ? path.join(webRoot, moduleName.slice(2))
        : moduleName;
      return context.resolveRequest(context, name, platform);
    },
  },
};

module.exports = mergeConfig(getDefaultConfig(__dirname), config);
