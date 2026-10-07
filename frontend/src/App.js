import {useState,useEffect,useCallback} from 'react';
import {BrowserRouter,Routes,Route,useLocation} from 'react-router-dom';
import {Toaster,toast} from './components/ui/sonner';
import {Layout} from './components/Layout';
import {AuthDialog} from './components/AuthDialog';
import Dashboard from './pages/Dashboard';
import Connections from './pages/Connections';
import RiskCenter from './pages/RiskCenter';
import Markets from './pages/Markets';
import PaperTrading from './pages/PaperTrading';
import {Signals,Ledger} from './pages/Research';
import {SystemHealth,Settings,Eligibility,Journal,PlannedModule,ModelLab} from './pages/SystemPages';
import {api,errorText} from './lib/api';
import './App.css';
import './readability.css';

function Terminal(){
 const [user,setUser]=useState(null),[overview,setOverview]=useState(null);
 const [auth,setAuth]=useState(false),[apiError,setApiError]=useState(false);
 const location=useLocation();
 const refresh=useCallback(async()=>{
  try{
   const {data}=await api.get('/overview');
   setOverview(data);
   setUser(prev=>prev?.id===data.user?.id?prev:data.user);
   if(data.user&&!sessionStorage.getItem('terminal-csrf')){
    const response=await api.get('/auth/csrf');
    sessionStorage.setItem('terminal-csrf',response.data.csrf_token);
   }
   setApiError(false);
  }catch(e){setApiError(true);}
 },[]);
 useEffect(()=>{refresh();const interval=setInterval(refresh,30000);return()=>clearInterval(interval);},[refresh]);
 useEffect(()=>{window.scrollTo(0,0);},[location.pathname]);
 const logout=async()=>{
  try{await api.post('/auth/logout');sessionStorage.removeItem('terminal-csrf');setUser(null);setOverview(null);refresh();toast.success('Signed out securely.');}
  catch(e){toast.error(errorText(e));}
 };
 const props={user,overview,onAuth:()=>setAuth(true),onRefresh:refresh};
 return <>
  <Layout {...props} onLogout={logout}>
   {apiError&&<div className="form-error" data-testid="api-unavailable-alert">Server connection unavailable. TRADING DISABLED. <button data-testid="retry-api-button" className="text-link" onClick={refresh}>Retry</button></div>}
   <div className="page-enter" key={`${location.pathname}-${user?.id||'public'}`}>
    <Routes>
     <Route path="/" element={<Dashboard {...props}/>}/>
     <Route path="/connections" element={<Connections {...props}/>}/>
     <Route path="/risk" element={<RiskCenter {...props}/>}/>
     <Route path="/markets" element={<Markets {...props}/>}/>
     <Route path="/paper" element={<PaperTrading {...props}/>}/>
     <Route path="/signals" element={<Signals {...props}/>}/>
     <Route path="/ledger" element={<Ledger {...props}/>}/>
     <Route path="/health" element={<SystemHealth {...props}/>}/>
     <Route path="/settings" element={<Settings {...props}/>}/>
     <Route path="/eligibility" element={<Eligibility {...props}/>}/>
     <Route path="/journal" element={<Journal {...props}/>}/>
     <Route path="/models" element={<ModelLab {...props}/>}/>
     {['options','news','backtest'].map(path=><Route path={`/${path}`} key={path} element={<PlannedModule/>}/>)}
     <Route path="*" element={<Dashboard {...props}/>}/>
    </Routes>
   </div>
  </Layout>
  <AuthDialog open={auth} onOpenChange={setAuth} onSuccess={u=>{setUser(u);refresh();toast.success(`Welcome, ${u.name}.`);}}/>
  <Toaster theme="dark" richColors position="bottom-right"/>
 </>;
}
export default function App(){return <BrowserRouter><Terminal/></BrowserRouter>;}