import {useState,useEffect,useCallback} from 'react';
import {ThemeProvider} from 'next-themes';
import {LoaderCircle} from 'lucide-react';
import {BrowserRouter,Routes,Route,useLocation} from 'react-router-dom';
import {Toaster} from './components/ui/sonner';
import {Layout} from './components/Layout';
import Dashboard from './pages/Dashboard';
import Connections from './pages/Connections';
import RiskCenter from './pages/RiskCenter';
import Markets from './pages/Markets';
import PaperTrading from './pages/PaperTrading';
import {Signals,Ledger} from './pages/Research';
import {SystemHealth,Settings,Eligibility,Journal,PlannedModule,ModelLab} from './pages/SystemPages';
import {api,openWorkspace,errorText} from './lib/api';
import './App.css';
import './readability.css';
import './workspace.css';

function Terminal(){
 const [user,setUser]=useState(null),[overview,setOverview]=useState(null);
 const [apiError,setApiError]=useState('');
 const location=useLocation();
 const refresh=useCallback(async()=>{
  try{
   await openWorkspace();
   const {data}=await api.get('/overview');
   if(!data.user)throw new Error('This browser must allow workspace cookies.');
   setOverview(data);
   setUser(prev=>prev?.id===data.user.id?prev:data.user);
   setApiError('');
  }catch(e){setApiError(e.response?errorText(e):e.message||'Connection interrupted.');}
 },[]);
 useEffect(()=>{refresh();const interval=setInterval(refresh,30000);return()=>clearInterval(interval);},[refresh]);
 useEffect(()=>{if(!location.hash)window.scrollTo(0,0);},[location.pathname,location.hash]);
 const props={user,overview,onAuth:refresh,onRefresh:refresh};
 return <>
  <Layout {...props}>
   {apiError&&<div className="form-error" role="alert" data-testid="api-unavailable-alert">Workspace connection unavailable. Trading stays disabled until reconnected. {apiError} <button data-testid="retry-api-button" className="text-link" onClick={refresh}>Reconnect workspace</button></div>}
   {!user&&!apiError&&<div className="workspace-loading" role="status" data-testid="workspace-loading"><LoaderCircle className="spin" size={24}/><h1>Opening your workspace</h1><p>No account or password needed.</p></div>}
   {user&&<div className="page-enter" key={`${location.pathname}-${user.id}`}>
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
   </div>}
  </Layout>
  <Toaster richColors position="bottom-right"/>
 </>;
}
export default function App(){return <ThemeProvider attribute="data-theme" defaultTheme="dark" enableSystem storageKey="edge-theme"><BrowserRouter><Terminal/></BrowserRouter></ThemeProvider>;}