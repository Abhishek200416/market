import axios from 'axios';
export const api = axios.create({baseURL: `${process.env.REACT_APP_BACKEND_URL}/api`, withCredentials:true, timeout:25000});
api.interceptors.request.use(config => { const csrf=sessionStorage.getItem('terminal-csrf'); if(csrf) config.headers['X-CSRF-Token']=csrf; return config; });
let workspaceRequest;
export const openWorkspace = () => {
 if (!workspaceRequest) {
  const bootstrap = async () => {
   const {data} = await api.post('/auth/workspace');
   sessionStorage.setItem('terminal-csrf', data.csrf_token);
   return data.user;
  };
  const request = navigator.locks ? navigator.locks.request('edge-workspace', bootstrap) : bootstrap();
  workspaceRequest = request.finally(() => { workspaceRequest = null; });
 }
 return workspaceRequest;
};
export const errorText = e => typeof e.response?.data?.detail === 'string' ? e.response.data.detail : e.response?.status === 422 ? 'Please check the values in this form.' : 'Connection interrupted. Please try again.';
export const money = n => n == null ? '—' : `₹${Number(n).toLocaleString('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2})}`;
export const formatTime = s => s ? new Date(s).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'short'}) : '—';