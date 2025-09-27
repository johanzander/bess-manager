// frontend/src/lib/api.ts
import axios from 'axios';

// Get the base URL for API requests
const getBaseUrl = () => {
  const currentPath = window.location.pathname;
  
  // Check for Home Assistant ingress pattern
  const ingressMatch = currentPath.match(/^(\/api\/hassio_ingress\/[^/]+\/)/);
  if (ingressMatch && ingressMatch[1]) {
    return ingressMatch[1].slice(0, -1); // Remove trailing slash
  }
  
  // Not in ingress
  return '';
};

// Create an axios instance with the dynamic base URL
const api = axios.create({
  baseURL: getBaseUrl()
});


export default api;