export const getBasePath = () => {
  if (typeof window !== 'undefined') {
    return process.env.NEXT_PUBLIC_APP_BASE_PATH?.replace(/\/$/, '') || '';
  }
  return process.env.NEXT_PUBLIC_APP_BASE_PATH?.replace(/\/$/, '') || '';
};

export const appPath = (path: string) => {
  const basePath = getBasePath();
  if (!path) return basePath;
  
  // If path is absolute URL, return as is
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path;
  }
  
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  
  if (!basePath) return cleanPath;
  
  return `${basePath}${cleanPath}`;
};
